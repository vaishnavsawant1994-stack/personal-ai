from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget


class PulseWidget(QWidget):
    """Personal AI Home V1 living neural field.

    The core is deliberately open, asymmetric and non-mechanical. It behaves
    like a living constellation of memory/context paths instead of a ring,
    orb, reactor or loading spinner. State motion expresses what the AI is
    doing while preserving one continuous identity.
    """

    STATE_ALIASES = {
        "memory_retrieval": "memory",
        "retrieving_memory": "memory",
        "knowledge_retrieval": "knowledge",
        "retrieving_knowledge": "knowledge",
        "tool": "acting",
        "action": "acting",
        "responding": "speaking",
        "response": "speaking",
        "needs_approval": "approval",
        "waiting_approval": "approval",
        "ready": "active",
    }
    STATE_SPEEDS = {
        "idle": 0.012,
        "active": 0.022,
        "listening": 0.046,
        "understanding": 0.038,
        "thinking": 0.061,
        "memory": 0.042,
        "knowledge": 0.048,
        "acting": 0.072,
        "speaking": 0.052,
        "approval": 0.010,
        "error": 0.026,
        "background": 0.006,
    }
    STATE_ENERGY = {
        "idle": 0.50,
        "active": 0.62,
        "listening": 0.82,
        "understanding": 0.76,
        "thinking": 1.00,
        "memory": 0.94,
        "knowledge": 0.88,
        "acting": 0.94,
        "speaking": 0.88,
        "approval": 0.38,
        "error": 0.54,
        "background": 0.23,
    }
    STATE_AMPLITUDE = {
        "idle": 0.014,
        "active": 0.019,
        "listening": 0.029,
        "understanding": 0.024,
        "thinking": 0.038,
        "memory": 0.031,
        "knowledge": 0.028,
        "acting": 0.026,
        "speaking": 0.032,
        "approval": 0.011,
        "error": 0.020,
        "background": 0.007,
    }

    # Stable irregular neural constellation. The outer nodes are intentionally
    # not connected as a perimeter so the silhouette never becomes an oval.
    CORE_NODES = (
        (-0.27, -0.10),
        (-0.19, -0.27),
        (-0.05, -0.19),
        (0.12, -0.26),
        (0.26, -0.14),
        (0.19, -0.02),
        (0.28, 0.14),
        (0.09, 0.24),
        (-0.07, 0.18),
        (-0.24, 0.25),
        (-0.21, 0.04),
        (-0.08, -0.04),
        (0.05, 0.03),
        (0.15, 0.10),
        (-0.02, 0.30),
        (0.00, -0.32),
        (-0.32, 0.10),
        (0.30, -0.02),
    )
    CORE_EDGES = (
        (0, 2), (0, 10),
        (1, 2), (1, 11), (1, 15),
        (2, 11), (2, 12), (2, 3),
        (3, 12), (3, 4),
        (4, 5), (4, 17),
        (5, 12), (5, 13), (5, 17),
        (6, 13), (6, 7),
        (7, 13), (7, 8), (7, 14),
        (8, 12), (8, 14), (8, 9),
        (9, 10), (9, 14),
        (10, 11), (10, 16),
        (11, 12), (12, 13),
    )
    # Open filaments give the field a heartbeat-like flow without enclosing it.
    FLOW_PATHS = (
        ((-0.34, -0.06), (-0.22, -0.17), (-0.10, -0.14), (0.04, -0.04)),
        ((-0.16, -0.34), (-0.07, -0.24), (0.08, -0.12), (0.22, -0.18)),
        ((0.31, -0.19), (0.24, -0.08), (0.10, 0.03), (0.20, 0.19)),
        ((0.25, 0.25), (0.12, 0.19), (-0.02, 0.08), (-0.18, 0.18)),
        ((-0.30, 0.28), (-0.22, 0.16), (-0.08, 0.05), (0.05, 0.13)),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.t = 0.0
        self.state = "idle"
        self.reduce_motion = False
        self.memory_labels = ("Project", "Person", "Decision", "Conversation")
        self.seed = [random.Random(101 + i).uniform(-1.0, 1.0) for i in range(48)]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.setAccessibleName("Personal AI living core")

    @classmethod
    def normalize_state(cls, state: str) -> str:
        key = str(state or "idle").strip().lower().replace("-", "_").replace(" ", "_")
        return cls.STATE_ALIASES.get(key, key if key in cls.STATE_SPEEDS else "idle")

    def set_state(self, state):
        self.state = self.normalize_state(state)
        self.update()

    def set_memory_labels(self, labels):
        cleaned = [str(item).strip() for item in labels if str(item).strip()]
        if cleaned:
            self.memory_labels = tuple(cleaned[:4])
        self.update()

    def set_reduce_motion(self, value: bool):
        self.reduce_motion = bool(value)
        self.timer.setInterval(120 if self.reduce_motion else 16)
        self.update()

    def tick(self):
        speed = self.STATE_SPEEDS[self.state]
        self.t += speed * (0.18 if self.reduce_motion else 1.0)
        self.update()

    def _palette(self):
        if self.state == "error":
            return QColor(234, 158, 143), QColor(184, 102, 92)
        if self.state == "approval":
            return QColor(214, 205, 166), QColor(154, 144, 104)
        if self.state == "memory":
            return QColor(155, 220, 216), QColor(84, 154, 153)
        if self.state == "knowledge":
            return QColor(171, 206, 233), QColor(95, 136, 171)
        return QColor(164, 224, 236), QColor(83, 151, 169)

    def _node_position(self, cx, cy, width, height, index, amplitude=None):
        nx, ny = self.CORE_NODES[index]
        amp = self.STATE_AMPLITUDE[self.state] if amplitude is None else amplitude
        if self.reduce_motion:
            amp *= 0.42
        seed = self.seed[index]
        phase = self.t * (0.62 + (index % 4) * 0.07) + seed * 2.4
        breath = 1.0 + math.sin(self.t * 0.72 + index * 0.17) * amp * 0.34
        dx = math.sin(phase) * width * amp * 0.070
        dy = math.cos(phase * 0.83) * height * amp * 0.076
        return QPointF(
            cx + nx * width * 0.78 * breath + dx,
            cy + ny * height * 0.88 * breath + dy,
        )

    def _curve_between(self, a, b, index, bend_scale=1.0):
        mx = (a.x() + b.x()) * 0.5
        my = (a.y() + b.y()) * 0.5
        vx = b.x() - a.x()
        vy = b.y() - a.y()
        length = max(1.0, math.hypot(vx, vy))
        direction = -1.0 if index % 2 else 1.0
        bend = (8.0 + (index % 5) * 3.0) * direction * bend_scale
        control = QPointF(mx - vy / length * bend, my + vx / length * bend)
        path = QPainterPath(a)
        path.quadTo(control, b)
        return path

    def _draw_flow_paths(self, painter, cx, cy, width, height, primary):
        energy = self.STATE_ENERGY[self.state]
        amp = self.STATE_AMPLITUDE[self.state] * (0.42 if self.reduce_motion else 1.0)
        for index, template in enumerate(self.FLOW_PATHS):
            phase = self.t * (0.34 + index * 0.025) + self.seed[24 + index]
            points = []
            for point_index, (nx, ny) in enumerate(template):
                wave_x = math.sin(phase + point_index * 1.2) * width * amp * 0.085
                wave_y = math.cos(phase * 0.9 + point_index) * height * amp * 0.095
                points.append(
                    QPointF(
                        cx + nx * width * 0.78 + wave_x,
                        cy + ny * height * 0.88 + wave_y,
                    )
                )
            path = QPainterPath(points[0])
            path.cubicTo(points[1], points[2], points[3])
            alpha = int((82 - index * 5) * energy)
            pen = QPen(QColor(primary.red(), primary.green(), primary.blue(), max(16, alpha)))
            pen.setWidthF(1.12 if index in (1, 3) else 0.88)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _draw_lattice(self, painter, cx, cy, width, height, primary):
        energy = self.STATE_ENERGY[self.state]
        points = [self._node_position(cx, cy, width, height, i) for i in range(len(self.CORE_NODES))]
        self._draw_flow_paths(painter, cx, cy, width, height, primary)

        active_phase = int(self.t * 1.45) % 4
        for edge_index, (source, target) in enumerate(self.CORE_EDGES):
            alpha = int((88 + (edge_index % 4) * 15) * energy)
            width_boost = 0.0
            if self.state in ("thinking", "understanding") and edge_index % 4 == active_phase:
                alpha += 58
                width_boost = 0.38
            pen = QPen(
                QColor(
                    primary.red(),
                    primary.green(),
                    primary.blue(),
                    min(188, max(16, alpha)),
                )
            )
            pen.setWidthF(0.72 + (edge_index % 3) * 0.12 + width_boost)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._curve_between(points[source], points[target], edge_index))

        count = 11 if self.state == "background" else len(points)
        for index, point in enumerate(points[:count]):
            alpha = int((104 + (index % 4) * 18) * energy)
            radius = 1.45 + (index % 3) * 0.36
            if self.state == "thinking" and index % 4 == active_phase:
                alpha = min(220, alpha + 72)
                radius += 1.25
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 24))
                painter.drawEllipse(point, radius + 6.0, radius + 6.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), max(18, alpha)))
            painter.drawEllipse(point, radius, radius)

    def _draw_listening(self, painter, cx, cy, width, height, primary):
        if self.state != "listening":
            return
        targets = (0, 4, 6, 9)
        origins = ((-0.36, -0.20), (0.36, -0.22), (0.37, 0.20), (-0.36, 0.22))
        for i, (target_index, (ox, oy)) in enumerate(zip(targets, origins)):
            target = self._node_position(cx, cy, width, height, target_index)
            origin = QPointF(cx + ox * width, cy + oy * height)
            progress = (self.t * 0.30 + i * 0.19) % 1.0
            # Intake strokes contract toward the lattice. They remain short and
            # curved instead of becoming screen-spanning technical spokes.
            sx = origin.x() + (target.x() - origin.x()) * progress * 0.35
            sy = origin.y() + (target.y() - origin.y()) * progress * 0.35
            start = QPointF(sx, sy)
            path = self._curve_between(start, target, i + 40, bend_scale=1.75)
            alpha = int(122 * (1.0 - progress * 0.34))
            painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), alpha), 1.05))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 86))
            painter.drawEllipse(start, 1.8, 1.8)

    def _draw_thinking(self, painter, cx, cy, width, height, primary):
        if self.state not in ("understanding", "thinking"):
            return
        signal_count = 9 if self.state == "thinking" else 5
        for i in range(signal_count):
            edge_index = (i * 3 + int(self.t * 2.0)) % len(self.CORE_EDGES)
            source_index, target_index = self.CORE_EDGES[edge_index]
            a = self._node_position(cx, cy, width, height, source_index)
            b = self._node_position(cx, cy, width, height, target_index)
            q = (self.t * 0.23 + i * 0.115) % 1.0
            x = a.x() + (b.x() - a.x()) * q
            y = a.y() + (b.y() - a.y()) * q
            point = QPointF(x, y)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 34))
            painter.drawEllipse(point, 6.0, 6.0)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 176))
            painter.drawEllipse(point, 2.35, 2.35)

    def _draw_memory(self, painter, cx, cy, width, height, primary):
        if self.state != "memory":
            return
        source_nodes = (1, 4, 6, 9)
        anchors = ((-0.30, -0.25), (0.32, -0.20), (0.31, 0.25), (-0.31, 0.24))
        font = QFont()
        font.setPointSizeF(8.2)
        painter.setFont(font)
        for index, (source_index, (ax, ay)) in enumerate(zip(source_nodes, anchors)):
            source = self._node_position(cx, cy, width, height, source_index)
            endpoint = QPointF(cx + ax * width, cy + ay * height)
            path = self._curve_between(source, endpoint, index + 60, bend_scale=2.0)
            painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 118), 1.02))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 188))
            painter.drawEllipse(endpoint, 2.7, 2.7)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 26))
            painter.drawEllipse(endpoint, 7.0, 7.0)
            label = self.memory_labels[index % len(self.memory_labels)]
            painter.setPen(QColor(primary.red(), primary.green(), primary.blue(), 148))
            tx = 10 if ax >= 0 else -70
            painter.drawText(int(endpoint.x() + tx), int(endpoint.y() - 6), label)

    def _draw_knowledge(self, painter, cx, cy, width, height, primary):
        if self.state != "knowledge":
            return
        sources = ((-0.25, -0.34), (0.00, -0.39), (0.27, -0.32))
        for i, (source_xy, target_index) in enumerate(zip(sources, (1, 15, 4))):
            source = QPointF(cx + source_xy[0] * width, cy + source_xy[1] * height)
            target = self._node_position(cx, cy, width, height, target_index)
            path = self._curve_between(source, target, i + 70, bend_scale=1.8)
            painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 92), 0.95))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _draw_action(self, painter, cx, cy, width, height, primary):
        if self.state != "acting":
            return
        start = self._node_position(cx, cy, width, height, 17)
        end = QPointF(start.x() + width * 0.105, start.y() - height * 0.035)
        path = self._curve_between(start, end, 80, bend_scale=1.5)
        painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 148), 1.20))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 190))
        painter.drawEllipse(end, 3.0, 3.0)

    def _draw_speaking(self, painter, cx, cy, width, height, primary):
        if self.state != "speaking":
            return
        source_indices = (3, 4, 17, 6, 7)
        angles = (-1.22, -0.68, -0.05, 0.58, 1.10)
        for i, (source_index, angle) in enumerate(zip(source_indices, angles)):
            source = self._node_position(cx, cy, width, height, source_index)
            reach = width * (0.072 + 0.009 * math.sin(self.t * 2.3 + i))
            end = QPointF(
                source.x() + math.cos(angle) * reach,
                source.y() + math.sin(angle) * height * 0.095,
            )
            path = self._curve_between(source, end, i + 90, bend_scale=1.35)
            painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 92 + i * 9), 0.96))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(primary.red(), primary.green(), primary.blue(), 82))
            painter.drawEllipse(end, 1.7, 1.7)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        cx, cy = width * 0.50, height * 0.50
        primary, secondary = self._palette()
        energy = self.STATE_ENERGY[self.state]

        glow = QRadialGradient(QPointF(cx, cy), min(width, height) * 0.45)
        glow.setColorAt(
            0,
            QColor(primary.red(), primary.green(), primary.blue(), int(34 * energy)),
        )
        glow.setColorAt(
            0.42,
            QColor(secondary.red(), secondary.green(), secondary.blue(), int(16 * energy)),
        )
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(
            QPointF(cx, cy),
            min(width, height) * 0.43,
            min(width, height) * 0.33,
        )

        self._draw_lattice(painter, cx, cy, width, height, primary)
        self._draw_listening(painter, cx, cy, width, height, primary)
        self._draw_thinking(painter, cx, cy, width, height, primary)
        self._draw_memory(painter, cx, cy, width, height, primary)
        self._draw_knowledge(painter, cx, cy, width, height, primary)
        self._draw_action(painter, cx, cy, width, height, primary)
        self._draw_speaking(painter, cx, cy, width, height, primary)
