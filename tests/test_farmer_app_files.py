"""The farmer app is served by the backend and installable (manifest, service worker, icons)."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app"


def test_manifest_on_disk():
    m = json.loads((APP / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["start_url"] == "./" and m["scope"] == "./" and m["display"] == "standalone"
    assert m["theme_color"] == "#15803D" and m["background_color"] == "#F0FDF4"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


def test_app_is_served_and_installable(tmp_path):
    app = create_app(db_path=tmp_path / "a.db", baseline_path=None, start_mqtt=False)
    with TestClient(app) as client:
        page = client.get("/app/")
        assert page.status_code == 200 and "manifest.webmanifest" in page.text and "apple-touch-icon" in page.text
        man = client.get("/app/manifest.webmanifest")
        assert man.status_code == 200
        for icon in man.json()["icons"]:
            assert client.get(f"/app/{icon['src']}").status_code == 200, icon["src"]
        js = client.get("/app/main.js")
        assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
        sw = client.get("/app/sw.js")
        assert sw.status_code == 200 and "hydropin-app-v1" in sw.text
        assert client.get("/app/icons/apple-touch-icon.png").status_code == 200
