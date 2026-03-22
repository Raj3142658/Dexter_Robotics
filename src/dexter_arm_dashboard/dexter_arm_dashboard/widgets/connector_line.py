import math
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QPainterPathStroker, QRegion


class _ConnectorHitLayer(QWidget):
    def __init__(self, owner, parent_widget):
        super().__init__(parent_widget)
        self._owner = owner
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Start with mouse events disabled - will enable only when unlocked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def enterEvent(self, event):
        self._owner.enterEvent(event)

    def leaveEvent(self, event):
        self._owner.leaveEvent(event)

    def mousePressEvent(self, event):
        self._owner._handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        self._owner._handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self._owner._handle_mouse_release(event)

    def mouseDoubleClickEvent(self, event):
        self._owner._handle_mouse_double_click(event)

    def wheelEvent(self, event):
        self._owner._handle_wheel_event(event)


class ConnectorLine(QWidget):
    """
    Draws a multi-point connector line with glowing effects.

    Coordinate system:
    - Points are stored normalized to the base canvas (0.0-1.0).
    - A view transform (scale + offset + base size) maps normalized points to pixels.
    """

    configChanged = pyqtSignal()

    def __init__(self, parent=None, points_normalized=None,
                 line_color="#00FFFF", glow_color="#00FFFF",
                 thickness=2.0, glow_radius=10.0, 
                 base_width=1280.0, base_height=720.0, name=None):
        super().__init__(parent)

        if points_normalized and len(points_normalized) >= 2:
            self.points_normalized = [
                [float(p[0]), float(p[1])] for p in points_normalized
            ]
        else:
            self.points_normalized = [[0.1, 0.1], [0.5, 0.5]]

        self.line_color = QColor(line_color)
        self.glow_color = QColor(glow_color)
        self.line_thickness = thickness
        self.glow_radius = glow_radius
        self.handle_radius = 15.0

        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # Parent transparency is controlled by lock state
        # Will be set transparent when locked, non-transparent when unlocked

        self._drag_index = None
        self._hover_index = None
        self._drag_whole_line = False
        self._drag_start_pos = None
        self._drag_start_points = None
        self._locked = True
        self._interaction_scale = 1.0
        self.name = name
        self._group_highlighted = False
        self._group_prev_opacity = None
        self._group_prev_glow_radius = None
        self._group_prev_glow_color = None

        # Initialize with proper base size instead of 1x1
        self._view_scale = 1.0
        self._view_offset_x = 0.0
        self._view_offset_y = 0.0
        self._base_width = base_width
        self._base_height = base_height

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(0.8)
        self.setGraphicsEffect(self.opacity_effect)

        hit_parent = parent if parent is not None else self
        self._hit_layer = _ConnectorHitLayer(self, hit_parent)
        self._sync_hit_layer_geometry()
        self._hit_layer.raise_()

        self._current_glow_radius = self.glow_radius
        self.glow_anim = QPropertyAnimation(self, b"current_glow_radius")
        self.glow_anim.setDuration(200)
        self.glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    @pyqtProperty(float)
    def current_glow_radius(self):
        return self._current_glow_radius

    @current_glow_radius.setter
    def current_glow_radius(self, value):
        self._current_glow_radius = value
        self.update()

    def set_view_transform(self, scale, offset_x, offset_y, base_width, base_height):
        old_scale = self._view_scale
        self._view_scale = float(scale)
        self._view_offset_x = float(offset_x)
        self._view_offset_y = float(offset_y)
        self._base_width = max(1.0, float(base_width))
        self._base_height = max(1.0, float(base_height))
        if abs(old_scale - self._view_scale) > 0.01:
            print(f"[CONN_TRANSFORM] View transform updated: scale={self._view_scale:.3f}, offset=({self._view_offset_x:.1f},{self._view_offset_y:.1f}), base=({self._base_width}x{self._base_height})")
        self.update_geometry()

    def _normalized_to_pixel(self, norm_x, norm_y):
        return QPointF(
            self._view_offset_x + (norm_x * self._base_width * self._view_scale),
            self._view_offset_y + (norm_y * self._base_height * self._view_scale)
        )

    def _pixel_to_normalized(self, pixel_point):
        denom_x = self._base_width * self._view_scale
        denom_y = self._base_height * self._view_scale
        if denom_x <= 0.0 or denom_y <= 0.0:
            return [0.5, 0.5]
        return [
            (pixel_point.x() - self._view_offset_x) / denom_x,
            (pixel_point.y() - self._view_offset_y) / denom_y
        ]

    def _clamp_normalized(self, norm_point):
        return [
            max(0.0, min(1.0, norm_point[0])),
            max(0.0, min(1.0, norm_point[1]))
        ]

    def get_pixel_points(self):
        return [self._normalized_to_pixel(p[0], p[1]) for p in self.points_normalized]

    def set_locked(self, locked):
        print(f"[LOCK] set_locked({locked}), widget geom=({self.x()},{self.y()},{self.width()}x{self.height()})")
        self._locked = locked
        if locked:
            self._drag_index = None
            self._drag_whole_line = False
            self._hover_index = None
            # In locked mode, parent is transparent - all events pass through
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._hit_layer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._hit_layer.clearMask()
            self.clearMask()  # Clear parent mask too
            # Reset edit mode paint flag so we debug next time
            if hasattr(self, '_painted_edit_mode'):
                delattr(self, '_painted_edit_mode')
            print(f"[LOCK] Locked mode: parent transparent, masks cleared")
        else:
            # In unlocked mode, keep parent transparent and use the hit layer
            # as the event target to allow pass-through outside the mask.
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._hit_layer.show()  # Ensure hit layer is visible before enabling events
            self._hit_layer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            print(f"[LOCK] Unlocked mode: parent transparent, hit layer active")
            self._update_mask()
            # Don't raise here - only raise when clicked
        self.update()
        print(f"[LOCK] After update, widget geom=({self.x()},{self.y()},{self.width()}x{self.height()})")

    def apply_scale(self, scale):
        self._interaction_scale = float(scale)
        if not self._locked:
            self._update_mask()

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._group_highlighted:
            self.opacity_effect.setOpacity(0.999)
            self.glow_anim.setStartValue(self._current_glow_radius)
            self.glow_anim.setEndValue(self.glow_radius * 2.5)
            self.glow_anim.start()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._group_highlighted:
            self.opacity_effect.setOpacity(0.8)
            self.glow_anim.setStartValue(self._current_glow_radius)
            self.glow_anim.setEndValue(self.glow_radius)
            self.glow_anim.start()

    def _handle_wheel_event(self, event):
        if not self._locked and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y()
            current_opacity = self.opacity_effect.opacity()
            step = 0.05
            if delta > 0:
                new_opacity = min(0.999, current_opacity + step)
            else:
                new_opacity = max(0.1, current_opacity - step)
            self.opacity_effect.setOpacity(new_opacity)
            event.accept()
            return
        event.ignore()

    def set_group_highlight(self, enabled):
        self.set_group_highlight_config(enabled)

    def set_group_highlight_config(self, enabled, glow_radius=None, glow_color=None):
        if enabled:
            if not self._group_highlighted:
                self._group_prev_opacity = self.opacity_effect.opacity()
                self._group_prev_glow_radius = self.current_glow_radius
                self._group_prev_glow_color = self.glow_color
            self._group_highlighted = True
            self.opacity_effect.setOpacity(0.999)
            if glow_color:
                self.glow_color = QColor(glow_color)
            if glow_radius is not None:
                self.current_glow_radius = float(glow_radius)
            else:
                self.current_glow_radius = self.glow_radius * 2.0
        else:
            self._group_highlighted = False
            if self._group_prev_opacity is not None:
                self.opacity_effect.setOpacity(self._group_prev_opacity)
            if self._group_prev_glow_radius is not None:
                self.current_glow_radius = self._group_prev_glow_radius
            if self._group_prev_glow_color is not None:
                self.glow_color = self._group_prev_glow_color

    def raise_hit_layer(self):
        if hasattr(self, '_hit_layer'):
            self._hit_layer.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_hit_layer_geometry()
        if not self._locked:
            self._update_mask()

    def update_geometry(self):
        if not self._locked:
            self._update_mask()
        self.update()

    def _handle_radius_px(self):
        return self.handle_radius * max(0.6, self._interaction_scale)

    def _update_mask(self):
        if not self.points_normalized:
            return

        print(f"[MASK] Widget geom: pos=({self.x()},{self.y()}), size=({self.width()}x{self.height()})")
        pixel_points = self.get_pixel_points()
        if pixel_points:
            print(f"[MASK] Pixel points[0]=({pixel_points[0].x():.1f},{pixel_points[0].y():.1f}), transform=(s={self._view_scale:.3f}, o=({self._view_offset_x:.1f},{self._view_offset_y:.1f}))")

        pixel_points = self.get_pixel_points()
        if not pixel_points:
            return

        mask_width = max(self.line_thickness, self.glow_radius) * 2
        path = QPainterPath()
        path.moveTo(pixel_points[0])
        for p in pixel_points[1:]:
            path.lineTo(p)

        stroker = QPainterPathStroker()
        stroker.setWidth(mask_width)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroke = stroker.createStroke(path)

        region = QRegion(stroke.toFillPolygon().toPolygon())
        handle_radius = self._handle_radius_px()
        for p in pixel_points:
            handle_path = QPainterPath()
            handle_path.addEllipse(p, handle_radius, handle_radius)
            region = region.united(QRegion(handle_path.toFillPolygon().toPolygon()))

        # Apply mask to hit layer only so visuals are not clipped.
        # Events outside the mask pass through to connectors underneath.
        self._hit_layer.setMask(region)
        self.update()

    def _is_in_hit_region(self, point):
        if not hasattr(self, '_hit_layer'):
            return True
        mask = self._hit_layer.mask()
        if mask.isEmpty():
            return True
        return mask.contains(point)

    def _sync_hit_layer_geometry(self):
        if hasattr(self, '_hit_layer'):
            if self._hit_layer.parent() is self:
                self._hit_layer.setGeometry(0, 0, self.width(), self.height())
            else:
                self._hit_layer.setGeometry(self.geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.points_normalized:
            return

        pixel_points = self.get_pixel_points()
        if not pixel_points:
            return

        # Debug paint during drag
        if self._drag_index is not None or self._drag_whole_line:
            print(f"[PAINT_DRAG] widget_pos=({self.x()},{self.y()}), norm[0]={self.points_normalized[0]}, pixel[0]=({pixel_points[0].x():.1f},{pixel_points[0].y():.1f}), "
                  f"transform=(s={self._view_scale:.3f}, o=({self._view_offset_x:.1f},{self._view_offset_y:.1f})), locked={self._locked}")
        elif not hasattr(self, '_painted_initial'):
            self._painted_initial = True
            print(f"[PAINT_INIT] widget_pos=({self.x()},{self.y()}), norm[0]={self.points_normalized[0]}, pixel[0]=({pixel_points[0].x():.1f},{pixel_points[0].y():.1f}), "
                  f"transform=(s={self._view_scale:.3f}, o=({self._view_offset_x:.1f},{self._view_offset_y:.1f})), locked={self._locked}")
        elif not self._locked and not hasattr(self, '_painted_edit_mode'):
            self._painted_edit_mode = True
            print(f"[PAINT_EDIT] widget_pos=({self.x()},{self.y()}), norm[0]={self.points_normalized[0]}, pixel[0]=({pixel_points[0].x():.1f},{pixel_points[0].y():.1f}), "
                  f"transform=(s={self._view_scale:.3f}, o=({self._view_offset_x:.1f},{self._view_offset_y:.1f})), locked={self._locked}")

        path = QPainterPath()
        path.moveTo(pixel_points[0])
        for p in pixel_points[1:]:
            path.lineTo(p)

        glow_color_alpha = QColor(self.glow_color)
        alpha = 150 if self.opacity_effect.opacity() > 0.9 else 50
        glow_color_alpha.setAlpha(alpha)

        glow_pen = QPen(glow_color_alpha)
        glow_pen.setWidthF(self._current_glow_radius)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)
        painter.drawPath(path)

        line_color_solid = QColor(self.line_color)
        line_color_solid.setAlpha(255)
        core_pen = QPen(line_color_solid)
        core_pen.setWidthF(self.line_thickness)
        core_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        core_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(core_pen)
        painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self.line_color))
        dot_radius = self.line_thickness * 2.0
        for p in pixel_points:
            painter.drawEllipse(p, dot_radius, dot_radius)

        if not self._locked:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            handle_radius = self._handle_radius_px()
            for i, p in enumerate(pixel_points):
                if i == self._hover_index:
                    painter.setPen(QPen(QColor("yellow"), 2))
                    painter.drawEllipse(p, handle_radius, handle_radius)
                elif i == self._drag_index:
                    painter.setPen(QPen(QColor("white"), 2, Qt.PenStyle.DashLine))
                    painter.drawEllipse(p, handle_radius, handle_radius)

    def _point_distance(self, p1, p2):
        dx = p1.x() - p2.x()
        dy = p1.y() - p2.y()
        return math.sqrt(dx * dx + dy * dy)

    def _point_near_line(self, point, line_start, line_end, threshold):
        line_len_sq = self._point_distance(line_start, line_end) ** 2
        if line_len_sq == 0:
            return self._point_distance(point, line_start) < threshold

        t = ((point.x() - line_start.x()) * (line_end.x() - line_start.x()) +
             (point.y() - line_start.y()) * (line_end.y() - line_start.y())) / line_len_sq
        t = max(0.0, min(1.0, t))

        proj_x = line_start.x() + t * (line_end.x() - line_start.x())
        proj_y = line_start.y() + t * (line_end.y() - line_start.y())
        proj = QPointF(proj_x, proj_y)

        return self._point_distance(point, proj) < threshold

    def mousePressEvent(self, event):
        self._handle_mouse_press(event)

    def _handle_mouse_press(self, event):
        if self._locked or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if not self._is_in_hit_region(event.position().toPoint()):
            event.ignore()
            return

        # Bring this connector to the front when clicked
        self.raise_()
        # Temporarily clear mask during drag for better visual updates
        self.clearMask()
        self._hit_layer.clearMask()
        print(f"[CONNECTOR_CLICK] Raised connector to top, cleared masks for drag")

        click_pos = event.position()
        pixel_points = self.get_pixel_points()
        handle_radius = self._handle_radius_px()

        for i, p in enumerate(pixel_points):
            if self._point_distance(click_pos, p) < handle_radius * 2:
                self._drag_index = i
                print(f"[DRAG_START] Grabbed point {i} at pixel ({p.x():.1f},{p.y():.1f}), norm={self.points_normalized[i]}")
                self.grabMouse()
                event.accept()
                return

        threshold = max(8.0, handle_radius)
        for i in range(len(pixel_points) - 1):
            if self._point_near_line(click_pos, pixel_points[i], pixel_points[i + 1], threshold):
                self._drag_whole_line = True
                self._drag_start_pos = click_pos
                self._drag_start_points = [p[:] for p in self.points_normalized]
                self.clearMask()  # Remove mask during drag for proper visual updates
                self.grabMouse()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._handle_mouse_move(event)

    def _handle_mouse_move(self, event):
        if self._locked:
            super().mouseMoveEvent(event)
            return

        mouse_pos = event.position()
        pixel_points = self.get_pixel_points()

        if self._drag_index is not None:
            norm_pos = self._pixel_to_normalized(mouse_pos)
            old_norm = self.points_normalized[self._drag_index][:]
            self.points_normalized[self._drag_index] = self._clamp_normalized(norm_pos)
            new_pixel = self._normalized_to_pixel(self.points_normalized[self._drag_index][0], self.points_normalized[self._drag_index][1])
            print(f"[DRAG] point{self._drag_index}: norm {old_norm} -> {self.points_normalized[self._drag_index]}, will paint at ({new_pixel.x():.1f},{new_pixel.y():.1f})")
            # Don't update mask during drag - it causes visual glitches
            self.update()  # This should trigger paintEvent
            self.configChanged.emit()
            event.accept()
            return

        if self._drag_whole_line and self._drag_start_pos is not None:
            delta = mouse_pos - self._drag_start_pos
            denom_x = self._base_width * self._view_scale
            denom_y = self._base_height * self._view_scale
            delta_norm_x = delta.x() / denom_x if denom_x > 0 else 0.0
            delta_norm_y = delta.y() / denom_y if denom_y > 0 else 0.0

            for i, start_pos in enumerate(self._drag_start_points):
                new_x = start_pos[0] + delta_norm_x
                new_y = start_pos[1] + delta_norm_y
                self.points_normalized[i] = self._clamp_normalized([new_x, new_y])

            # Don't update mask during drag - it causes visual glitches
            self.update()
            self.configChanged.emit()
            event.accept()
            return

        if not self._is_in_hit_region(mouse_pos.toPoint()):
            if self._hover_index is not None:
                self._hover_index = None
                self.update()
            event.ignore()
            return

        old_hover = self._hover_index
        self._hover_index = None
        handle_radius = self._handle_radius_px()
        for i, p in enumerate(pixel_points):
            if self._point_distance(mouse_pos, p) < handle_radius * 2:
                self._hover_index = i
                break

        if old_hover != self._hover_index:
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._handle_mouse_release(event)

    def _handle_mouse_release(self, event):
        if self._drag_index is not None or self._drag_whole_line:
            if self._drag_index is not None:
                print(f"[DRAG_END] Released point {self._drag_index}, final norm={self.points_normalized[self._drag_index]}")
            else:
                print(f"[DRAG_END] Released whole line")
            self.releaseMouse()
            self._drag_index = None
            self._drag_whole_line = False
            self._drag_start_pos = None
            self._drag_start_points = None
            # Restore mask after drag completes
            self._update_mask()
            self.configChanged.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._handle_mouse_double_click(event)

    def _handle_mouse_double_click(self, event):
        if self._locked or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        if not self._is_in_hit_region(event.position().toPoint()):
            event.ignore()
            return

        click_pos = event.position()
        pixel_points = self.get_pixel_points()
        threshold = max(8.0, self._handle_radius_px())

        for i in range(len(pixel_points) - 1):
            if self._point_near_line(click_pos, pixel_points[i], pixel_points[i + 1], threshold):
                new_norm = self._pixel_to_normalized(click_pos)
                self.points_normalized.insert(i + 1, self._clamp_normalized(new_norm))
                self._update_mask()
                self.update()
                self.configChanged.emit()
                event.accept()
                return

        super().mouseDoubleClickEvent(event)