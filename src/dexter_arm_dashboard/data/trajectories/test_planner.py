import yaml
with open("/home/raj/dexter_arm_ws/src/dexter_arm_dashboard/data/trajectories/dexter_right_circle_20260310_000131.yaml") as f:
    d = yaml.safe_load(f)
print(d.get('waypoint_count', 'no waypoints'))
