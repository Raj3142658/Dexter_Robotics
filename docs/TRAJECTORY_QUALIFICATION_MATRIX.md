# Trajectory Qualification Matrix

This matrix defines the acceptance path from middleware integrity to hardware reliability.

## Scope

- System under test: `src/dexter_middleware` trajectory execute path
- Artifact format: `dexter.trajectory.execute14.v1`
- Runtime modes: `dry_run`, `ros2_topic`, `udp_json`

## Exit Criteria

Release readiness requires:

1. All `S` (software) tests pass.
2. All `I` (integration) tests pass in hardware session.
3. All `H` (hardware-in-loop) tests pass on real arm.
4. No unresolved safety-critical defects (stop behavior, stale-link abort, limit enforcement).

## Test Matrix

| ID | Layer | Test | Command / Method | Pass Condition |
|---|---|---|---|---|
| S1 | Software | Middleware health | `GET /health` | `ok=true` |
| S2 | Software | Execute precheck API | `GET /trajectory/execute/precheck` | Response schema valid; readiness reasons present |
| S3 | Software | Artifact runner starts | `POST /trajectory/execute?artifact_job_id=<id>` in `dry_run` | `trajectory.running=true` initially |
| S4 | Software | Report ID issued | Execute call response | `execution_run_id` populated for artifact-backed run |
| S5 | Software | Report list endpoint | `GET /trajectory/execute/reports` | At least one recent report row |
| S6 | Software | Report detail endpoint | `GET /trajectory/execute/reports/{run_id}` | Status, timing, artifact metadata present |
| S7 | Software | Joint limit validation | Run artifact with out-of-range point | Execute request rejected (422) |
| S8 | Software | Step delta validation | Run artifact with very large step jump | Execute request rejected (422) |
| S9 | Software | Transport safety gate | Start middleware with non-dry transport and no hardware session | Execute rejected with safety error |
| I1 | Integration | Hardware bootstrap | `POST /ros/hardware/start` | `agent_running=true`, `launch_running=true` |
| I2 | Integration | ros2_topic publish path | Set `DEXTER_TRAJECTORY_EXECUTE_TRANSPORT=ros2_topic`, execute artifact | Run completes, no stale-session failures |
| I3 | Integration | Health watchdog abort | Interrupt hardware session during execute | Run aborts; report status=`failed` with watchdog reason |
| I4 | Integration | Stop endpoint latency | `POST /trajectory/stop` during active run | Run transitions to stopped quickly and safely |
| I5 | Integration | Report evidence | Inspect run report JSON | Includes transport mode, result stats, and timestamps |
| H1 | Hardware | Low-speed path tracking | Run line/circle profile at conservative speed | Smooth physical motion, no jerks/stalls |
| H2 | Hardware | Mid-speed repeatability | 20 repeated executions | No limit faults; endpoint repeatability acceptable |
| H3 | Hardware | Link interruption safety | Disable WiFi/agent during run | Controlled abort, no runaway behavior |
| H4 | Hardware | Timeout/freeze safety | Stop command source and wait for firmware timeout | Arm freezes safely (no sudden jump) |
| H5 | Hardware | Endurance | 30-60 min mixed trajectories | No watchdog leak, no cumulative drift causing safety trips |

## Required Artifacts for Sign-off

- Latest software test report JSON from qualification script
- At least 5 execution report JSON files from `.runtime/trajectory_native/execution_reports/`
- Hardware test log sheet with operator initials and timestamp
- Any failure triage tickets linked to specific run IDs

## Failure Severity

- Blocker: uncontrolled motion, stop failure, limit bypass, stale-link not aborted
- Major: repeated intermittent execution failure with same scenario
- Minor: non-safety telemetry/report formatting issues

## Suggested Order

1. Run software qualification script (`scripts/trajectory_qualification_run.sh`)
2. Run integration checks with hardware session active
3. Run hardware-in-loop matrix H1-H5
4. Freeze configuration and capture final baseline reports
