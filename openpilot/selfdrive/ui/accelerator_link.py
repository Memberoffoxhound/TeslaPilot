"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
Ported to Highland from zoompilot develop
(selfdrive/ui/sunnypilot/accelerator_link.py). Layout and names match so
zoompilot Jetlink UI commits merge cleanly; import path is Highland's
openpilot.selfdrive.jetlink_adapter.

Models panel helpers. Everything reads ui_state.jetlink; the link itself is
switched by hardwared's accel_detect.
"""
from __future__ import annotations

from openpilot.selfdrive.ui.ui_state import ui_state

IOS_KEY = "JetlinkIos"  # iPhone is manual; a Jetson over USB is auto-detected (accel_detect.py)


def ios_toggle_meaningful() -> bool:
  return not ui_state.chestnut_present


def link_status(jetlink=None) -> str:
  if jetlink is None:
    jetlink = ui_state.jetlink
  port = getattr(jetlink, 'port_state', None)
  if port == "connected":
    return f"Jetlink connected: {jetlink.transport}."
  return {"empty": "Nothing on the USB port.", "device": "A device is on the USB port."}.get(port, "")


def big_model_progress(jetlink=None) -> tuple[str, float, str] | None:
  if jetlink is None:
    jetlink = ui_state.jetlink
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
               small_name: str = "built-in", big_name: str = "default") -> tuple[str, str, str]:
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
    provisioning = big_model_progress(jetlink)
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
