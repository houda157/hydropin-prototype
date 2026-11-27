"""Layer 2 – network.

Builds networks from a NetworkSpec: bench and synthetic farm generators,
lateral aggregation, conversion to a WNTR model and .inp export.

Math note sections: §1, §2.4
Allowed imports: hydropin_sim modules of a lower layer only (enforced by tests/test_architecture.py).
"""
