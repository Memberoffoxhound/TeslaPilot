import numpy as np
import raylib_nb as rl
from openpilot.cereal import log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.controls.radard import RADAR_TO_CAMERA
from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.selfdrive.ui.layouts.settings.common import custom_onroad_ui, tesla_theme, THEME_TESLA_RGB, THEME_OPENPILOT_RGB
from openpilot.selfdrive.ui.mici.onroad import blend_colors
from openpilot.selfdrive.ui.mici.onroad.status import lerp_color, status_fade, steer_fade
from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer as BaseModelRenderer, CLIP_MARGIN, MAX_DRAW_DISTANCE, STOCK_PATH_GRADIENT
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.polygon import Gradient, draw_polygon

LEAD_BAR_LENGTH = 12.0  # px
LEAD_BAR_WIDTH = 1.8  # m

STOCK_LANE_GREEN = rl.Color(*THEME_OPENPILOT_RGB, 255)
TESLA_LANE_BLUE = rl.Color(*THEME_TESLA_RGB, 255)

SWAP_RC = 0.15  # lane/path color swap, ~0.5 s each way
SWAP_BRIGHT = 1.5  # steering-only path alpha
SWAP_LANE = rl.Color(242, 242, 242, 255)  # steering-only path border: the cruising near-white
BORDER_PX = 3.0  # steering-only path border width

LANE_LINE_COLORS = {
  UIStatus.DISENGAGED: rl.Color(200, 200, 200, 255),
  UIStatus.OVERRIDE: rl.Color(255, 255, 255, 255),
}


def _faded(gradient: Gradient, alpha: float) -> Gradient:
  if alpha >= 1:
    return gradient
  return Gradient(gradient.start, gradient.end, [rl.Color(c.r, c.g, c.b, round(c.a * alpha)) for c in gradient.colors], gradient.stops)


def _tinted(gradient: Gradient, color: rl.Color, f: float) -> Gradient:
  # rgb toward color and alpha up, both by f
  if f < 1e-3:
    return gradient
  k = 1 + (SWAP_BRIGHT - 1) * f
  tint = [lerp_color(c, rl.Color(color.r, color.g, color.b, c.a), f) for c in gradient.colors]
  return Gradient(gradient.start, gradient.end, [rl.Color(t.r, t.g, t.b, min(255, round(t.a * k))) for t in tint], gradient.stops)


def _resample(line: np.ndarray, n: int) -> np.ndarray:
  t, u = np.linspace(0, 1, len(line)), np.linspace(0, 1, n)
  return np.column_stack((np.interp(u, t, line[:, 0]), np.interp(u, t, line[:, 1])))


def _morph(lane: np.ndarray, edge: np.ndarray, w: float) -> np.ndarray:
  # lane polygon slides onto a path edge (both near to far) and thins to BORDER_PX
  m = len(lane) // 2
  n = max(m, len(edge))
  a, b = _resample(lane[:m], n), _resample(lane[m:][::-1], n)
  center = (a + b) / 2 + (_resample(edge, n) - (a + b) / 2) * w
  side = np.where(a[:, :1] <= b[:, :1], -1.0, 1.0)
  half = (a - b) / 2 * (1 - w) + np.column_stack((side[:, 0] * BORDER_PX / 2, np.zeros(n))) * w
  return np.vstack((center + half, (center - half)[::-1])).astype(np.float32)


class LeadVehicle:
  def __init__(self):
    self.bar = np.empty((0, 2), dtype=np.float32)
    self.d_filter = FirstOrderFilter(0.0, 0.2, 1 / gui_app.target_fps, initialized=False)
    self.y_filter = FirstOrderFilter(0.0, 0.2, 1 / gui_app.target_fps, initialized=False)
    self.fade_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)


