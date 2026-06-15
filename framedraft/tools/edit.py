import math
from PySide6.QtCore import Qt, QObject, Signal, QPointF
from PySide6.QtGui import QPen, QColor
from PySide6.QtWidgets import QApplication

from ..canvas.items import CurveItem, NodeDot, HandleDot, make_handle_line_pen
from ..canvas.snapping import px_dist
from ..document import Curve, SplineNode, ControlPoint


class EditTool(QObject):
    """Manages NodeDot and HandleDot items for the currently selected curve(s)."""

    about_to_modify        = Signal()   # emitted just before any node/handle drag begins
    node_selection_changed = Signal(bool)  # True = a node dot became selected; False = deselected

    _EP_SNAP_PX = 12   # screen-pixel radius for endpoint drag-snap
    _EP_IND_R   = 7    # screen-pixel radius of the endpoint snap indicator ring

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self._scene        = scene
        self._dots:        list[NodeDot]   = []
        self._handles:     list[HandleDot] = []
        self._lines:       list            = []
        self._line_data:   list[dict]      = []
        self._smooth_mode  = True
        self._selected_dot: NodeDot | None = None
        # Endpoint drag-snap context (set via set_endpoint_snap_context)
        self._ep_curves:      list | None  = None
        self._ep_view                      = None
        self._ep_enabled_fn                = None   # () -> bool
        self._ep_indicator                 = None   # scene indicator item
        scene.selectionChanged.connect(self._on_selection)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clear(self):
        self._remove_all()

    def set_smooth_mode(self, smooth: bool):
        self._smooth_mode = smooth
        for hdot in self._handles:
            hdot.set_smooth(smooth)

    def refresh_theme(self):
        """Re-apply current theme colours to all active dots and connector lines."""
        pen = make_handle_line_pen()
        for line in self._lines:
            line.setPen(pen)
        for dot in self._dots:
            dot.refresh_theme()
        for hdot in self._handles:
            hdot.refresh_theme()

    def set_endpoint_snap_context(self, curves: list, view, snap_enabled_fn=None):
        """Provide the doc-curves list and view needed for drag-snap to endpoints."""
        self._ep_curves     = curves
        self._ep_view       = view
        self._ep_enabled_fn = snap_enabled_fn or (lambda: True)

    @property
    def selected_dot(self) -> "NodeDot | None":
        return self._selected_dot

    def has_selected_node(self) -> bool:
        return self._selected_dot is not None

    def selected_node_info(self) -> tuple:
        """Return (Curve, node_index) for the selected node, or (None, -1)."""
        if self._selected_dot is None:
            return None, -1
        return self._selected_dot._curve, self._selected_dot.node_index

    def delete_selected_node(self) -> Curve | None:
        """Remove the selected NodeDot's node from its curve.

        Returns the modified Curve so the caller can push an undo snapshot
        and refresh the scene.  Returns None if nothing was selected or the
        curve would be left with fewer than 2 nodes.
        """
        if self._selected_dot is None:
            return None
        curve = self._selected_dot._curve
        idx   = self._selected_dot.node_index
        if len(curve.nodes) <= 2:
            return None   # caller should delete the whole curve instead
        curve.nodes.pop(idx)
        self._selected_dot = None
        self._remove_all()
        return curve

    def insert_node_at(self, curve: Curve, scene_pos: QPointF) -> bool:
        """Insert a new node on *curve* at the point nearest to *scene_pos*.

        Returns True if a node was inserted (caller should undo-snapshot +
        refresh the scene before calling this, or snapshot first and call this
        after — follow the existing pattern: snapshot BEFORE mutation).
        """
        if curve.kind in ("circle", "arc"):
            return False   # circles/arcs don't support node insertion
        mx, my = scene_pos.x(), scene_pos.y()

        if curve.kind == "line":
            return self._insert_line_node(curve, mx, my)
        else:
            return self._insert_spline_node(curve, mx, my)

    # ------------------------------------------------------------------
    # Node-insert helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    def _insert_line_node(self, curve: Curve, mx: float, my: float) -> bool:
        nodes  = curve.nodes
        n      = len(nodes)
        pairs  = list(range(n - 1))
        if curve.closed:
            pairs.append(n - 1)   # segment from last → first

        best_d   = float("inf")
        best_seg = -1
        best_t   = 0.5

        for i in pairs:
            a = nodes[i]
            b = nodes[(i + 1) % n]
            dx, dy = b.x - a.x, b.y - a.y
            seg_len2 = dx * dx + dy * dy
            if seg_len2 < 1e-12:
                continue
            t = ((mx - a.x) * dx + (my - a.y) * dy) / seg_len2
            t = max(0.0, min(1.0, t))
            px = a.x + t * dx
            py = a.y + t * dy
            d  = math.hypot(mx - px, my - py)
            if d < best_d:
                best_d, best_seg, best_t = d, i, t

        if best_seg < 0:
            return False

        ins_x = nodes[best_seg].x + best_t * (nodes[(best_seg + 1) % n].x - nodes[best_seg].x)
        ins_y = nodes[best_seg].y + best_t * (nodes[(best_seg + 1) % n].y - nodes[best_seg].y)
        curve.nodes.insert(best_seg + 1, SplineNode(x=ins_x, y=ins_y))
        return True

    def _insert_spline_node(self, curve: Curve, mx: float, my: float) -> bool:
        nodes  = curve.nodes
        n      = len(nodes)
        pairs  = list(range(n - 1))
        if curve.closed:
            pairs.append(n - 1)

        best_d   = float("inf")
        best_seg = -1
        best_t   = 0.5

        SAMPLES = 200
        for i in pairs:
            a  = nodes[i]
            b  = nodes[(i + 1) % n]
            p0 = (a.x, a.y)
            p1 = (a.cp_out.x, a.cp_out.y) if a.cp_out else p0
            p2 = (b.cp_in.x,  b.cp_in.y)  if b.cp_in  else (b.x, b.y)
            p3 = (b.x, b.y)
            for s in range(SAMPLES + 1):
                t  = s / SAMPLES
                bx = self._cubic(p0[0], p1[0], p2[0], p3[0], t)
                by = self._cubic(p0[1], p1[1], p2[1], p3[1], t)
                d  = math.hypot(mx - bx, my - by)
                if d < best_d:
                    best_d, best_seg, best_t = d, i, t

        if best_seg < 0:
            return False

        a  = nodes[best_seg]
        b  = nodes[(best_seg + 1) % n]
        p0 = (a.x, a.y)
        p1 = (a.cp_out.x, a.cp_out.y) if a.cp_out else p0
        p2 = (b.cp_in.x,  b.cp_in.y)  if b.cp_in  else (b.x, b.y)
        p3 = (b.x, b.y)

        # de Casteljau split at best_t
        t  = best_t
        L  = self._lerp
        ax = L(p0[0], p1[0], t);  ay = L(p0[1], p1[1], t)
        bx = L(p1[0], p2[0], t);  by = L(p1[1], p2[1], t)
        cx = L(p2[0], p3[0], t);  cy = L(p2[1], p3[1], t)
        dx = L(ax, bx, t);        dy = L(ay, by, t)
        ex = L(bx, cx, t);        ey = L(by, cy, t)
        fx = L(dx, ex, t);        fy = L(dy, ey, t)   # point on curve

        # Update left-side endpoint handles
        a.cp_out = ControlPoint(ax, ay)
        # Update right-side endpoint handles
        b.cp_in  = ControlPoint(cx, cy)

        new_node = SplineNode(
            x=fx, y=fy,
            cp_in  = ControlPoint(dx, dy),
            cp_out = ControlPoint(ex, ey),
        )
        insert_at = best_seg + 1
        curve.nodes.insert(insert_at, new_node)
        return True

    @staticmethod
    def _cubic(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
        u = 1 - t
        return u*u*u*p0 + 3*u*u*t*p1 + 3*u*t*t*p2 + t*t*t*p3

    # ------------------------------------------------------------------
    # Endpoint drag-snap
    # ------------------------------------------------------------------

    def _make_ep_snap_fn(self, dragged_node):
        """Return a per-NodeDot snap callback that captures the specific node being dragged."""
        def ep_snap(pos: QPointF) -> QPointF:
            # Respect global snap toggle and Ctrl-key suspend
            if (self._ep_view is None
                    or not self._ep_enabled_fn()
                    or QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
                self._hide_ep_indicator()
                return pos

            best_x, best_y = None, None
            best_d = float("inf")

            # Snap to open-curve endpoints (skip hidden layers)
            is_visible = getattr(self._scene, "is_layer_visible", None)
            if self._ep_curves is not None:
                for c in self._ep_curves:
                    if not c.nodes or c.closed:
                        continue
                    if is_visible is not None and not is_visible(c.layer):
                        continue
                    for ep in (c.nodes[0], c.nodes[-1]):
                        if ep is dragged_node:
                            continue
                        d = px_dist(self._ep_view, pos, QPointF(ep.x, ep.y))
                        if d < self._EP_SNAP_PX and d < best_d:
                            best_d, best_x, best_y = d, ep.x, ep.y

            # Snap to mirror axis — allows re-snapping a moved endpoint back to the axis
            mirror = getattr(self._scene, 'mirror', None)
            if mirror is not None and getattr(mirror, 'enabled', False):
                horizontal = getattr(mirror, '_horizontal', False)
                if horizontal:
                    target = QPointF(pos.x(), mirror.x)
                else:
                    target = QPointF(mirror.x, pos.y())
                d = px_dist(self._ep_view, pos, target)
                if d < self._EP_SNAP_PX and d < best_d:
                    best_d, best_x, best_y = d, target.x(), target.y()

            if best_x is not None:
                self._show_ep_indicator(QPointF(best_x, best_y))
                return QPointF(best_x, best_y)

            self._hide_ep_indicator()
            return pos

        return ep_snap

    def _show_ep_indicator(self, pos: QPointF):
        R   = self._EP_IND_R
        pen = QPen(QColor("#e67e22"), 2.5)
        pen.setCosmetic(True)
        if self._ep_indicator is None:
            item = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, pen)
            item.setFlag(item.GraphicsItemFlag.ItemIgnoresTransformations, True)
            item.setZValue(210)
            self._ep_indicator = item
        else:
            self._ep_indicator.setPen(pen)
        self._ep_indicator.setPos(pos)

    def _hide_ep_indicator(self):
        if self._ep_indicator is not None:
            self._scene.removeItem(self._ep_indicator)
            self._ep_indicator = None

    # ------------------------------------------------------------------
    # Selection response
    # ------------------------------------------------------------------

    def _on_selection(self):
        had_selected = self._selected_dot is not None
        self._remove_all()   # clears _selected_dot
        # Node/handle editing dots only appear for a SINGLE selected curve.
        # When several curves are selected (e.g. the final mirror, or any
        # band-select), showing every curve's nodes lets an accidental drag
        # grab a node and endpoint-snap it — geometry "snaps around" even
        # though the user only meant to move the group. A multi-selection
        # therefore stays rigid (like a group), independent of the snap toggle.
        curve_items = [it for it in self._scene.selectedItems()
                       if isinstance(it, CurveItem)]
        if len(curve_items) == 1:
            self._add_curve_items(curve_items[0])
        if had_selected:
            self.node_selection_changed.emit(False)

    def _on_node_clicked(self, dot: NodeDot):
        """Called when a NodeDot is clicked; toggles selection on that dot."""
        if self._selected_dot is dot:
            dot.set_node_selected(False)
            self._selected_dot = None
            self.node_selection_changed.emit(False)
            return
        if self._selected_dot is not None:
            self._selected_dot.set_node_selected(False)
        self._selected_dot = dot
        dot.set_node_selected(True)
        self.node_selection_changed.emit(True)

    def _add_curve_items(self, curve_item: CurveItem):
        curve = curve_item.curve

        # Grouped curves move as a rigid unit — no node/handle editing.
        # (This is what stops imported hinge groups from being distorted by
        # accidental node drags + endpoint snap onto frame geometry.)
        if curve.group_id:
            return

        node_dots: dict[int, NodeDot] = {}
        for i in range(len(curve.nodes)):
            dragged_node = curve.nodes[i]
            dot = NodeDot(
                curve, i, self._node_moved,
                on_drag_start = self.about_to_modify.emit,
                on_clicked    = self._on_node_clicked,
                on_snap       = self._make_ep_snap_fn(dragged_node),
                on_drag_end   = self._hide_ep_indicator,
            )
            self._scene.addItem(dot)
            self._dots.append(dot)
            node_dots[i] = dot

        if curve.kind != "spline":
            return

        for i, node in enumerate(curve.nodes):
            cp_out_dot: HandleDot | None = None
            cp_in_dot:  HandleDot | None = None

            for which in ("cp_out", "cp_in"):
                cp = getattr(node, which)
                if cp is None:
                    continue

                hdot = HandleDot(curve, i, which, self._node_moved,
                                 on_drag_start=self.about_to_modify.emit)
                hdot.set_smooth(self._smooth_mode)
                self._scene.addItem(hdot)
                self._handles.append(hdot)

                line = self._scene.addLine(
                    node.x, node.y, cp.x, cp.y, make_handle_line_pen()
                )
                line.setZValue(18)
                line.setFlag(line.GraphicsItemFlag.ItemIsSelectable, False)
                self._lines.append(line)

                self._line_data.append({
                    "curve":      curve,
                    "node_index": i,
                    "node_dot":   node_dots[i],
                    "which":      which,
                    "handle_dot": hdot,
                    "line_item":  line,
                })

                if which == "cp_out":
                    cp_out_dot = hdot
                else:
                    cp_in_dot = hdot

            if cp_out_dot and cp_in_dot:
                cp_out_dot.set_sibling(cp_in_dot)
                cp_in_dot.set_sibling(cp_out_dot)

    # ------------------------------------------------------------------
    # Movement callback
    # ------------------------------------------------------------------

    def _node_moved(self, curve: Curve):
        self._scene.refresh_curve(curve)

        for entry in self._line_data:
            if entry["curve"] is not curve:
                continue
            node = curve.nodes[entry["node_index"]]
            cp   = getattr(node, entry["which"])
            if cp is not None:
                entry["handle_dot"].set_pos_silent(cp.x, cp.y)

        self._refresh_lines()

    def _refresh_lines(self):
        for entry in self._line_data:
            node = entry["curve"].nodes[entry["node_index"]]
            hp   = entry["handle_dot"].pos()
            entry["line_item"].setLine(node.x, node.y, hp.x(), hp.y())

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _remove_all(self):
        self._hide_ep_indicator()
        for item in self._dots + self._handles + self._lines:
            self._scene.removeItem(item)
        self._dots.clear()
        self._handles.clear()
        self._lines.clear()
        self._line_data.clear()
        self._selected_dot = None
