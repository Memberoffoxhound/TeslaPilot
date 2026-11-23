# the mici models panel (zoompilot's, big models only): builds, shows a download, and its buttons write the params
import json
import os
import subprocess
import sys
import textwrap

PROBE = textwrap.dedent('''
  import json, sys, time, types
  from enum import Enum
  from types import SimpleNamespace
  from openpilot.common.params import Params
  from openpilot.cereal import custom

  params = Params()
  class CS(Enum):
    DISCONNECTED = "disconnected"
    UNCOMPILED = "uncompiled"
    READY = "ready"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"
    WAITING = "waiting"
  ds = custom.ModelManagerSP.DownloadStatus
  mm = custom.ModelManagerSP.new_message()
  b = mm.init('availableBundles', 2)
  for i, (ref, name, folder) in enumerate((("aaa", "Light Speed 2", "2026 Deep RL Models"), ("bbb", "Old One", "2025"))):
    b[i].ref, b[i].displayName, b[i].internalName, b[i].index = ref, name, name, 10 - i
    o = b[i].init('overrides', 1)
    o[0].key, o[0].value = "folder", folder
  class SM(dict):
    alive = {"modelManagerSP": True}
  timeouts = []
  ui = SimpleNamespace(started=False, params=params, chestnut_present=True, chestnut_state=CS.UNCOMPILED, chestnut_active=None,
                       chestnut_loading=False, chestnut_compiled=False, jetlink=None, is_offroad=lambda: True,
                       sm=SM({"modelManagerSP": mm}))
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state, mod.ChestnutState = ui, CS
  mod.device = SimpleNamespace(set_override_interactive_timeout=timeouts.append, awake=True)
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mod

  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "models")
  gui_app._load_fonts()
  from openpilot.selfdrive.ui.mici.layouts.settings import models

  out = {}
  lay = models.ModelsLayoutMici()
  lay.set_rect(rl.Rectangle(0, 0, 536, 240))
  info = lay.current_model_info
  def texts():
    return [info.current_model_text.text, info.info_header.text, info.info_text.text]
  lay._update_state()
  out["idle"] = texts()
  out["link_visible"] = lay.link_toggle.is_visible

  sel = mm.init('selectedBundle')
  sel.ref, sel.internalName, sel.status = "aaa", "LS2", ds.downloading
  m = sel.init('models', 1)
  m[0].artifact.downloadProgress.status = ds.downloading
  m[0].artifact.downloadProgress.progress = 42.5
  m[0].artifact.downloadProgress.speed = 3 * 1024 ** 2
  params.put("ModelManager_DownloadRef", "aaa", block=True)
  lay._update_state()
  out["downloading"] = [info.current_model_header.text] + texts()
  out["cancel_visible"] = lay.cancel_download_btn.is_visible
  out["timeouts"] = timeouts[:]
  tex = rl.load_render_texture(536, 240)
  rl.begin_texture_mode(tex)
  lay.render(rl.Rectangle(0, 0, 536, 240))
  rl.end_texture_mode()

  lay.cancel_download_btn._click_callback()
  time.sleep(0.3)  # the panel writes params without blocking
  out["cancelled"] = params.get("ModelManager_DownloadRef") is None
  pushed = []
  gui_app.push_widget = pushed.append
  gui_app.pop_widgets_to = lambda *a, **k: None
  lay._show_folders()
  out["folders"] = [w.text for w in pushed[-1]._scroller._items]
  lay._select_folder("2026 Deep RL Models")
  out["models"] = [w.text for w in pushed[-1]._scroller._items]
  lay._select_model(b[0])
  time.sleep(0.3)  # the panel writes params without blocking
  out["queued"] = params.get("ModelManager_DownloadRef")
  params.put("ModelManager_ActiveBundleChestnut", {"ref": "x"}, block=True)
  lay._select_default()
  time.sleep(0.3)  # the panel writes params without blocking
  out["slot_reset"] = params.get("ModelManager_ActiveBundleChestnut") is None
  lay._refresh_models()
  time.sleep(0.3)  # the panel writes params without blocking
  out["sync_zeroed"] = params.get("ModelManager_LastSyncTime_Chestnut") == 0
  ui.chestnut_present = False
  ui.jetlink = SimpleNamespace(port_state=None)
  lay._download_frame = -1
  lay._update_state()
  out["link_visible_no_chestnut"] = lay.link_toggle.is_visible
  print("RESULT" + json.dumps(out))
''')


def test_models_panel(tmp_path):
  env = {**os.environ, 'PARAMS_ROOT': str(tmp_path / 'params')}
  r = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True, env=env, timeout=120)
  line = next((ln for ln in r.stdout.splitlines() if ln.startswith('RESULT')), None)
  assert line is not None, r.stdout[-2000:] + r.stderr[-4000:]
  out = json.loads(line[len('RESULT'):])
  assert out["idle"][1] == "big model"
  assert out["idle"][2] == "not downloaded"
  assert out["link_visible"] is False, "beside a chestnut the Jetlink toggle is hidden"
  assert out["downloading"][0] == "downloading"
  assert out["downloading"][1].startswith("ls2")
  assert out["downloading"][3] == "42.50%  |  3.0 MB/s"
  assert out["cancel_visible"] is True and 5 in out["timeouts"]
  assert out["cancelled"]
  assert out["folders"] == ["light speed 2 (default)", "2026 deep rl models", "2025"]
  assert out["models"] == ["light speed 2"]
  assert out["queued"] == "aaa"
  assert out["slot_reset"] and out["sync_zeroed"]
  assert out["link_visible_no_chestnut"] is True
