from types import SimpleNamespace as NS

import pytest
from opendbc.car.structs import car
from openpilot.selfdrive.ui import fingerprint_prompt as fp


class SM(dict):
  recv_frame = {"carParams": 20}


@pytest.fixture
def prompt(monkeypatch):
  cp = car.CarParams.new_message(brand="mock").as_reader()
  ui = NS(started=True, ignition=True, engaged=False, started_frame=10,
          sm=SM(carParams=cp), params=NS(put_bool=lambda *a: None))
  stack = [object()]
  root = stack[0]
  monkeypatch.setattr(fp, "ui_state", ui)
  monkeypatch.setattr(fp, "gui_app", NS(widget_in_stack=lambda p: p in stack,
                                       pop_widgets_to=lambda *a, **k: stack.__setitem__(slice(1, None), []),
                                       push_widget=stack.append))
  monkeypatch.setattr(fp, "alert_dialog", lambda text: NS(text=text))
  prompt = fp.FingerprintPrompt(root)
  def show(title, choices):
    page = NS(title=title, choices=dict(choices))
    stack.append(page)
    return page
  monkeypatch.setattr(prompt, "_show", show)
  return prompt, ui, stack


def test_question_no_stock_continues(prompt):
  p, ui, stack = prompt
  assert p.tick()
  assert stack[-1].title == "Are you on a Tesla?"
  stack[-1].choices["No"]()
  assert "Sorry" in stack[-1].text
  stack.pop()
  assert not p.tick()
  assert ui.sm["carParams"].brand == "mock"
  ui.ignition = ui.started = False
  p.tick()
  assert not p.asked


def test_yes_picker_review(prompt):
  p, ui, stack = prompt
  p.tick()
  stack[-1].choices["Yes"]()
  assert list(stack[-1].choices)[0].startswith("2026")
  assert not any("Model X" in title for title in stack[-1].choices)
  next(iter(stack[-1].choices.values()))()
  assert list(stack[-1].choices) == ["This is my car"]


def test_route_end_cancels_and_no_reprompt(prompt):
  p, ui, stack = prompt
  p.tick()
  ui.started = False
  assert not p.tick() and len(stack) == 1
  ui.started = True
  assert not p.tick()


def test_known_car_and_stale_cp(prompt):
  p, ui, stack = prompt
  ui.sm.recv_frame = {"carParams": 5}
  assert not p.tick()
  ui.sm.recv_frame = {"carParams": 20}
  ui.sm["carParams"] = car.CarParams.new_message(brand="toyota").as_reader()
  assert not p.tick()


def test_save_and_restart(prompt, monkeypatch):
  p, ui, stack = prompt
  p.tick()
  saved = []
  monkeypatch.setattr(fp, "save", lambda platform, fw: saved.append(platform))
  monkeypatch.setattr(fp, "ConfirmDialog", lambda text, label, callback: NS(text=text, callback=callback))
  p._save("TESLA_MODEL_3", "Model 3")
  assert saved == ["TESLA_MODEL_3"]
  assert "Please wait in Park until the device restarts and goes onroad so your Tesla Model 3 stays happy." in stack[-1].text
  assert "sharing is coming" in stack[-1].text
  reboot = []
  ui.params.put_bool = lambda *a: reboot.append(a)
  stack[-1].callback(fp.DialogResult.CANCEL)
  ui.started = False
  p._save("TESLA_MODEL_3", "Model 3")
  assert not reboot and len(saved) == 1
  ui.started = True
  stack[-1].callback(fp.DialogResult.CONFIRM)
  assert reboot == [("DoReboot", True)]
