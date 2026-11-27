"""M2 on the virtual farm: common mode removed, fingerprint per leak site, cosine -> probabilities.

The same idea as on the bench (detection/bench_detector.py): a leak lowers every pressure by
about the same amount (the pump slides down its curve), so the first healthy/leak principal
direction is the common mode; what is left - the leak residual's "fingerprint" over the
sensors - says where the leak is.

  * residual r = measured - healthy baseline at the chosen sensors (gnn/X.npy, noisy),
    restricted to sensors that are pressurised in that shift;
  * detected if some |r| > k * sigma;
  * common mode removed: r - mean(r);
  * fingerprint per (shift, site) = mean unit direction of the training scenarios' residuals
    (worlds 0-6, all sizes that were detected);
  * matched-subspace likelihood per site: the residual is modelled as a * fingerprint +
    common mode + Gaussian noise (sigma, plus the baseline's own noise), a >= 0, so
    log p(site) = max(0, D . u_site)^2 / (2 sigma_eff^2) + const. Big leaks give sharp maps,
    leaks near the noise give flat ones. The ranking equals the cosine ranking.
"""
from __future__ import annotations

import numpy as np

from farm.methods.common import FarmData

K_SIGMA = 3.0


class FarmM2:
    def __init__(self, fd: FarmData, sensors: list[str], k: float = K_SIGMA):
        self.fd, self.k = fd, k
        self.cols = np.array([fd.nodes.index(s) for s in sensors])
        self.sensors = sensors
        self.sigma_eff = fd.sigma_eff
        self.fp: dict[int, np.ndarray] = {}      # shift -> [n_sites x n_sensors], NaN where unknown

    def _resid(self, rows: np.ndarray):
        R = self.fd.X[np.ix_(rows, self.cols)]
        live = np.abs(R) > 1e-12                 # unpressurised nodes read exactly 0
        return R, live

    def detected(self, rows: np.ndarray) -> np.ndarray:
        R, live = self._resid(rows)
        return ((np.abs(R) > self.k * self.fd.sigma_eff) & live).any(axis=1)

    @staticmethod
    def _centred(R: np.ndarray, live: np.ndarray) -> np.ndarray:
        cnt = np.maximum(live.sum(axis=1, keepdims=True), 1)
        mean = np.where(live, R, 0).sum(axis=1, keepdims=True) / cnt
        return np.where(live, R - mean, 0.0)

    @classmethod
    def _direction(cls, R: np.ndarray, live: np.ndarray) -> np.ndarray:
        D = cls._centred(R, live)
        nrm = np.linalg.norm(D, axis=1, keepdims=True)
        return D / np.where(nrm > 0, nrm, 1.0)

    def fit(self):
        fd = self.fd
        rows = np.where(fd.train)[0]
        det = self.detected(rows)
        rows = rows[det]
        R, live = self._resid(rows)
        D = self._direction(R, live)
        cfg = fd.sc.config_id.to_numpy()[rows]
        site = fd.site_idx[rows]
        for c in np.unique(fd.sc.config_id):
            F = np.full((len(fd.sites), len(self.cols)), np.nan)
            for s in np.unique(site[cfg == c]):
                m = (cfg == c) & (site == s)
                v = D[m].mean(axis=0)
                n = np.linalg.norm(v)
                F[s] = v / n if n > 0 else 0.0
            self.fp[int(c)] = F
        return self

    def predict(self, rows: np.ndarray) -> np.ndarray:
        """[len(rows) x n_sites] probabilities (zero for sites not possible in that shift)."""
        R, live = self._resid(rows)
        D = self._centred(R, live)
        cfg = self.fd.sc.config_id.to_numpy()[rows]
        P = np.zeros((len(rows), len(self.fd.sites)))
        for i, c in enumerate(cfg):
            F = self.fp[int(c)]
            ok = ~np.isnan(F[:, 0])
            proj = np.maximum(F[ok] @ D[i], 0.0)
            ll = proj ** 2 / (2 * self.sigma_eff ** 2)
            z = ll - ll.max()
            e = np.exp(z)
            P[i, ok] = e / e.sum()
        return P
