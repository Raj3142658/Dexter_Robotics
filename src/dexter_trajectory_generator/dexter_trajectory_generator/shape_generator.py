"""
shape_generator.py
==================
Generates 3-D position waypoints for each supported shape.
All shapes are defined relative to a reference point and projected
onto the work surface plane (defined by its normal vector).

Supported shapes
----------------
  circle     - center = reference, radius
  line       - start = reference, length, travel_direction (optional)
  rectangle  - center = reference, width, height
  arc        - center = reference, radius, start_angle_deg, end_angle_deg
  zigzag     - start = reference, total_length, zag_width, steps
  spiral     - center = reference, inner_radius, outer_radius, turns
"""

import numpy as np
from typing import Dict, Any


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _perp_vector(v: np.ndarray) -> np.ndarray:
    v = _normalize(v)
    candidates = [np.array([1,0,0], dtype=float),
                  np.array([0,1,0], dtype=float),
                  np.array([0,0,1], dtype=float)]
    best = min(candidates, key=lambda c: abs(np.dot(v, c)))
    return _normalize(np.cross(v, best))


def _surface_frame(normal: np.ndarray):
    """
    Returns (u, v) — two orthonormal vectors that span the surface plane.
    u is a stable 'first axis', v = normal × u.
    """
    n = _normalize(normal)
    u = _perp_vector(n)
    v = _normalize(np.cross(n, u))
    return u, v


