"""
csv_exporter.py
================
Reads a trajectory YAML produced by trajectory_node and exports the
right-arm waypoints to a CSV readable by the csv_visualizer ROS node.

CSV format matches dexter_right_*.csv (as expected by csv_visualizer):
    x, y, z, arm_id, arm, j1_deg, j2_deg, j3_deg, j4_deg, j5_deg, j6_deg

Usage:
    python3 csv_exporter.py <yaml_file_path> <shape_name>

Output:
    data/workspaces/<shape_name>.csv
"""

import yaml
import csv
import math
import sys
from pathlib import Path

URDF_PATH = Path(
    "/home/raj/dexter_arm_ws/src/dexter_arm_description/urdf/dexter.urdf"
)
OUT_DIR = Path(
    "/home/raj/dexter_arm_ws/src/dexter_arm_dashboard/data/workspaces"
)

RIGHT_ARM_BASE = "base_link"
RIGHT_ARM_TIP  = "r_end_effector_link"   # will probe the URDF below


# ── URDF → KDL ────────────────────────────────────────────────────────────────

def _urdf_joint_to_kdl(joint, PyKDL):
    origin = PyKDL.Vector(0.0, 0.0, 0.0)
    axis   = (
        PyKDL.Vector(joint.axis[0], joint.axis[1], joint.axis[2])
        if joint.axis else PyKDL.Vector(0.0, 0.0, 1.0)
    )
    if joint.type == "fixed":
        return PyKDL.Joint(joint.name, PyKDL.Joint.Fixed)
    if joint.type in ("revolute", "continuous"):
        return PyKDL.Joint(joint.name, origin, axis, PyKDL.Joint.RotAxis)
    if joint.type == "prismatic":
        return PyKDL.Joint(joint.name, origin, axis, PyKDL.Joint.TransAxis)
    return PyKDL.Joint(joint.name, PyKDL.Joint.Fixed)


def _urdf_pose_to_kdl(pose, PyKDL):
    pos = PyKDL.Vector(0.0, 0.0, 0.0)
    rot = PyKDL.Rotation.Identity()
    if pose:
        if pose.xyz: pos = PyKDL.Vector(*pose.xyz)
        if pose.rpy: rot = PyKDL.Rotation.RPY(*pose.rpy)
    return PyKDL.Frame(rot, pos)


def urdf_to_kdl_tree(robot, PyKDL):
    tree = PyKDL.Tree(robot.get_root())

    def add_children(kdl_tree, link_name):
        if link_name not in robot.child_map:
            return
        for joint_name, child_link in robot.child_map[link_name]:
            j_urdf   = robot.joint_map[joint_name]
            kdl_jnt  = _urdf_joint_to_kdl(j_urdf, PyKDL)
            kdl_orig = _urdf_pose_to_kdl(j_urdf.origin, PyKDL)
            if kdl_jnt.getType() != PyKDL.Joint.Fixed:
                pre_name = child_link + "_pre_kdl"
                tree.addSegment(PyKDL.Segment(pre_name,      PyKDL.Joint(joint_name + "_pre", PyKDL.Joint.Fixed), kdl_orig), link_name)
                tree.addSegment(PyKDL.Segment(child_link,    kdl_jnt, PyKDL.Frame()), pre_name)
            else:
                tree.addSegment(PyKDL.Segment(child_link, kdl_jnt, kdl_orig), link_name)
            add_children(kdl_tree, child_link)

    add_children(tree, robot.get_root())
    return tree


def find_tip_link(robot, arm: str = "right") -> str:
    """Find the end-effector link name for the given arm."""
    keywords = ["end_effector", "tool", "tip", "eef"]
    candidates = [
        l for l in robot.link_map
        if any(k in l.lower() for k in keywords)
    ]
    right_cands = [l for l in candidates if "r" in l.lower() or "right" in l.lower()]
    if right_cands:
        return right_cands[0]
    if candidates:
        return candidates[0]
    # fallback: last leaf link
    all_children = {c for jn, c in sum(robot.child_map.values(), [])}
    leaves = [l for l in robot.link_map if l not in all_children]
    return leaves[0] if leaves else list(robot.link_map.keys())[-1]


