from openpilot.conftest import FakeParams
from openpilot.selfdrive.ui.mici.layouts import accel_card as ac


def test_card_pages():
  line = "You can see progress and change your model in Settings, Models."
  assert ac.card('chestnut') == ("Chestnut connected", ["Settings have been updated to manage your chestnut.",
                                                        "The comma big model is ready.", line])
  assert ac.card('chestnut', False)[1][1] == "The comma big model downloads the first time. The chestnut icon fills as it downloads."
  assert ac.card('jetlink') == ("Jetlink connected", ["Settings have been updated to manage Jetlink.", line])
  assert ac.card('none') is None
  assert not any('\u2014' in p for m in ('chestnut', 'jetlink') for p in ac.card(m)[1])


def test_due_once_per_device():
  p = FakeParams(AcceleratorDevice='jetlink-usb', AcceleratorAck='none')
  assert ac.due(p) == 'jetlink'
  p['AcceleratorAck'] = 'jetlink'
  assert ac.due(p) is None
  p['AcceleratorDevice'] = 'jetlink-ios'
  assert ac.due(p) is None  # same mode, new transport: no card
  p['AcceleratorDevice'] = 'chestnut'
  assert ac.due(p) == 'chestnut'


def test_unplug_acks_quietly():
  p = FakeParams(AcceleratorDevice='none', AcceleratorAck='chestnut')
  assert ac.due(p) is None and p['AcceleratorAck'] == 'none'
  p['AcceleratorDevice'] = 'chestnut'
  assert ac.due(p) == 'chestnut'  # plugged back in: shown again

