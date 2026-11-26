"""Layer 3 – steady.

Steady-state / extended-period twin: runs WNTR with pressure-driven demand and
leaks, Monte Carlo scenario sampling, tidy SteadyResult output.

Math note sections: §2, §2.9
Built in: hydraulics + sensors
Allowed imports: hydropin_sim modules of a lower layer only (enforced by tests/test_architecture.py).
"""
