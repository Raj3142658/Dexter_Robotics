#!/usr/bin/env bash
set -euo pipefail

MW_URL="${DEXTER_MIDDLEWARE_URL:-http://127.0.0.1:8084}"
TMP_DIR="${TMPDIR:-/tmp}"
OUT_FILE="${TMP_DIR}/dexter_trajectory_smoke_$$.yaml"

echo "[1/16] Start bridge via middleware"
curl -sS -m 8 -X POST "${MW_URL}/trajectory/backend/start" >/dev/null

echo "[2/16] Submit safe generate request"
GEN_JSON="$(curl -sS -m 10 -X POST "${MW_URL}/trajectory/generate" \
  -H 'Content-Type: application/json' \
  --data '{"config":{"arm":"left","surface":{"normal":[0,0,1],"tool_tilt_deg":0},"reference_point":{"x":0.0,"y":0.0,"z":0.2},"shape":{"type":"circle","radius":0.03,"n_points":32},"execution":{"eef_step":0.01,"jump_threshold":0.0,"max_velocity_scaling":0.2,"max_acceleration_scaling":0.1,"avoid_collisions":true,"time_param_method":"totg"}}}')"

JOB_ID="$(python3 - <<'PY' "$GEN_JSON"
import json,sys
obj=json.loads(sys.argv[1])
print(obj['job_id'])
PY
)"

if [[ -z "$JOB_ID" ]]; then
  echo "Failed to parse job_id"
  exit 1
fi
echo "  - job_id: $JOB_ID"

echo "[3/16] Query job status"
JOB_JSON="$(curl -sS -m 8 "${MW_URL}/trajectory/jobs/${JOB_ID}")"
python3 - <<'PY' "$JOB_JSON"
import json,sys
obj=json.loads(sys.argv[1])
assert obj.get('status') == 'done', obj
assert obj.get('backend') == 'bridge', obj
assert obj.get('contract_version') == 'dexter.trajectory.job.v1', obj
print(f"  - status: {obj.get('status')}, waypoints: {obj.get('waypoints')}")
PY

echo "[4/16] Verify middleware job listing"
LIST_JSON="$(curl -sS -m 8 "${MW_URL}/trajectory/jobs?limit=10")"
python3 - <<'PY' "$LIST_JSON" "$JOB_ID"
import json,sys
obj=json.loads(sys.argv[1])
job_id=sys.argv[2]
jobs=obj.get('jobs', [])
assert any(j.get('job_id') == job_id for j in jobs), obj
print(f"  - listed jobs: {len(jobs)}")
PY

echo "[5/16] Download artifact"
curl -sS -m 10 "${MW_URL}/trajectory/download/${JOB_ID}" -o "$OUT_FILE"
if [[ ! -s "$OUT_FILE" ]]; then
  echo "Downloaded file is empty"
  exit 1
fi
echo "  - saved: $OUT_FILE ($(wc -c < "$OUT_FILE") bytes)"

echo "[6/16] Validate bridge artifact contract"
grep -q '^schema_version: dexter.trajectory.native.v1$' "$OUT_FILE"
grep -q '^  backend_selected: bridge$' "$OUT_FILE"
grep -q '^  source_config_sha256:' "$OUT_FILE"
echo "  - bridge schema/provenance keys verified"

echo "[7/16] Validate bridge artifact via middleware endpoint"
BRIDGE_VAL_JSON="$(curl -sS -m 10 "${MW_URL}/trajectory/artifacts/validate/${JOB_ID}")"
python3 - <<'PY' "$BRIDGE_VAL_JSON"
import json,sys
obj=json.loads(sys.argv[1])
assert obj.get('ok') is True, obj
assert obj.get('backend') == 'bridge', obj
assert obj.get('strict') is True, obj
print('  - bridge validator ok')
PY

echo "[8/16] Delete created job via middleware"
DEL_JSON="$(curl -sS -m 8 -X DELETE "${MW_URL}/trajectory/jobs/${JOB_ID}")"
python3 - <<'PY' "$DEL_JSON" "$JOB_ID"
import json,sys
obj=json.loads(sys.argv[1])
job_id=sys.argv[2]
assert obj.get('ok') is True, obj
assert obj.get('job_id') == job_id, obj
print('  - delete ok')
PY