# ── Main export ───────────────────────────────────────────────────────────────

def process_and_write(yaml_file: Path, shape_name: str) -> None:
    # 1. Load YAML
    class SafeLoader(yaml.SafeLoader): pass
    SafeLoader.add_multi_constructor('!', lambda l, s, n: None)
    trajectory_data = yaml.load(yaml_file.read_text(encoding='utf-8'), Loader=SafeLoader)

    if not trajectory_data or 'points' not in trajectory_data:
        print(f"[CSV EXPORTER] Error: no 'points' key in {yaml_file}")
        return

    points      = trajectory_data['points']
    joint_names = trajectory_data.get('joint_names', [])

    # right-arm indices = joints whose name ends with 'r'
    right_idx = [i for i, n in enumerate(joint_names) if n.endswith('r')]
    if not right_idx:
        n_total   = len(points[0]['positions']) if points else 12
        right_idx = list(range(n_total // 2, n_total))

    # 2. Build FK solver from the real URDF
    try:
        import PyKDL
        from urdf_parser_py.urdf import URDF

        if not URDF_PATH.exists():
            # Try to compile from xacro on-the-fly
            import subprocess
            xacro_path = str(URDF_PATH).replace('.urdf', '.urdf.xacro')
            subprocess.run(['xacro', xacro_path, '-o', str(URDF_PATH)], check=True)

        robot   = URDF.from_xml_file(str(URDF_PATH))
        tree    = urdf_to_kdl_tree(robot, PyKDL)
        tip     = find_tip_link(robot)
        chain   = tree.getChain(RIGHT_ARM_BASE, tip)
        fk      = PyKDL.ChainFkSolverPos_recursive(chain)
        n_jnts  = chain.getNrOfJoints()
        use_fk  = True
        print(f"[CSV EXPORTER] FK chain: {RIGHT_ARM_BASE} → {tip}  ({n_jnts} joints)")
    except Exception as e:
        print(f"[CSV EXPORTER] FK unavailable ({e}), writing joint angles only.")
        use_fk  = False
        n_jnts  = len(right_idx)

    # 3. Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output_csv = OUT_DIR / f"{shape_name}.csv"

    fieldnames = ['x', 'y', 'z', 'arm_id', 'arm'] + \
                 [f'j{i+1}_deg' for i in range(len(right_idx))]

    written = 0
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)

        for point in points:
            pos   = point.get('positions', [])
            r_rad = [pos[i] for i in right_idx if i < len(pos)]
            r_deg = [math.degrees(v) for v in r_rad]

            x, y, z = 0.0, 0.0, 0.0
            if use_fk:
                q = PyKDL.JntArray(n_jnts)
                for k, v in enumerate(r_rad[:n_jnts]):
                    q[k] = v
                frame = PyKDL.Frame()
                if fk.JntToCart(q, frame) >= 0:
                    x, y, z = frame.p.x(), frame.p.y(), frame.p.z()
                else:
                    continue   # skip bad rows

            writer.writerow([x, y, z, 1, 'right'] + r_deg)
            written += 1

    print(f"[CSV EXPORTER] Written {written} waypoints → {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: csv_exporter.py <yaml_file_path> <shape_name>")
        sys.exit(1)

    yaml_file_path = Path(sys.argv[1])
    shape_name     = sys.argv[2]

    if not yaml_file_path.exists():
        print(f"[CSV EXPORTER] WARNING: not found: {yaml_file_path}")
        sys.exit(1)

    process_and_write(yaml_file_path, shape_name)
    print(f"[CSV EXPORTER] Exported '{shape_name}' successfully.")
