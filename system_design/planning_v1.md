# Planning V1 - Base ROS Native System + Middleware

Date: 2026-03-22
Status: Draft V1 (foundation-first)
Scope: Only the 5 base ROS-native packages and the middleware layer above them.
Out of scope for this document: dashboard UX, trajectory app architecture, utilities app architecture.

## 1. Intent

Build a robust, long-term base system that:
- preserves ROS-native execution for robot-critical paths,
- introduces a strict middleware boundary between ROS and any web framework,
- supports simulation and real hardware consistently,
- becomes the stable foundation for all higher-level modules.

## 2. Base Package Dependency Chain (authoritative)

The base chain is treated as layered and directional:

1. `dexter_arm_description`
   - Source of truth for robot model: URDF/Xacro + meshes + visualization defaults.
2. `dexter_arm_moveit_config`
   - Planning semantics constrained by robot definition.
3. `dexter_arm_control`
   - ros2_control controller definitions and low-level controller config.
4. `dexter_arm_gazebo`
   - Simulation overlay and bringup composition.
5. `dexter_arm_hardware`
   - Real hardware interface and firmware coupling.

Design rule: lower layer changes can force updates upward; never the reverse.

## 3. Core Design Principles

1. ROS-native stays authoritative for control/planning/runtime.
2. Web/control systems never directly talk to motors or firmware.
3. All non-ROS clients communicate only through middleware contracts.
4. Every command path is mode-aware: `observe`, `simulate`, `live`.
5. Safety policies execute server-side before ROS execution.
6. Execution state is centralized and observable.
7. Same command model across simulation and hardware, with policy gates.

## 4. Proposed Middleware (Bridge) Architecture

## 4.1 Logical Components

1. `Command Gateway`
- Accepts external control requests (REST/WebSocket/gRPC).
- Validates auth/session/role.
- Converts requests into internal command envelopes.

2. `Policy and Safety Engine`
- Pre-execution checks:
  - mode gate,
  - controller readiness,
  - hardware link readiness,
  - parameter bounds,
  - rate limits and lock ownership.
- Blocks unsafe transitions.

3. `ROS Orchestrator Adapter`
- Owns launch/stop/status of ROS compositions.
- Manages base bringup profiles and dependency order.
- Encapsulates ROS command execution and recovery.

4. `ROS Contract Adapter`
- Normalizes ROS topics/services/actions into stable middleware contracts.
- Hides ROS package-specific details from external clients.

5. `State and Telemetry Bus`
- Unified stream for state changes:
  - mode,
  - process status,
  - robot status,
  - health and diagnostics,
  - errors.

6. `Audit and Event Store`
- Stores who requested what, when, and outcome.
- Needed for remote operations and post-incident review.

## 4.2 Trust Boundary

- Trusted zone: ROS graph + hardware interface + middleware policy engine.
- Semi-trusted zone: control API endpoints.
- Untrusted zone: browsers and remote clients.

Hard rule: untrusted zone must not issue raw ROS/motor operations directly.

## 5. Canonical Runtime Modes

1. `observe`
- Read-only telemetry and diagnostics.
- No control commands.

2. `simulate`
- Allows simulation launches and planned motion execution in Gazebo/MoveIt.
- No live hardware actuation.

3. `live`
- Hardware control enabled only after explicit arming and readiness checks.
- Strictest policy profile.

Mode transitions must be explicit state-machine transitions, not ad-hoc commands.

## 6. Base Bringup Profiles (middleware-managed)

1. `profile:model_view`
- launches description-only model visualization path.

2. `profile:planning_demo`
- description + moveit_config + control (as needed for planning demo).

3. `profile:simulation_full`
- description + moveit_config + control + gazebo full bringup.

4. `profile:hardware_full`
- description + moveit_config + control + hardware interface + micro-ROS readiness gate.

Profiles are first-class middleware objects, not shell scripts.

## 7. State Machine (base system)

`offline -> bootstrapping -> ready_observe -> ready_simulate or ready_live -> active -> degraded -> emergency_stop`

Required transition guards:
- `bootstrapping -> ready_live`: hardware transport + controller checks pass.
- `active -> degraded`: heartbeat loss, controller fault, or bridge error.
- `any -> emergency_stop`: manual stop or critical fault.

## 8. Middleware Contract Model (framework-agnostic)

Use stable command envelope for all control requests:

```json
{
  "request_id": "uuid",
  "timestamp": "ISO-8601",
  "actor": "operator-id",
  "mode": "observe|simulate|live",
  "intent": "launch_profile|stop_profile|execute_plan|set_param|arm|disarm",
  "target": "profile:simulation_full",
  "payload": {},
  "constraints": {
    "dry_run": false,
    "timeout_ms": 15000
  }
}
```

Execution response model:

```json
{
  "request_id": "uuid",
  "accepted": true,
  "decision": "allowed|blocked",
  "reason": "policy_passed",
  "execution_ref": "exec-uuid",
  "state": "queued|running|failed|completed"
}
```

## 9. Optimized Folder Structure Proposal (base-first)

Keep existing five packages in `src/` with minimal internal disruption.
Add a clean middleware area and architecture metadata:

```text
Dexter-arm-Robotics/
  src/
    dexter_arm_description/
    dexter_arm_moveit_config/
    dexter_arm_control/
    dexter_arm_gazebo/
    dexter_arm_hardware/

  middleware/
    command_gateway/
      contracts/
      auth/
      api/
    policy_engine/
      rules/
      validators/
      state_machine/
    ros_orchestrator/
      profiles/
      launch_adapter/
      process_supervisor/
    ros_contract_adapter/
      services/
      actions/
      topics/
      serializers/
    telemetry_bus/
      publishers/
      subscriptions/
      stream_api/
    audit/
      events/
      storage/

  system_design/
    planning_v1.md
    decisions/
      (future ADR files)
```

Notes:
- This is a design structure; implementation language is intentionally not fixed yet.
- `middleware/` is the new stable seam between ROS-native and any UI/control framework.

## 10. Base Interface Mapping (high level)

For the five packages, middleware should expose these normalized capabilities:

1. Description domain
- get current robot model metadata
- get active model variant
- reload model definition (controlled)

2. Planning domain
- check planning stack readiness
- request planning session availability
- fetch planning diagnostics

3. Control domain
- list controllers
- activate/deactivate controllers
- controller health and latency

4. Simulation domain
- start/stop simulation profile
- simulation health and clock state

5. Hardware domain
- hardware session readiness
- transport status (serial/wifi + micro-ROS)
- hardware command path health

## 11. Non-Negotiable Reliability/Safety Requirements

1. Command idempotency for launch/stop operations.
2. Single active operator lock in `live` mode.
3. Heartbeat watchdog for live control sessions.
4. Structured error taxonomy (policy, orchestration, ROS, hardware).
5. Graceful degradation and deterministic fallback behavior.
6. Emergency stop path independent from UI availability.

## 12. What We Finalize Next (before UI and file mapping)

1. Final mode/state machine diagram with exact guards.
2. Base bringup profile definitions and dependency ordering.
3. Policy ruleset V1 for `observe/simulate/live`.
4. Canonical contract schema V1 (`intent`, `target`, `payload`).
5. Failure handling strategy:
- link loss,
- controller crash,
- move_group unavailable,
- micro-ROS session drop.

## 13. Design Tracking Convention

All architecture outputs from now on are stored under `system_design/`.
Naming convention:
- `planning_v1.md`, `planning_v2.md`, ...
- decision records under `system_design/decisions/adr_00x_<title>.md`

This file is the baseline for further brainstorming.
