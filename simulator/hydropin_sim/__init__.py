"""HydroPin simulation package.

Layers (a module may only import from layers below it):
    0  config, contracts
    1  physics
    2  network
    3  steady
    4  transient
    5  sensors
    6  methods
    7  fusion, placement
    8  viz
See docs/architecture.md.
"""

__version__ = "0.1.0"
