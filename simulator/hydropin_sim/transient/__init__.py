"""Layer 4 – transient.

Own method-of-characteristics solver: grid and Courant adjustment, boundaries
(source, pump, junction, dead end, leak, dripper, valve), unsteady friction,
viscoelasticity, frequency-domain transfer matrices.

Math note sections: §5
Built in: the pressure-wave studies (solver, leak echoes, M3)
Allowed imports: hydropin_sim modules of a lower layer only (enforced by tests/test_architecture.py).
"""
