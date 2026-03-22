# Phase 2: RViz + MoveIt Demo Wiring

Scope for this phase:

- Start MoveIt demo launch from middleware.
- Stop MoveIt demo launch cleanly from middleware.
- Query MoveIt launch status from middleware.
- Drive lifecycle from temporary UI.

Out of scope:

- gazebo simulation control
- real hardware actuation
- trajectory execution on real controllers

## Prerequisites

```bash
cd /home/raj/Dexter_Robotics
colcon build --symlink-install
source install/setup.bash
```

## Middleware endpoints

- `GET /ros/moveit/status`
- `POST /ros/moveit/start` body: `{ "use_sim_time": true|false }`
- `POST /ros/moveit/stop`

## Run middleware

```bash
cd /home/raj/Dexter_Robotics/src/dexter_middleware
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## UI quick test

1. Open `http://127.0.0.1:8090`.
2. In MoveIt panel, click `Start MoveIt Demo`.
3. Verify RViz opens with MoveIt plugin panels and robot model.
4. Click `Refresh MoveIt Status`, verify `running: true`.
5. Click `Stop MoveIt Demo`, verify `running: false`.

## Notes

- If start fails, API returns `503` with environment guidance.
- `disconnect` now also stops active MoveIt and RViz launch sessions.
