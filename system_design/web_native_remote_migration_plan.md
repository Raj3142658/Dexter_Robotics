# Web-Native ROS Visualization Migration Plan (Production)

Date: 2026-03-22
Status: Approved planning draft
Scope: Production architecture for remote server deployment with browser/mobile UI, using web-native ROS visualization and simulation access.

## 1. Goal

Deliver a production-ready remote robotics stack where:
- ROS-native compute remains on server.
- Web/mobile UI consumes ROS data through middleware.
- RViz-like visualization is web-native.
- Gazebo access is web-native-compatible (preferred) with migration-safe options.

## 2. Final Direction (Locked)

1. Web-native ROS visualization is the default product path.
2. Core ROS web stack (rosbridge, roslibjs, ROS-compatible middleware contracts) is foundational.
3. Gazebo browser client capability is included in architecture and may be delivered in staged form.
4. No direct desktop screen streaming as primary product feature.

## 3. Target Production Architecture

```text
Remote Server (ROS Native)
  ROS 2 packages (description, control, moveit, gazebo, hardware)
  Middleware API (FastAPI + adapters)
  rosbridge_suite (WebSocket ROS bridge)
  Telemetry + Audit + Policy services

Client (Web/Mobile)
  React/TypeScript app
  3D scene layer (URDF/TF/joints/markers)
  Simulation panels and control views
  Secure auth/session + role-based operations
```

Data flow:
1. UI requests go to middleware command API.
2. Middleware policy engine validates command.
3. Middleware executes via ROS adapters.
4. ROS state/telemetry is normalized and sent back to UI.

## 4. Phase Plan

### Phase 0: Foundations (1-2 weeks)

Deliverables:
- Lock API contract style (REST + WS events).
- Lock environment strategy (dev, staging, prod).
- Lock security baseline (JWT/session, TLS, role model).
- Define topic/service/action contract inventory.

Exit criteria:
- Signed API schema v1.
- Role policy matrix approved.
- Remote deployment checklist drafted.

### Phase 1: Web Robot Viewer (2-3 weeks)

Deliverables:
- Render robot model in browser from URDF assets.
- Live joint animation via `/joint_states`.
- TF frame updates and basic overlays.
- Read-only status dashboards.

Tech path:
- rosbridge_suite + roslibjs or middleware WebSocket relay.
- 3D rendering in web client.

Exit criteria:
- Browser viewer matches basic RViz model behavior for robot pose/joint movement.
- No direct ROS calls from UI bypassing middleware policy boundary.

### Phase 2: Web Simulation Visibility (2-4 weeks)

Deliverables:
- Gazebo simulation state surfaced in UI (world, entities, robot state, sensors).
- Simulation control endpoints (start, stop, reset, pause) through middleware.
- Multi-panel web simulation dashboard.

Notes:
- Prefer data-native rendering where feasible.
- If a temporary compatibility bridge is needed for specific Gazebo visuals, keep it behind middleware and plan deprecation.

Exit criteria:
- Remote users can observe and operate simulation workflows from browser without server desktop access.

### Phase 3: Planning + Operations (2-4 weeks)

Deliverables:
- Planning state and task progress in UI.
- Command queue with audit trail and safety gates.
- Structured logs, metrics, and failure diagnostics.

Exit criteria:
- End-to-end remote operation path validated in staging.
- Incident review trail complete (who, what, when, result).

### Phase 4: Hardening for Production (2-3 weeks)

Deliverables:
- HA and restart behavior for middleware services.
- Rate limits, command throttling, and backpressure.
- E2E tests for safety-critical flows.
- SLOs for latency and event delivery.

Exit criteria:
- Production readiness checklist passed.
- Controlled pilot rollout approved.

## 5. Component Responsibilities

1. Middleware Command Gateway
- Accepts UI commands.
- Enforces auth, role, request schema.

2. Policy/Safety Engine
- Mode checks (`observe/simulate/live`).
- Bounds and precondition checks.
- Blocks unsafe transitions.

3. ROS Adapter Layer
- ROS topics/services/actions mapping.
- Launch profile orchestration.

4. State Normalization Service
- Converts ROS-native payloads to stable API payloads.
- Provides versioned event schemas.

5. Web Visualization Layer
- URDF/TF/joint rendering.
- Marker and sensor overlays.
- Simulation entity visualization.

6. Audit + Observability
- Structured event logs.
- Metrics and tracing for critical commands.

## 6. Remote Server Migration Strategy

1. Stage in local lab first.
- Same contract, same auth model, local network.

2. Deploy staging server with secure ingress.
- TLS certs, reverse proxy, firewall policy.

3. Move ROS + middleware services to managed process runtime.
- systemd or container orchestration.

4. Introduce remote users in read-only mode first.
- Then promote to simulation control.
- Then hardware control with strict safety policy.

## 7. Security and Safety Baseline

- Authentication required for all non-health endpoints.
- Role separation: viewer, operator, admin.
- Write commands require explicit operator role and mode gate.
- Safety interlocks enforced server-side, never client-side only.
- Immutable audit records for command path.

## 8. Testing Strategy

1. Contract tests
- API schema compatibility tests per version.

2. Integration tests
- Middleware to ROS adapter tests against test graph.

3. UI E2E tests
- Viewer updates, simulation controls, fault states.

4. Fault injection
- Bridge disconnects, delayed topics, dropped events.

## 9. Risks and Mitigations

1. Risk: Event volume overload
- Mitigation: topic filtering, throttling, delta updates.

2. Risk: Browser performance under dense scenes
- Mitigation: LOD controls, selective layers, sampling.

3. Risk: Contract drift between ROS and UI
- Mitigation: versioned schemas + CI contract checks.

4. Risk: Unsafe command propagation
- Mitigation: server-side policy engine + approval gates.

## 10. Definition of Done (Production Migration)

Migration is complete when:
- Remote users can monitor robot/simulation from web/mobile with low-latency updates.
- Simulation operations are performed from web UI through middleware safely.
- Audit, observability, and rollback paths are verified.
- No UI feature depends on server desktop GUI access.
