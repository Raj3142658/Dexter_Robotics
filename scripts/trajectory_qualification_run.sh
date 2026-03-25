#!/usr/bin/env bash
set -euo pipefail

MW_URL="${DEXTER_MIDDLEWARE_URL:-http://127.0.0.1:8080}"
OUT_DIR="${DEXTER_QUAL_OUT_DIR:-/tmp}"
STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${OUT_DIR}/trajectory_qualification_${STAMP}.json"
REQ_FILE="${OUT_DIR}/trajectory_qualification_req_${STAMP}.json"

jq_bin="$(command -v jq || true)"
if [[ -z "${jq_bin}" ]]; then
  echo "jq is required for this script" >&2
  exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0
RESULTS_JSON="[]"
LAST_RUN_ID=""
LAST_JOB_ID=""
LAST_BACKEND=""
EXEC_NAME="qualification_execute_${STAMP}"

record_result() {
  local id="$1"
  local status="$2"
  local detail="$3"
  local row
  row="$(jq -n --arg id "$id" --arg status "$status" --arg detail "$detail" '{id:$id,status:$status,detail:$detail}')"
  RESULTS_JSON="$(jq -c --argjson row "$row" '. + [$row]' <<<"$RESULTS_JSON")"
  if [[ "$status" == "PASS" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

step() {
  local id="$1"
  local desc="$2"
  shift 2
  echo "[$id] $desc"
  if "$@"; then
    record_result "$id" "PASS" "$desc"
  else
    record_result "$id" "FAIL" "$desc"
  fi
}

check_health() {
  local out
  out="$(curl -m 8 -sS "${MW_URL}/health")"
  [[ "$(jq -r '.ok // false' <<<"$out")" == "true" ]]
}

prepare_robot_state() {
  curl -m 8 -sS -X POST "${MW_URL}/connect" >/dev/null
  curl -m 8 -sS -X POST "${MW_URL}/enable" >/dev/null
}

force_native_backend() {
  curl -m 8 -sS -X POST "${MW_URL}/trajectory/backend/stop" >/dev/null || true
}

restore_bridge_backend() {
  curl -m 8 -sS -X POST "${MW_URL}/trajectory/backend/start" >/dev/null || true
}

create_artifact_job() {
  cat >"$REQ_FILE" <<'JSON'
{
  "config": {
    "trajectory_name": "qualification_smoke",
    "arm": "left",
    "surface": {"normal": [0, 0, 1], "tool_tilt_deg": 0},
    "reference_point": {"x": -0.05, "y": 0.0, "z": 0.24},
    "shape": {"type": "line", "length": 0.05, "n_points": 2},
    "execution": {
      "eef_step": 0.01,
      "jump_threshold": 0.0,
      "max_velocity_scaling": 0.2,
      "max_acceleration_scaling": 0.1,
      "avoid_collisions": true,
      "time_param_method": "totg"
    },
    "joint_trajectory": {
      "joint_names": [
        "j1l", "j2l", "j3l", "j4l", "j5l", "j6l", "gripper_l_servo",
        "j1r", "j2r", "j3r", "j4r", "j5r", "j6r", "gripper_r_servo"
      ],
      "points": [
        {"time_from_start": 0.0, "positions": [0,0,0,0,0,0,0,0,0,0,0,0,0,0]},
        {"time_from_start": 1.0, "positions": [0.1,0.05,0,0,0,0,0,0.1,0.05,0,0,0,0,0]}
      ]
    }
  }
}
JSON

  local out
  out="$(curl -m 10 -sS -X POST "${MW_URL}/trajectory/generate" -H 'Content-Type: application/json' --data @"$REQ_FILE")"
  LAST_JOB_ID="$(jq -r '.job_id // ""' <<<"$out")"
  LAST_BACKEND="$(jq -r '.backend // ""' <<<"$out")"
  [[ -n "$LAST_JOB_ID" ]]
}

ensure_no_active_trajectory() {
  curl -m 8 -sS -X POST "${MW_URL}/trajectory/stop" >/dev/null || true
  sleep 0.4
}

execute_and_capture_run_id() {
  local out
  local run_id
  local poll_id
  local i

  ensure_no_active_trajectory

  out="$(curl -m 10 -sS -X POST "${MW_URL}/trajectory/execute?artifact_job_id=${LAST_JOB_ID}&artifact_strict=true" -H 'Content-Type: application/json' --data "{\"name\":\"${EXEC_NAME}\"}")"
  if [[ "$(jq -r '.execution_guard.ok // false' <<<"$out")" != "true" ]]; then
    return 1
  fi

  run_id="$(jq -r '.execution_run_id // .run_id // ""' <<<"$out")"
  if [[ -n "$run_id" && "$run_id" != "null" ]]; then
    LAST_RUN_ID="$run_id"
    return 0
  fi

  for i in $(seq 1 15); do
    poll_id="$(curl -m 8 -sS "${MW_URL}/trajectory/execute/reports?limit=30" | jq -r --arg job "$LAST_JOB_ID" --arg name "$EXEC_NAME" 'first(.reports[]? | select(.artifact_job_id == $job and .name == $name) | .run_id) // ""')"
    if [[ -n "$poll_id" ]]; then
      LAST_RUN_ID="$poll_id"
      return 0
    fi
    sleep 0.4
  done

  [[ -n "$LAST_RUN_ID" ]]
}

check_report_list_contains_run() {
  local out
  out="$(curl -m 8 -sS "${MW_URL}/trajectory/execute/reports?limit=20")"
  [[ "$(jq -r --arg rid "$LAST_RUN_ID" 'any(.reports[]?; .run_id == $rid)' <<<"$out")" == "true" ]]
}

check_report_detail() {
  local out
  out="$(curl -m 8 -sS "${MW_URL}/trajectory/execute/reports/${LAST_RUN_ID}")"
  [[ "$(jq -r '.status // ""' <<<"$out")" =~ ^(completed|failed|cancelled)$ ]]
  [[ "$(jq -r '.artifact.job_id // ""' <<<"$out")" == "$LAST_JOB_ID" ]]
}

check_precheck_endpoint() {
  local out
  out="$(curl -m 8 -sS "${MW_URL}/trajectory/execute/precheck?artifact_job_id=${LAST_JOB_ID}")"
  [[ "$(jq -r '.artifact.ok // false' <<<"$out")" == "true" ]]
  [[ "$(jq -r '.artifact.job_id // ""' <<<"$out")" == "$LAST_JOB_ID" ]]
  [[ "$(jq -r '.artifact.backend // ""' <<<"$out")" == "$LAST_BACKEND" ]]
}

# Run sequence
step "S1" "Middleware health" check_health
step "S2" "Prepare robot connected/enabled state" prepare_robot_state
force_native_backend
step "S3" "Create native artifact job" create_artifact_job
step "S4" "Execute artifact and capture run id" execute_and_capture_run_id
sleep 1.3
step "S5" "Precheck endpoint returns artifact metadata" check_precheck_endpoint
step "S6" "Report list contains latest run" check_report_list_contains_run
step "S7" "Report detail fields are valid" check_report_detail
restore_bridge_backend

SUMMARY="$(jq -n \
  --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg mw_url "$MW_URL" \
  --arg run_id "$LAST_RUN_ID" \
  --arg job_id "$LAST_JOB_ID" \
  --argjson pass_count "$PASS_COUNT" \
  --argjson fail_count "$FAIL_COUNT" \
  --argjson results "$RESULTS_JSON" \
  '{
    generated_at: $generated_at,
    middleware_url: $mw_url,
    artifact_job_id: $job_id,
    execution_run_id: $run_id,
    pass_count: $pass_count,
    fail_count: $fail_count,
    results: $results
  }')"

echo "$SUMMARY" >"$REPORT_FILE"
echo "Qualification report: $REPORT_FILE"
echo "$SUMMARY" | jq '{pass_count, fail_count, artifact_job_id, execution_run_id}'

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 2
fi
