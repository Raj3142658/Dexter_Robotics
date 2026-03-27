"""
frenet_serret.py
================
Computes Frenet-Serret moving frames along a 3-D curve and converts them
into geometry_msgs/Pose orientations for MoveIt2 computeCartesianPath.

Theory
------
At every point P[i] on the curve:
  T = tangent  = (P[i+1] - P[i-1]) / |...|   ← travel direction
  N = surface_normal                           ← points away from workpiece
  B = T × N  (binormal, ~lateral)             ← completes right-hand frame

The end-effector frame is:
  tool_z = -N   (tool points INTO the surface)
  tool_x =  T   (tool travels in this direction)
  tool_y =  B

An optional tilt rotates the tool around tool_y (forward tilt, like a welding torch).
"""

import numpy as np
from scipy.spatial.transform import Rotation as R
from geometry_msgs.msg import Pose, Point, Quaternion


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-9:
        raise ValueError(f'Cannot normalize near-zero vector: {v}')
    return v / n


def _perp_vector(v: np.ndarray) -> np.ndarray:
    """Returns a vector perpendicular to v (stable for any direction)."""
    v = _normalize(v)
    # Pick the axis least aligned with v
    candidates = [np.array([1,0,0]), np.array([0,1,0]), np.array([0,0,1])]
    best = min(candidates, key=lambda c: abs(np.dot(v, c)))
    return _normalize(np.cross(v, best))


class FrenetSerretFrames:
    """
    Attaches a physically-meaningful end-effector orientation to every
    position waypoint along a curve.

    Parameters
    ----------
    surface_normal : array (3,)
        Unit vector pointing away from the work surface (e.g. [0,0,1] for a table).
    tool_tilt_deg : float
        Forward tilt of the tool in the travel direction (degrees).
        0° = perpendicular to surface. 10-15° typical for welding.
    """

    def __init__(self, surface_normal: np.ndarray, tool_tilt_deg: float = 0.0):
        self.surface_normal = _normalize(np.array(surface_normal, dtype=float))
        self.tilt_rad = np.deg2rad(tool_tilt_deg)

    def build_pose_list(self, positions: np.ndarray) -> list:
        """
        Given (N, 3) position array, return a list of geometry_msgs/Pose
        with position + orientation filled in.

        Parameters
        ----------
        positions : np.ndarray, shape (N, 3)

        Returns
        -------
        list of geometry_msgs.msg.Pose  (length N)
        """
        N = len(positions)
        if N < 2:
            raise ValueError('Need at least 2 waypoints to compute tangents.')

        tangents = self._compute_tangents(positions)
        poses    = []

        for i in range(N):
            T = tangents[i]
            q = self._frame_to_quaternion(T)
            p = Pose()
            p.position.x = float(positions[i, 0])
            p.position.y = float(positions[i, 1])
            p.position.z = float(positions[i, 2])
            p.orientation.x = float(q[0])
            p.orientation.y = float(q[1])
            p.orientation.z = float(q[2])
            p.orientation.w = float(q[3])
            poses.append(p)

        return poses

    # ─── INTERNALS ────────────────────────────────────────────────────────────

    def _compute_tangents(self, positions: np.ndarray) -> np.ndarray:
        """
        Central-difference tangents (forward/backward at endpoints).
        Returns (N, 3) unit tangent vectors.
        """
        N = len(positions)
        tangents = np.zeros((N, 3))

        for i in range(N):
            if i == 0:
                raw = positions[1] - positions[0]
            elif i == N - 1:
                raw = positions[-1] - positions[-2]
            else:
                raw = positions[i + 1] - positions[i - 1]  # central diff

            norm = np.linalg.norm(raw)
            if norm < 1e-9:
                # Degenerate: reuse previous tangent
                tangents[i] = tangents[i - 1] if i > 0 else np.array([1, 0, 0])
            else:
                tangents[i] = raw / norm

        return tangents

    def _frame_to_quaternion(self, tangent: np.ndarray) -> np.ndarray:
        """
        Builds rotation matrix from Frenet frame and returns quaternion [x,y,z,w].

        Frame convention:
          tool_z = -surface_normal  (approach direction, into workpiece)
          tool_x = tangent          (travel direction)
          tool_y = cross(tool_z, tool_x)  completes right-hand frame

        A forward tilt rotates around tool_y by tilt_rad.
        """
        N  = self.surface_normal
        T  = tangent

        # tool_z points INTO the surface (approach direction)
        tool_z = -N

        # Re-orthogonalize tangent against tool_z
        # (tangent might not be exactly perpendicular to surface normal for
        # non-flat surfaces — Gram-Schmidt step)
        T_ortho = T - np.dot(T, tool_z) * tool_z
        norm_T  = np.linalg.norm(T_ortho)
        if norm_T < 1e-6:
            # Tangent is parallel to approach vector — degenerate case
            # Fall back to a fixed reference direction
            T_ortho = _perp_vector(tool_z)
        else:
            T_ortho = T_ortho / norm_T

        tool_x = T_ortho
        tool_y = np.cross(tool_z, tool_x)
        tool_y = tool_y / np.linalg.norm(tool_y)

        # Rotation matrix: columns are [tool_x, tool_y, tool_z]
        rot_mat = np.column_stack([tool_x, tool_y, tool_z])

        # Apply forward tilt around tool_y (in tool frame)
        if abs(self.tilt_rad) > 1e-6:
            tilt_rot = R.from_rotvec(self.tilt_rad * tool_y)
            rot_mat  = (tilt_rot.as_matrix() @ rot_mat)

        # Convert to quaternion [x, y, z, w]
        rotation = R.from_matrix(rot_mat)
        q = rotation.as_quat()   # scipy returns [x, y, z, w]
        return q
