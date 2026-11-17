from openpilot.selfdrive.ui.mici.layouts import accel_card as ac


class FakeParams(dict):
  def get(self, key):
    return super().get(key)

  def put(self, key, value):
    self[key] = value


def test_card_copy():
  chestnut = "Settings have been updated to manage your chestnut. The comma big model is ready. You can change your model in Settings, Models."
  assert ac.card('chestnut') == ("Chestnut connected", chestnut)
  assert ac.card('chestnut', False)[1].endswith("The comma big model is downloading. You can change your model in Settings, Models.")
  jetlink = "Settings have been updated to manage Jetlink. You can change your model in Settings, Models."
  assert ac.card('jetlink') == ("Jetlink connected", jetlink)
  assert ac.card('none') is None


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
