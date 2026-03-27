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
- `POST /trajectory/import`
- `GET /trajectory/jobs`
- `GET /trajectory/jobs/{job_id}`
- `DELETE /trajectory/jobs/{job_id}`
- `POST /trajectory/jobs/cleanup`
- `GET /trajectory/download/{job_id}`
- `GET /trajectory/artifacts/validate/{job_id}`
- `GET /trajectory/execute/precheck`
- `GET /trajectory/execute/reports`
- `GET /trajectory/execute/reports/{run_id}`

Backend selection:

- `DEXTER_TRAJECTORY_BACKEND_MODE=auto` (default): bridge when online, native fallback when bridge is offline.
- `DEXTER_TRAJECTORY_BACKEND_MODE=bridge`: force bridge-only generation.
- `DEXTER_TRAJECTORY_BACKEND_MODE=native`: force middleware native generation.

ROS-backed generation (recommended for real hardware):

- `DEXTER_TRAJECTORY_GENERATION_MODE=ros` (default): use `dexter_arm_trajectory` ROS services to compute joint trajectories via MoveIt, then import into native execute14.
- Requires `ros2 launch dexter_arm_trajectory trajectory_system.launch.py` running (or equivalent) so `/shape_trajectory/generate` + `/trajectory_manager/save` are available.
- `DEXTER_TRAJECTORY_GENERATION_MODE=native`: keep the placeholder XY waypoint generator (plan-only, no joint points).
- `DEXTER_TRAJECTORY_ROS_TIMEOUT_SEC` (default `15.0`): service wait/response timeout.
  - Note: the legacy ROS shape generator operates in the **XZ plane** (y=0). Use `reference_point.x` + `reference_point.z` for positioning.

Teach/repeat mode:

- `DEXTER_TRAJECTORY_TEACH_MODE=ros` (default): route teach capture/compile through `trajectory_manager` services and import the compiled YAML.
- If ROS services are offline, teach endpoints return HTTP 503 with a hint to start the trajectory system.

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

Strict artifact validation:

- `GET /trajectory/artifacts/validate/{job_id}` validates required schema/provenance/trajectory keys.
- Default `strict=true` returns HTTP 422 when required keys are missing.

Execution artifact gate:

- `POST /trajectory/execute` now supports optional query params:
- `artifact_job_id=<job_id>`: require artifact validation for this job before execution starts.
- `artifact_strict=true|false` (default `true`): strict mode enforces validation failure as HTTP error.

Execution precheck dry-run:

- `GET /trajectory/execute/precheck` returns readiness and guard diagnostics without starting motion.
- Supports the same optional query params: `artifact_job_id` and `artifact_strict`.

Native execute artifact runtime:

- When `POST /trajectory/execute` is called with `artifact_job_id` for a native job, middleware now loads the job's `execute.yaml` and runs time-based interpolation from artifact points.
- If no valid artifact is selected, middleware falls back to the legacy simulated duration flow.

Import JointTrajectory YAML:

- `POST /trajectory/import` accepts `{ "source_path": "/abs/path/to/joint_trajectory.yaml", "name": "optional_name" }`.
- Creates a **native job** with both plan + execute14 artifacts.
- Enables legacy teach/shape YAMLs to run through the new execute14 executor.

Execution transport environment variables:

- `DEXTER_TRAJECTORY_EXECUTE_TRANSPORT`:
- `dry_run` (default): validate and run timing loop without sending hardware packets.
- `udp_json`: send waypoint packets as JSON over UDP.
- `ros2_topic`: publish `std_msgs/Float64MultiArray` commands to ESP topic path.
- `ros2_action`: send `FollowJointTrajectory` goals to ros2_control controllers (Gazebo or hardware).
- `DEXTER_TRAJECTORY_EXECUTE_HZ` (default `50`): control loop frequency.
- `DEXTER_TRAJECTORY_EXECUTE_UDP_HOST` (default `127.0.0.1`): UDP target host.
- `DEXTER_TRAJECTORY_EXECUTE_UDP_PORT` (default `5005`): UDP target port.
- `DEXTER_TRAJECTORY_EXECUTE_UDP_TIMEOUT_SEC` (default `0.1`): UDP read timeout.
- `DEXTER_TRAJECTORY_EXECUTE_UDP_REQUIRE_ACK` (default `false`): fail execute when ack is missing or invalid.
- `DEXTER_TRAJECTORY_EXECUTE_UDP_RETRIES` (default `0`): resend count for transient UDP failures.
- `DEXTER_TRAJECTORY_EXECUTE_EMIT_STOP` (default `true`): emit `trajectory_stop` packet when execution completes/fails/cancels.
- `DEXTER_TRAJECTORY_EXECUTE_MAX_STEP_RAD` (default `0.6`): max allowed waypoint-to-waypoint joint delta for artifact validation.
- `DEXTER_TRAJECTORY_EXECUTE_LIMIT_MARGIN_RAD` (default `0.05`): tolerance margin used during joint-limit validation.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_TOPIC` (default `/esp32/joint_commands`): target topic for `ros2_topic` transport.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_QUEUE_DEPTH` (default `10`): ROS publisher queue depth.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_HEALTH_CHECK` (default `true`): subscribe to health topic and evaluate link status.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_HEALTH_TOPIC` (default `/esp32/link_health`): health topic path.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_REQUIRE_HEALTH` (default `true`): require fresh health before each publish.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_HEALTH_TIMEOUT_SEC` (default `1.0`): stale timeout for health freshness.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_ACTION_LEFT` (default `left_arm_controller`): controller name for left arm action.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_ACTION_RIGHT` (default `right_arm_controller`): controller name for right arm action.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_ACTION_LEFT_GRIPPER` (default `left_arm_gripper`): controller name for left gripper action.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_ACTION_RIGHT_GRIPPER` (default `right_arm_gripper`): controller name for right gripper action.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_ACTION_INCLUDE_GRIPPERS` (default `true`): include gripper goals in `ros2_action` transport.
- `DEXTER_TRAJECTORY_EXECUTE_ROS_ACTION_GOAL_TOLERANCE_SEC` (default `1.0`): action goal time tolerance.
- `DEXTER_TRAJECTORY_EXECUTION_WATCHDOG_ENABLED` (default `true`): enforce runtime session watchdog during execute.
- `DEXTER_TRAJECTORY_EXECUTION_WATCHDOG_INTERVAL_SEC` (default `0.25`): watchdog check cadence.

Transport safety gate:

- Non-dry-run transport modes are rejected unless the hardware session is active.
- This prevents accidental live packet streaming while only simulation/full-stack state is active.

ESP firmware compatibility note:

- Middleware now includes monotonically increasing `seq` in each transport packet.
- In `ros2_topic` mode, middleware publishes command vectors as 15 values: 14 joint targets + trailing sequence number.
- This aligns with ESP stale-sequence protections used in `esp32_firmware_wireless.ino` command handling.

Execution run audit reports:

- Artifact-backed executions now persist run reports under:
- `.runtime/trajectory_native/execution_reports/exec_<id>.json`
- Reports include: status (`completed|failed|cancelled`), timing, context, transport, artifact metadata, executor stats, and error detail (if any).
- `POST /trajectory/execute` returns `execution_run_id` for artifact-backed runs.
- Use `GET /trajectory/execute/reports` and `GET /trajectory/execute/reports/{run_id}` to inspect outcomes during QA/hardware validation.

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
