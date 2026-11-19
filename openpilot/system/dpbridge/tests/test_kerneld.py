from openpilot.system.dpbridge import kerneld
from openpilot.system.dpbridge.kerneld import last_error, parse_status, should_flash, step

SHA = "f" * 64
STATUS = f"state=offer\nslot=_b\ntarget=_a\nagnos=20.6\nimage_agnos=20.6\nsha={SHA}\nimage=missing\nfree_mb=900\nneed_mb=200\n"


def fake_sh(status=STATUS, flash_rc=0, flash_out=""):
  calls = []
  def run(args, timeout):
    calls.append(args)
    if args[0] == "status":
      return 0, status
    return flash_rc, flash_out
  return run, calls


def test_parse_status():
  st = parse_status(STATUS + "garbage line\n")
  assert st["state"] == "offer" and st["slot"] == "_b" and st["target"] == "_a" and st["sha"] == SHA


def test_should_flash_offroad_offer_only():
  st = parse_status(STATUS)
  assert should_flash(st, onroad=False)
  assert not should_flash(st, onroad=True)
  for state in ("ok", "failed", "pending", "onroad", "no_space", "unsupported_agnos", "unsupported_device", "error"):
    assert not should_flash(dict(st, state=state), onroad=False)


def test_step_flashes_on_its_own(tmp_path, monkeypatch):
  monkeypatch.setattr(kerneld, "STATE_PATH", str(tmp_path / "k.json"))
  run, calls = fake_sh()
  st = step(run, onroad=False, prev={})
  assert calls == [["status"], ["flash", "--yes"]] and st["phase"] == "idle"


def test_step_never_flashes_onroad(tmp_path, monkeypatch):
  monkeypatch.setattr(kerneld, "STATE_PATH", str(tmp_path / "k.json"))
  run, calls = fake_sh()
  step(run, onroad=True, prev={})
  assert calls == [["status"]]


def test_step_does_not_repeat_a_failure(tmp_path, monkeypatch):
  monkeypatch.setattr(kerneld, "STATE_PATH", str(tmp_path / "k.json"))
  run, _ = fake_sh(flash_rc=1, flash_out="+ x\nrefusing: downloaded boot.img does not match the pinned sha\n")
  st = step(run, onroad=False, prev={})
  assert st["phase"] == "failed" and st["error"] == "downloaded boot.img does not match the pinned sha"
  run2, calls = fake_sh()
  st2 = step(run2, onroad=False, prev=st)
  assert st2["phase"] == "failed" and calls == [["status"]]


def test_step_leaves_other_states_alone(tmp_path, monkeypatch):
  monkeypatch.setattr(kerneld, "STATE_PATH", str(tmp_path / "k.json"))
  for state in ("ok", "unsupported_agnos", "failed"):
    run, calls = fake_sh(status=STATUS.replace("state=offer", f"state={state}"))
    step(run, onroad=False, prev={})
    assert calls == [["status"]]


def test_last_error():
  assert last_error("a\nrefusing: no space\n") == "no space"
  assert last_error("boom") == "flash failed"