class ModelRenderer(BaseModelRenderer):
  LANE_LINE_WIDTHS = (0.12, 0.16, 0.16, 0.16)
  ROAD_EDGE_WIDTH = 0.16

  def __init__(self):
    super().__init__()
    self._ll_engaged = TESLA_LANE_BLUE
    self._lead_bars = [LeadVehicle(), LeadVehicle()]
    self._torque_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)
    self._visible = 0.0
    self._swap = FirstOrderFilter(0.0, SWAP_RC, 1 / gui_app.target_fps)

  def _draw_offset(self) -> np.ndarray:
    # car space transform maps to rect-origin space
    return np.array([self._rect.x, self._rect.y], dtype=np.float32)

  def _render(self, rect: rl.Rectangle):
    sm = ui_state.sm

    self._torque_filter.update(-ui_state.sm['carOutput'].actuatorsOutput.torque)

    # Check if data is up-to-date
    if (sm.recv_frame["extrinsicsCalibration"] < ui_state.started_frame or
        sm.recv_frame["modelV2"] < ui_state.started_frame):
      return

    # Set up clipping region
    self._clip_region = rl.Rectangle(
      rect.x - CLIP_MARGIN, rect.y - CLIP_MARGIN, rect.width + 2 * CLIP_MARGIN, rect.height + 2 * CLIP_MARGIN
    )

    # Update state
    extrinsics_calibration = sm['extrinsicsCalibration']
    self._path_offset_z = extrinsics_calibration.height[0] if extrinsics_calibration.height else HEIGHT_INIT[0]

    if sm.updated['carParams']:
      self._longitudinal_control = sm['carParams'].openpilotLongitudinalControl

    model = sm['modelV2']
    radar_state = sm['radarState'] if sm.valid['radarState'] else None
    lead_one = radar_state.leadOne if radar_state else None
    render_lead_indicator = self._longitudinal_control and radar_state is not None

    # Update model data when needed
    model_updated = sm.updated['modelV2']
    if model_updated or sm.updated['radarState'] or self._transform_dirty:
      if model_updated:
        self._update_raw_points(model)

      path_x_array = self._path.raw_points[:, 0]
      if path_x_array.size == 0:
        return

      self._update_model(lead_one, path_x_array)
      self._transform_dirty = False

    # lane lines and path fade out while disengaged
    self._visible = 1 - steer_fade.weight(UIStatus.DISENGAGED)
    # TITS steering alone: lane lines and path trade colors
    # TITS override keeps it, so override flapping does not pulse the path
    self._swap.update(float(ui_state.steer_status != UIStatus.DISENGAGED and ui_state.status == UIStatus.DISENGAGED))
    if self._visible > 1e-2:
      self._ll_engaged = TESLA_LANE_BLUE if custom_onroad_ui() and tesla_theme() else STOCK_LANE_GREEN
      self._draw_lane_lines()
      self._draw_path()

    if render_lead_indicator:
      self._update_lead_bars(sm)
      self._draw_lead_indicator()
    else:
      self._lead_bars = [LeadVehicle(), LeadVehicle()]

  def _update_lead_bars(self, sm):
    plan = sm['longitudinalPlan']
    if plan.longitudinalPlanSource == log.LongitudinalPlan.LongitudinalPlanSource.e2e and len(sm['modelV2'].leadsV3) > 1:
      leads = [(lead.prob > 0.5, lead.x[0], -lead.y[0]) for lead in list(sm['modelV2'].leadsV3)[:2]]
    else:
      radar = sm['radarState']
      leads = [(lead.present, lead.dRel + RADAR_TO_CAMERA, lead.yRel) for lead in (radar.leadOne, radar.leadTwo)]

    # both leads can be the same vehicle
    if leads[0][0] and abs(leads[1][1] - leads[0][1]) < 3.0:
      leads[1] = (False, 0.0, 0.0)

    ss, cs = sm['selfdriveState'], sm['carState']
    # braking disengages without making openpilot unavailable
    available = ss.enabled or ss.engageable or cs.brakePressed
    lane = self._path.raw_points
    opacity = 0.8 - 0.4 * status_fade.weight(UIStatus.DISENGAGED)
    for lead, (present, d_rel, y_rel) in zip(self._lead_bars, leads, strict=True):
      visible = available and present and d_rel < MAX_DRAW_DISTANCE and len(lane) > 0
      # snap to a new vehicle instead of sliding over
      if not visible or abs(y_rel - lead.y_filter.x) > 3.0:
        lead.d_filter.initialized = lead.y_filter.initialized = False
      lead.fade_filter.update(opacity if visible else 0.0)
      if visible:
        lead.bar = self._get_lead_bar(lane, lead.d_filter.update(d_rel), lead.y_filter.update(y_rel))

  def _get_lead_bar(self, lane, d_rel, y_rel):
    # bar on the road behind the lead, following the lane
    x = np.array([d_rel, d_rel - min(6.0, 0.25 * d_rel)])
    y = np.interp(x, lane[:, 0], lane[:, 1]) - np.interp(d_rel, lane[:, 0], lane[:, 1]) - y_rel
    z = np.interp(x, self._path.raw_points[:, 0], self._path.raw_points[:, 2]) + self._path_offset_z
    corners = np.vstack((np.column_stack((x, y + LEAD_BAR_WIDTH / 2, z)), np.column_stack((x, y - LEAD_BAR_WIDTH / 2, z))[::-1]))
    pts = self._car_space_transform @ corners.T
    bar = (pts[:2] / pts[2]).T

    far, near = bar[[0, 3]], bar[[1, 2]]
    length = np.linalg.norm(near.mean(axis=0) - far.mean(axis=0))
    bar[[1, 2]] = far + (near - far) * np.clip(length, 3.0, LEAD_BAR_LENGTH) / length
    return bar.astype(np.float32)

  def _get_ll_color(self, prob: float, adjacent: bool, left: bool):
    alpha = np.clip(prob, 0.0, 0.7) * self._visible
    if adjacent:
      engaged = lerp_color(self._ll_engaged, SWAP_LANE, self._swap.x) if self._swap.x >= 1e-3 else self._ll_engaged
      _base_color = steer_fade.color({**LANE_LINE_COLORS, UIStatus.ENGAGED: engaged})
      color = rl.Color(_base_color.r, _base_color.g, _base_color.b, int(alpha * 255))

      # turn adjacent lls orange if torque is high
      torque = self._torque_filter.x
      high_torque = abs(torque) > 0.6
      if high_torque and (left == (torque > 0)):
        color = blend_colors(
          color,
          rl.Color(255, 115, 0, int(alpha * 255)),  # orange
          np.interp(abs(torque), [0.6, 0.8], [0.0, 1.0])
        )
    else:
      color = rl.Color(255, 255, 255, int(alpha * 255))

    return color

  def _draw_lane_lines(self):
    """Draw lane lines and road edges. Two closest lines should be green (lane line or road edges)."""
    offset = self._draw_offset()
    w = self._swap.x
    path, h = self._path.projected_points + offset, len(self._path.projected_points) // 2
    edges = sorted((path[:h], path[h:][::-1]), key=lambda e: float(e[:, 0].mean())) if h > 1 else None

    for i, lane_line in enumerate(self._lane_lines):
      if lane_line.projected_points.size == 0:
        continue

      color = self._get_ll_color(float(self._lane_line_probs[i]), i in (1, 2), i in (0, 1))
      pts = lane_line.projected_points + offset
      # steering only: the two closest lines slide onto the path edges and become its border, the others fade
      if w >= 1e-3:
        if i in (1, 2) and edges is not None and len(pts) >= 4:
          pts = _morph(pts, edges[i - 1], w)
          color.a = int(color.a + (255 * 0.7 * self._visible - color.a) * w)
        else:
          color.a = int(color.a * (1 - w))
      draw_polygon(self._rect, pts, color)

    for i, road_edge in enumerate(self._road_edges):
      if road_edge.projected_points.size == 0:
        continue

      # if closest lane lines are not confident, make road edges green
      color = self._get_ll_color(float(1.0 - self._road_edge_stds[i]), float(self._lane_line_probs[i + 1]) < 0.25, i == 0)
      draw_polygon(self._rect, road_edge.projected_points + offset, color)

  def _draw_path(self):
    if not self._path.projected_points.size:
      return

    path_pts = self._path.projected_points + self._draw_offset()
    swap = self._swap.x

    if not self._longitudinal_control:
      draw_polygon(self._rect, path_pts, gradient=_faded(_tinted(STOCK_PATH_GRADIENT, self._ll_engaged, swap), self._visible))
    elif len(self._path_gradient.colors) > 1:
      draw_polygon(self._rect, path_pts, gradient=_faded(_tinted(self._path_gradient, self._ll_engaged, swap), self._visible))
    else:
      white = rl.Color(255, 255, 255, round(30 * self._visible * (1 + (SWAP_BRIGHT - 1) * swap)))
      draw_polygon(self._rect, path_pts, lerp_color(white, rl.Color(self._ll_engaged.r, self._ll_engaged.g, self._ll_engaged.b, white.a), swap))

  def _draw_lead_indicator(self):
    offset = self._draw_offset()
    for lead in self._lead_bars:
      draw_polygon(self._rect, lead.bar + offset, rl.Color(255, 255, 255, int(255 * lead.fade_filter.x)))
