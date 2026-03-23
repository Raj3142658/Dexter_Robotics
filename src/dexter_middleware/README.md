# Dexter Middleware (MVP)

Temporary middleware for flow validation before full architecture expansion.

## Run

```bash
cd /home/raj/Dexter_Robotics/src/dexter_middleware
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Core Endpoints

- `GET /health`
- `GET /status`
- `POST /connect`
- `POST /disconnect`
- `POST /enable`
- `POST /disable`
- `POST /jog/joint`
- `POST /trajectory/execute`
- `POST /trajectory/pause`
- `POST /trajectory/resume`
- `POST /trajectory/stop`
- `WS /ws/events`

## ROS Session Endpoints

- `GET /ros/rviz/status`
- `POST /ros/rviz/start`
- `POST /ros/rviz/stop`
- `GET /ros/moveit/status`
- `POST /ros/moveit/start`
- `POST /ros/moveit/stop`
- `GET /ros/gazebo/status`
- `POST /ros/gazebo/start`
- `POST /ros/gazebo/stop`
- `GET /ros/full-stack/status`
- `POST /ros/full-stack/start`
- `POST /ros/full-stack/stop`
- `GET /ros/hardware/status`
- `POST /ros/hardware/start`
- `POST /ros/hardware/stop`

## Trajectory Backend Ops

- `GET /trajectory/backend/status`
- `POST /trajectory/backend/start`
- `POST /trajectory/backend/stop`
- `POST /trajectory/generate`
- `GET /trajectory/jobs`
- `GET /trajectory/jobs/{job_id}`
- `DELETE /trajectory/jobs/{job_id}`
- `POST /trajectory/jobs/cleanup`
- `GET /trajectory/download/{job_id}`

Backend selection:

- `DEXTER_TRAJECTORY_BACKEND_MODE=auto` (default): bridge when online, native fallback when bridge is offline.
- `DEXTER_TRAJECTORY_BACKEND_MODE=bridge`: force bridge-only generation.
- `DEXTER_TRAJECTORY_BACKEND_MODE=native`: force middleware native generation.

Native artifact contract (`backend=native`):

- Download endpoint remains `GET /trajectory/download/{job_id}`.
- Artifact format is YAML with `schema_version: dexter.trajectory.native.v1`.
- Includes provenance fields (`backend_selected`, `source_config_sha256`, bridge status at generation time).
- Job status payload includes `artifact_schema`, `artifact_format`, and `path_length_m`.

Middleware job payload contract normalization:

- `POST /trajectory/generate`, `GET /trajectory/jobs`, and `GET /trajectory/jobs/{job_id}` return `contract_version: dexter.trajectory.job.v1`.
- Middleware always returns `backend` and artifact metadata keys, including bridge compatibility defaults.

Bridge artifact parity:

- The local compatibility bridge now emits schema-tagged YAML artifacts using `schema_version: dexter.trajectory.native.v1` with bridge provenance.
- This keeps downloaded artifact structure aligned between bridge and native generation paths.

Bridge helper scripts:

```bash
/home/raj/Dexter_Robotics/scripts/start_trajectory_bridge.sh
/home/raj/Dexter_Robotics/scripts/stop_trajectory_bridge.sh
/home/raj/Dexter_Robotics/scripts/bridge_status.sh
```

End-to-end smoke test:

```bash
/home/raj/Dexter_Robotics/scripts/trajectory_smoke_test.sh
```