echo "[9/16] Cleanup old jobs (keep latest 5)"
curl -sS -m 10 -X POST "${MW_URL}/trajectory/jobs/cleanup?keep_latest=5" >/dev/null

echo "[10/16] Stop bridge to validate native fallback"
curl -sS -m 8 -X POST "${MW_URL}/trajectory/backend/stop" >/dev/null

echo "[11/16] Generate while bridge is offline (native fallback)"
NATIVE_GEN_JSON="$(curl -sS -m 10 -X POST "${MW_URL}/trajectory/generate" \
  -H 'Content-Type: application/json' \
  --data '{"config":{"arm":"left","surface":{"normal":[0,0,1],"tool_tilt_deg":0},"reference_point":{"x":0.0,"y":0.0,"z":0.2},"shape":{"type":"line","length":0.08,"n_points":16},"execution":{"eef_step":0.01,"jump_threshold":0.0,"max_velocity_scaling":0.2,"max_acceleration_scaling":0.1,"avoid_collisions":true,"time_param_method":"totg"}}}')"

NATIVE_JOB_ID="$(python3 - <<'PY' "$NATIVE_GEN_JSON"
import json,sys
obj=json.loads(sys.argv[1])
print(obj['job_id'])
PY
)"
echo "  - native job_id: $NATIVE_JOB_ID"

if [[ "$NATIVE_JOB_ID" != native_* ]]; then
  echo "Expected native fallback job id prefix, got: $NATIVE_JOB_ID"
  exit 1
fi

echo "[12/16] Verify native job status via middleware"
NATIVE_JOB_JSON="$(curl -sS -m 8 "${MW_URL}/trajectory/jobs/${NATIVE_JOB_ID}")"
python3 - <<'PY' "$NATIVE_JOB_JSON"
import json,sys
obj=json.loads(sys.argv[1])
assert obj.get('status') == 'done', obj
assert obj.get('backend') == 'native', obj
assert obj.get('artifact_schema') == 'dexter.trajectory.native.v1', obj
assert obj.get('contract_version') == 'dexter.trajectory.job.v1', obj
print(f"  - status: {obj.get('status')}, backend: {obj.get('backend')}")
PY

echo "[13/16] Download native artifact"
NATIVE_OUT_FILE="${TMP_DIR}/dexter_trajectory_native_smoke_$$.yaml"
curl -sS -m 10 "${MW_URL}/trajectory/download/${NATIVE_JOB_ID}" -o "$NATIVE_OUT_FILE"
if [[ ! -s "$NATIVE_OUT_FILE" ]]; then
  echo "Native downloaded file is empty"
  exit 1
fi
echo "  - saved: $NATIVE_OUT_FILE ($(wc -c < "$NATIVE_OUT_FILE") bytes)"

echo "[14/16] Validate native artifact contract"
grep -q '^schema_version: dexter.trajectory.native.v1$' "$NATIVE_OUT_FILE"
grep -q '^  backend_selected: native$' "$NATIVE_OUT_FILE"
grep -q '^  source_config_sha256:' "$NATIVE_OUT_FILE"
echo "  - schema/provenance keys verified"

echo "[15/16] Validate native artifact via middleware endpoint"
NATIVE_VAL_JSON="$(curl -sS -m 10 "${MW_URL}/trajectory/artifacts/validate/${NATIVE_JOB_ID}")"
python3 - <<'PY' "$NATIVE_VAL_JSON"
import json,sys
obj=json.loads(sys.argv[1])
assert obj.get('ok') is True, obj
assert obj.get('backend') == 'native', obj
assert obj.get('strict') is True, obj
print('  - native validator ok')
PY

echo "[16/16] Restore bridge online"
curl -sS -m 8 -X POST "${MW_URL}/trajectory/backend/start" >/dev/null

echo "Trajectory smoke test: PASS"
