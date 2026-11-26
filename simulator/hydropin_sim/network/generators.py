"""Reference networks: the test bench and a parametric demo drip farm. Math note §1.

Both return a validated NetworkSpec. Dimensions are placeholders until the
hardware team sends the bench layout and the pilot farm survey (Architecture D3).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from hydropin_sim.contracts import NetworkSpec
from hydropin_sim.physics.pump import pump_curve_from_points

# Pipe catalogue: (outside diameter m, SDR)
PE100_63_SDR11 = (0.063, 11.0)
PE100_75_SDR11 = (0.075, 11.0)
PVC_90_PN10 = (0.090, 21.0)


def _pipe(pid, a, b, material, length, spec, k_minor=0.0):
    d_out, sdr = spec
    return dict(id=pid, start=a, end=b, material=material, length=float(length),
                d_out=d_out, e_wall=d_out / sdr, k_minor=k_minor)


def bench_spec(length=150.0, leak_points=(40.0, 80.0, 120.0), q_design=0.002) -> NetworkSpec:
    """Straight HDPE PE100 Ø63 SDR11 test line fed by a pump from a tank.

    Nodes at every leak-valve position; the far end is the flush valve (fixed
    partly-open outlet giving about q_design at about 20 m of pressure).
    """
    xs = [0.0, *leak_points, length]
    nodes = [dict(id="TANK", kind="source", x=-5.0, y=0.0, z=0.0, head=1.0),
             dict(id="B0", kind="junction", x=0.0, y=0.0, z=0.0)]
    for x in leak_points:
        nodes.append(dict(id=f"B{int(x)}", kind="junction", x=x, y=0.0, z=0.0))
    nodes.append(dict(id="END", kind="flush_valve", x=length, y=0.0, z=0.0,
                      outlet_coeff=q_design / 20.0 ** 0.5))
    ids = ["B0", *[f"B{int(x)}" for x in leak_points], "END"]
    pipes = [_pipe(f"L{i + 1}", ids[i], ids[i + 1], "PE100", xs[i + 1] - xs[i], PE100_63_SDR11)
             for i in range(len(ids) - 1)]
    pump = dict(id="PUMP", start="TANK", end="B0", h0=35.0,
                r=pump_curve_from_points(q_design, 25.0, 35.0, 2.0), n=2.0)
    return NetworkSpec(name="bench", description="Test bench placeholder: 150 m HDPE PE100 Ø63 SDR11, "
                       "leak valves at 40/80/120 m, flush valve at the end",
                       nodes=nodes, pipes=pipes, pumps=[pump])


def demo_farm_spec(n_sectors=4, blocks_per_sector=3, laterals_per_block=10,
                   lateral_length=80.0, lateral_d_int=0.0136, row_spacing=1.0,
                   sector_spacing=90.0, slope_x=0.003, slope_y=0.006) -> NetworkSpec:
    """Parametric drip farm: basin + pump, PVC Ø90 main, one PE Ø75 sub-main per
    sector behind an on/off valve, manifolds ("lateral blocks") feeding
    `laterals_per_block` laterals that run along +x.

    Terrain: z = slope_x * x + slope_y * y (rising away from the pump).
    """
    def z(x, y):
        return round(slope_x * x + slope_y * y, 4)

    nodes = [dict(id="BASIN", kind="source", x=-10.0, y=0.0, z=0.0, head=0.0),
             dict(id="HEAD", kind="junction", x=0.0, y=0.0, z=0.0)]
    pipes, valves, blocks, sectors = [], [], [], []
    prev = "HEAD"
    block_w = laterals_per_block * row_spacing
    for k in range(1, n_sectors + 1):
        xm = 20.0 + sector_spacing * (k - 1)
        m_id = f"M{k}"
        nodes.append(dict(id=m_id, kind="junction", x=xm, y=0.0, z=z(xm, 0)))
        x_prev = 0.0 if prev == "HEAD" else 20.0 + sector_spacing * (k - 2)
        pipes.append(_pipe(f"MAIN{k}", prev, m_id, "PVC", xm - x_prev, PVC_90_PN10))
        prev = m_id
        s_id = f"S{k}"
        nodes.append(dict(id=s_id, kind="junction", x=xm, y=2.0, z=z(xm, 2)))
        pipes.append(_pipe(f"V{k}", m_id, s_id, "PE100", 2.0, PE100_75_SDR11, k_minor=2.0))
        valves.append(dict(id=f"VALVE{k}", pipe=f"V{k}"))
        up, y_up = s_id, 2.0
        members = []
        for i in range(1, blocks_per_sector + 1):
            yb = 2.0 + block_w * (i - 0.5)
            b_id = f"B{k}{i}"
            nodes.append(dict(id=b_id, kind="lateral_block", x=xm, y=yb, z=z(xm, yb)))
            pipes.append(_pipe(f"SUB{k}{i}", up, b_id, "PE100", yb - y_up, PE100_75_SDR11))
            blocks.append(dict(node=b_id, n_laterals=laterals_per_block,
                               lateral_length=lateral_length, lateral_d_int=lateral_d_int,
                               slope=-slope_x))
            members.append(b_id)
            up, y_up = b_id, yb
        sectors.append(dict(id=f"SECTOR{k}", valve=f"VALVE{k}", lateral_blocks=members))
    pump = dict(id="PUMP", start="BASIN", end="HEAD", h0=28.0,
                r=pump_curve_from_points(0.0064, 18.0, 28.0, 2.0), n=2.0)
    return NetworkSpec(
        name="farm_demo",
        description=(f"Demo drip farm: {n_sectors} sectors × {blocks_per_sector} manifolds × "
                     f"{laterals_per_block} laterals of {lateral_length:.0f} m Ø16 "
                     f"({n_sectors * blocks_per_sector * laterals_per_block * lateral_length * row_spacing / 1e4:.2f} ha)"),
        nodes=nodes, pipes=pipes, pumps=[pump], valves=valves,
        lateral_blocks=blocks, sectors=sectors)


def save_spec(spec: NetworkSpec, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = spec.model_dump(mode="json", exclude_none=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def load_spec(path: Path) -> NetworkSpec:
    return NetworkSpec(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))
