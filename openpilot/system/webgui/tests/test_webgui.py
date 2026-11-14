import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from openpilot.system.webgui import webgui as W


@pytest.fixture
def env(tmp_path):
  app = W.App(tmp_path)
  app.shots.mkdir(parents=True)
  srv = W.make_server(app, "127.0.0.1", 0)
  threading.Thread(target=srv.serve_forever, daemon=True).start()
  yield app, f"http://127.0.0.1:{srv.server_address[1]}"
  srv.shutdown()


def req(url, method="GET", body=None, raw=False, ctype="application/json"):
  h = {"Content-Type": ctype}
  r = urllib.request.Request(url, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
  try:
    with urllib.request.urlopen(r, timeout=5) as resp:
      data = resp.read()
      return resp.status, (data if raw else json.loads(data or b"{}")), resp.headers
  except urllib.error.HTTPError as e:
    return e.code, json.loads(e.read() or b"{}"), e.headers


# --- path traversal ---
@pytest.mark.parametrize("name", ["../secret.png", "..%2Fsecret.png", "%2e%2e%2fsecret.png", "a/../../x.png",
                                  ".hidden.png", "x.png/..", "evil.sh", "a.png.sh", "..png", "a..png"])
def test_traversal_rejected(env, name):
  app, u = env
  (app.data / "x.png").write_bytes(b"secret")
  (app.data / "secret.png").write_bytes(b"secret")
  assert req(u + "/media/shots/" + name)[0] == 404
  assert req(u + "/api/shots/" + name, "DELETE")[0] == 404
  assert (app.data / "secret.png").exists() and (app.data / "x.png").exists()


def test_symlink_rejected(env):
  app, u = env
  (app.data / "secret.png").write_bytes(b"s")
  os.symlink(app.data / "secret.png", app.shots / "link.png")
  assert req(u + "/media/shots/link.png")[0] == 404
  assert req(u + "/api/shots/link.png", "DELETE")[0] == 404
  assert (app.data / "secret.png").exists()


def test_shot_list_view_delete(env):
  app, u = env
  (app.shots / "2026-10-29--10-00-00.png").write_bytes(b"0123456789")
  (app.shots / "notes.txt").write_text("x")
  _, j, _ = req(u + "/api/shots")
  assert [f["name"] for f in j["items"]] == ["2026-10-29--10-00-00.png"]
  code, body, h = req(u + "/media/shots/2026-10-29--10-00-00.png?dl=1", raw=True)
  assert code == 200 and body == b"0123456789" and h["Content-Disposition"].startswith("attachment")
  assert req(u + "/api/shots/2026-10-29--10-00-00.png", "DELETE")[0] == 200
  assert req(u + "/api/shots")[1]["items"] == []


def test_capture_writes_request(env):
  app, _ = env
  assert app.capture(wait_s=0.2) == {"ok": True, "pending": True}
  assert app.shot_req.read_text() == "1"


def test_mock_stats_labelled(tmp_path):
  app = W.App(tmp_path, mock=True)
  s = app.stats()
  assert s["mock"] and set(s["src"].values()) == {"MOCK"}


def test_param_keys_exist():
  import re
  from pathlib import Path
  from openpilot.system.webgui import stats
  src = (Path(stats.__file__).parents[2] / "common/params_keys.h").read_text()
  keys = set(re.findall(r'\{"(\w+)",', src))
  assert set(stats.PARAMS) <= keys
  used = set(re.findall(r'p\.get(?:_bool)?\("(\w+)"', Path(stats.__file__).read_text()) +
             re.findall(r'_s\(p, "(\w+)"\)', Path(stats.__file__).read_text()))
  assert used and used <= set(stats.PARAMS)


def test_fonts_public_whitelisted(env):
  _, u = env
  for f in W.FONTS:
    code, body, h = req(u + "/font/" + f, raw=True)
    assert code == 200 and h["Content-Type"] == "font/ttf" and len(body) > 10000
  for bad in ("Inter-Bold.ttf", "..%2Fsecret.png", "../../common/params.py", "TESLA-LICENSE.txt"):
    assert req(u + "/font/" + bad)[0] == 404


def test_no_auth(env):
  _, u = env
  assert req(u + "/", raw=True)[0] == 200 and req(u + "/api/stats")[0] == 200 and req(u + "/api/shots")[0] == 200


def test_post_requires_json(env):
  app, u = env
  assert req(u + "/api/shots", "POST", {}, ctype="text/plain")[0] == 415
  assert not app.shot_req.exists()


def test_rec_endpoints_gone(env):
  _, u = env
  assert req(u + "/api/rec")[0] == 404
  assert req(u + "/api/rec/start", "POST", {})[0] == 404
  assert req(u + "/api/rec/stop", "POST", {})[0] == 404
  assert req(u + "/media/recs/a.mp4")[0] == 404
