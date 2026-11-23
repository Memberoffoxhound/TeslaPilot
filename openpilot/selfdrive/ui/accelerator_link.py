# Ported from zoompilot (421d151cf), see LICENSE.zoompilot.
# Layout and names match zoompilot selfdrive/ui/sunnypilot/accelerator_link.py;
# import path is openpilot.selfdrive.jetlink_adapter.
# Models panel helpers: everything reads ui_state.jetlink; the link itself is
# switched by the JetlinkLink setting.
from __future__ import annotations

from openpilot.selfdrive import jetlink_adapter
from openpilot.selfdrive.jetlink_adapter import KEYS, MODES
from openpilot.selfdrive.ui.ui_state import ui_state

LINK_MODE_TITLES = {"off": "Off", "usb": "USB", "ios": "iOS"}


def link_mode() -> str:
  # the JetlinkLink setting as stored, one of MODES: shown even when jetlink cannot run,
  # so a link that will not start can be turned off
  index = ui_state.params.get(KEYS.link, return_default=True)
  return MODES[index] if isinstance(index, int) and 0 <= index < len(MODES) else "off"


def link_toggle_meaningful() -> bool:
  # offered wherever jetlink is checked out, except beside a chestnut, which runs the big
  # model itself; and always while the setting is on. Never gated on presence: with the
  # link off there is no gadget for a Jetson to enumerate
  if link_mode() != "off":
    return True
  return not ui_state.chestnut_present and ui_state.jetlink is not None


def link_status() -> str:
  # one line on what is on the USB-C port now: jetlink knows a Jetson or a phone, below
  # that only the CC pin says a cable with a host is plugged in. Empty where unknown
  jetlink = ui_state.jetlink
  port = getattr(jetlink, 'port_state', None) if jetlink is not None else None
  if port == "connected":
    return f"Jetlink connected: {jetlink.transport}."
  return {"empty": "Nothing on the USB port.", "device": "A device is on the USB port."}.get(port, "")


def big_model_note(ref: str) -> str | None:
  # what jetlink says of one big model for the list: built on the Jetson, or downloaded
  # to the comma. None with a chestnut fitted
  if ui_state.chestnut_present or ui_state.jetlink is None:
    return None
  return {'ready': "ready on Jetson", 'downloaded': "downloaded"}.get(jetlink_adapter.model_state(ref))


def big_model_progress(jetlink=None, progress=None) -> tuple[str, float, str] | None:
  if jetlink is None:
    jetlink = ui_state.jetlink
  if progress is None:
    progress = getattr(jetlink, 'progress', None)
  if not isinstance(progress, dict) or not progress:
    return None
  stage = str(progress.get('stage', ''))
  if stage in ('', 'ready'):
    return None
  msg = str(progress.get('msg', ''))
  if drops := progress.get('drops'):
    hint = "check cable or app" if getattr(jetlink, 'mode', '') == 'ios' else "check cable"
    msg = f"{msg}, {hint} ({drops} drops)"
  try:
    frac = float(progress.get('frac', 0.0))
  except (TypeError, ValueError):
    frac = 0.0
  return stage, frac, msg


def standin_model(jetlink=None, chestnut_present: bool | None = None) -> str | None:
  if jetlink is None:
    jetlink = ui_state.jetlink
  if chestnut_present is None:
    chestnut_present = ui_state.chestnut_present
  return None if chestnut_present else getattr(jetlink, 'standin', None)


def big_model_state(chestnut_state: str) -> str | None:
  return {'uncompiled': 'failed', 'failed': 'failed', 'loading': 'loading', 'waiting': 'ready'}.get(chestnut_state)


def model_info(jetlink=None, chestnut_state: str | None = None, chestnut_present: bool | None = None,
               small_name: str = "built-in", big_name: str = "default", progress=None) -> tuple[str, str, str]:
  """(active model, info header, info text) for the models panel."""
  try:
    if jetlink is None:
      jetlink = ui_state.jetlink
    if chestnut_state is None:
      chestnut_state = ui_state.chestnut_state.value
    if chestnut_present is None:
      chestnut_present = ui_state.chestnut_present
    carry = None
    if not chestnut_present and chestnut_state == 'active' and jetlink is not None:
      carry = jetlink.active_model
    active_text = (carry or small_name).lower()
    provisioning = big_model_progress(jetlink, progress)
    if provisioning is not None:
      stage, frac, msg = provisioning
      if stage == 'failed':
        return active_text, "big model", msg or "unavailable"
      detail = msg or stage
      return active_text, "big model", f"{detail} {frac * 100:.0f}%" if frac > 0 else detail
    if standin := standin_model(jetlink, chestnut_present):
      return active_text, "big model", f"{standin.lower()} for now"
    state = big_model_state(chestnut_state)
    if state == 'failed':
      return active_text, "big model", "unavailable"
    if state == 'loading':
      return active_text, "big model", "getting ready"
    return active_text, "big model", big_name.lower()
  except Exception:
    return small_name.lower(), "big model", big_name.lower()
