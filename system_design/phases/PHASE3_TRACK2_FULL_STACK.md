# Phase 3 Track 2: Full Simulation Stack

Scope for this track:

- Start full simulation stack from middleware using `gazebo_bringup.launch.py`.
- Full stack includes: Gazebo + RViz + MoveIt + arm/gripper controllers.
- Stop full stack cleanly from middleware.
- Query full stack status from middleware.

## Middleware endpoints

- `GET /ros/full-stack/status`
- `POST /ros/full-stack/start` body:
  - `{ "use_rviz": true|false, "load_moveit": true|false }`
- `POST /ros/full-stack/stop`

## Notes

- `full-stack/start` stops standalone Gazebo-only, RViz-only, and MoveIt-only sessions first to avoid launch conflicts.
- Controller loading is handled by `dexter_arm_gazebo/launch/gazebo_bringup.launch.py`.

## UI Test

1. Open `http://127.0.0.1:8090`.
2. In `Phase 3 Track 2` panel, click `Start Full Stack`.
3. Verify Gazebo starts, RViz starts, MoveIt loads, controllers spawn.
4. Click `Refresh Full Stack Status`, confirm `running: true`.
5. Click `Stop Full Stack`, confirm `running: false`.