class ShapeGenerator:
    """
    Parameters
    ----------
    shape_config : dict
        Must contain 'type' and shape-specific params (see docstring above).
    reference_point : np.ndarray (3,)
        The anchor point in world frame (center, start, etc. depending on shape).
    surface_normal : np.ndarray (3,)
        Unit normal of the work surface. Determines the plane of the shape.
    """

    def __init__(self, shape_config: Dict[str, Any],
                 reference_point: np.ndarray,
                 surface_normal: np.ndarray):
        self.cfg    = shape_config
        self.ref    = np.array(reference_point, dtype=float)
        self.normal = _normalize(np.array(surface_normal, dtype=float))
        self.u, self.v = _surface_frame(self.normal)

    def generate(self) -> np.ndarray:
        """Returns (N, 3) array of 3-D waypoints."""
        shape_type = self.cfg['type'].lower()
        dispatch = {
            'circle':    self._circle,
            'line':      self._line,
            'rectangle': self._rectangle,
            'rect':      self._rectangle,
            'arc':       self._arc,
            'zigzag':    self._zigzag,
            'spiral':    self._spiral,
        }
        if shape_type not in dispatch:
            raise ValueError(
                f'Unknown shape type: "{shape_type}". '
                f'Supported: {list(dispatch.keys())}'
            )
        pts_2d = dispatch[shape_type]()   # (N, 2) in surface UV frame
        return self._to_3d(pts_2d)

    # ─── PRIVATE: 2-D shape generators (UV surface plane) ────────────────────

    def _circle(self) -> np.ndarray:
        """
        Config keys:
            radius      (float, meters)        default 0.08
            n_points    (int)                  default 100
        Reference = center of circle.
        """
        r = float(self.cfg.get('radius', 0.08))
        N = int(self.cfg.get('n_points', 100))
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
        return np.column_stack([r * np.cos(angles), r * np.sin(angles)])

    def _line(self) -> np.ndarray:
        """
        Config keys:
            length          (float, meters)    default 0.15
            n_points        (int)              default 60
            direction_u     (float)            component along surface U-axis
            direction_v     (float)            component along surface V-axis
        Reference = start of line (left end).
        """
        length = float(self.cfg.get('length', 0.15))
        N      = int(self.cfg.get('n_points', 60))
        du     = float(self.cfg.get('direction_u', 1.0))
        dv     = float(self.cfg.get('direction_v', 0.0))
        # Normalize direction
        d_norm = np.sqrt(du**2 + dv**2)
        if d_norm < 1e-9:
            du, dv = 1.0, 0.0
        else:
            du, dv = du / d_norm, dv / d_norm
        t = np.linspace(0, length, N)
        return np.column_stack([t * du, t * dv])

    def _rectangle(self) -> np.ndarray:
        """
        Config keys:
            width       (float, meters)        default 0.12
            height      (float, meters)        default 0.08
            n_points    (int)                  default 120
        Reference = center of rectangle.
        Traverses perimeter clockwise starting bottom-left.
        """
        w  = float(self.cfg.get('width',    0.12))
        h  = float(self.cfg.get('height',   0.08))
        N  = int(self.cfg.get('n_points',   120))
        hw, hh = w / 2, h / 2
        corners = [
            np.array([-hw, -hh]),
            np.array([ hw, -hh]),
            np.array([ hw,  hh]),
            np.array([-hw,  hh]),
            np.array([-hw, -hh]),   # close
        ]
        n_per = N // 4
        pts = []
        for i in range(4):
            ts = np.linspace(0, 1, n_per, endpoint=False)
            for t in ts:
                pts.append((1 - t) * corners[i] + t * corners[i + 1])
        pts.append(corners[0])
        return np.array(pts)

    def _arc(self) -> np.ndarray:
        """
        Config keys:
            radius          (float, meters)    default 0.10
            start_angle_deg (float)            default 0
            end_angle_deg   (float)            default 180
            n_points        (int)              default 80
        Reference = center of arc.
        """
        r     = float(self.cfg.get('radius',          0.10))
        a_st  = np.deg2rad(float(self.cfg.get('start_angle_deg', 0)))
        a_en  = np.deg2rad(float(self.cfg.get('end_angle_deg',   180)))
        N     = int(self.cfg.get('n_points', 80))
        angles = np.linspace(a_st, a_en, N)
        return np.column_stack([r * np.cos(angles), r * np.sin(angles)])

    def _zigzag(self) -> np.ndarray:
        """
        Config keys:
            length      (float, meters)    default 0.15   total travel
            zag_width   (float, meters)    default 0.04   amplitude
            steps       (int)              default 6      number of zigs
            n_points    (int)              default 80
        Reference = start of zigzag (left end, center line).
        """
        L      = float(self.cfg.get('length',    0.15))
        amp    = float(self.cfg.get('zag_width', 0.04))
        steps  = int(self.cfg.get('steps',       6))
        N      = int(self.cfg.get('n_points',    80))

        # Build corner list
        corners = []
        for i in range(steps + 1):
            u_val = L * i / steps
            v_val = amp if i % 2 else -amp
            corners.append(np.array([u_val, v_val]))

        # Interpolate between corners
        n_per = N // steps
        pts = []
        for i in range(len(corners) - 1):
            ts = np.linspace(0, 1, n_per, endpoint=False)
            for t in ts:
                pts.append((1 - t) * corners[i] + t * corners[i + 1])
        pts.append(corners[-1])
        return np.array(pts)

    def _spiral(self) -> np.ndarray:
        """
        Config keys:
            inner_radius    (float, meters)    default 0.03
            outer_radius    (float, meters)    default 0.10
            turns           (float)            default 2.5
            n_points        (int)              default 120
        Reference = center of spiral.
        """
        r1    = float(self.cfg.get('inner_radius', 0.03))
        r2    = float(self.cfg.get('outer_radius', 0.10))
        turns = float(self.cfg.get('turns',         2.5))
        N     = int(self.cfg.get('n_points',        120))
        t = np.linspace(0, 1, N)
        r = r1 + (r2 - r1) * t
        a = t * turns * 2 * np.pi
        return np.column_stack([r * np.cos(a), r * np.sin(a)])

    # ─── PROJECTION: UV → 3D world frame ─────────────────────────────────────

    def _to_3d(self, pts_2d: np.ndarray) -> np.ndarray:
        """
        Projects (N, 2) surface-plane coordinates to (N, 3) world coordinates.
        World point = reference + u_coord * U + v_coord * V
        """
        return (self.ref[np.newaxis, :]
                + pts_2d[:, 0:1] * self.u[np.newaxis, :]
                + pts_2d[:, 1:2] * self.v[np.newaxis, :])
