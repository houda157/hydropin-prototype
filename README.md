# hydropin-prototype

How to run everything, in a few commands.

## Layout

- `contract/` shared agreement, changed only together
- `broker/` local MQTT broker
- `firmware/` ESP32, PlatformIO project
- `hydropin/` shared Python code
- `simulator/` simulated bench data
- `backend/` FastAPI app + MQTT listener
- `detection/` leak detection
- `dashboard/` live Streamlit dashboard
- `data/` runs, database, calibration
- `docs/` wiring + test protocol
