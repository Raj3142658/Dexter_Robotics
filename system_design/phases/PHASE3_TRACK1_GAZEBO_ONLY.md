# Phase 3 Track 1: Gazebo Only

Scope for this track:

- Start Gazebo simulation from middleware.
- Stop Gazebo simulation from middleware.
- Query Gazebo session status.
- Validate from temporary UI.

Out of scope:

- RViz
- MoveIt
- controller loading

## Preconditions

```bash
cd /home/raj/Dexter_Robotics
colcon build --symlink-install
source install/setup.bash
```

## Middleware Endpoints

- `GET /ros/gazebo/status`
- `POST /ros/gazebo/start` body: `{ "gui": true|false }`
- `POST /ros/gazebo/stop`

## Launch used

- `dexter_arm_gazebo/launch/gazebo_only.launch.py`

This launch intentionally avoids controller loading, RViz, and MoveIt.

## UI Test

1. Open temporary UI `http://127.0.0.1:8090`.
2. In `Gazebo Only (Phase 3 Track 1)` panel, click `Start Gazebo Only`.
3. Verify Gazebo starts and robot is spawned.
4. Click `Refresh Gazebo Status`, confirm `running: true`.
5. Click `Stop Gazebo Only`, confirm `running: false`.