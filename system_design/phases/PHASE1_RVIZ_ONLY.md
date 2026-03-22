# Phase 1: RViz-Only Wiring

Scope for this phase:

- Start RViz with `dexter_arm_description` model launch.
- Stop RViz cleanly from middleware.
- Query RViz process state from middleware.
- Validate end-to-end calls from temporary UI.

Out of scope:

- MoveIt
- ros2_control controllers
- gazebo
- real hardware interaction

## Middleware Endpoints

- `GET /ros/rviz/status`
- `POST /ros/rviz/start` body: `{ "gui": true|false }`
- `POST /ros/rviz/stop`

## Preconditions

Run middleware from a terminal where ROS workspace is sourced:

```bash
cd /home/raj/Dexter_Robotics
source install/setup.bash
cd /home/raj/Dexter_Robotics/src/dexter_middleware
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Quick Test

1. Open temporary UI and click `Start RViz`.
2. Confirm RViz opens with model view.
3. Click `Refresh RViz Status` and verify `running: true`.
4. Click `Stop RViz` and verify `running: false`.
