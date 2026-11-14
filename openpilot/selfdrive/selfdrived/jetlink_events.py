"""
Jetlink's onroad events: a big model that joins mid-drive. Ported from zoompilot develop 632b0b0
(sunnypilot/selfdrive/selfdrived/accelerator_events.py:32-70) onto Highland's native events.
Nothing here disengages. With Jetlink off at start, swap_events() is None and update() is a no-op.
"""
from openpilot.cereal import log
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive import jetlink_adapter

EventName = log.OnroadEvent.EventName


class JetlinkEvents:
  # optional: the link owner exiting costs the big model, never engagement
  OPTIONAL_PROCESSES = frozenset({jetlink_adapter.OWNER})

  def __init__(self):
    # jetlink's tracker, behind the hooks' net; None with the link off or without jetlink
    self.swap = jetlink_adapter.swap_events(DT_CTRL)

  @property
  def settling(self) -> bool:
    """Within a second of the big model swapping in or handing back."""
    return self.swap is not None and self.swap.settling

  def update(self, sm, in_control: bool, events) -> None:
    """in_control: selfdrived's enabled, what the swap gate waits on."""
    if self.swap is None:
      return
    fresh = sm.seen['modelV2'] and sm.alive['modelV2'] and sm.valid['modelV2']
    big = sm.alive['modelV2'] and sm.valid['modelV2'] and sm['modelV2'].big
    flags = self.swap.update(fresh, big, in_control)
    if flags.offer:
      events.add(EventName.jetlinkBigModelAvailable)
    if flags.link_lost:
      events.add(EventName.jetlinkBigModelLost)
    if flags.no_entry:
      # upstream's no-entry for a big model that is not ready to drive
      events.add(EventName.bigModelLoading)
    if flags.chime:
      events.add(EventName.jetlinkBigModelActive)
