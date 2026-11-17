# accelerator param names and paths, stdlib only so any process can import it
CHESTNUT_PICK = 'ChestnutModelPick'
CHESTNUT_FAILED = 'ChestnutModelFailed'  # a pick that would not compile or load

# the last accelerator seen, kept across boots (hardwared's AccelDetect writes it)
DEVICE_KEY = 'AcceleratorDevice'
DEVICES = ('none', 'chestnut', 'jetlink-usb', 'jetlink-ios')


def known(device) -> str:
  return device if device in DEVICES else 'none'


def mode_of(device) -> str:
  # 'jetlink-usb' -> 'jetlink'; unset reads as none
  return (device or 'none').split('-')[0]
