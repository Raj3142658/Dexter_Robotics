import json
import os
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

app = FastAPI(title="Dexter Trajectory Bridge Compat", version="0.1.0")

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "trajectory_bridge"
JOBS_DIR = RUNTIME_DIR / "jobs"
JOB_INDEX_FILE = RUNTIME_DIR / "jobs_index.json"
ARTIFACT_SCHEMA_VERSION = "dexter.trajectory.native.v1"
JOB_CONTRACT_VERSION = "dexter.trajectory.job.v1"

JOBS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job registry for bridge lifetime.
JOBS: dict[str, dict[str, Any]] = {}


def _save_jobs_index() -> None:
    payload = {
        "saved_at": time.time(),
        "jobs": JOBS,
    }
    JOB_INDEX_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_jobs_index() -> None:
    if not JOB_INDEX_FILE.exists():
        return
    try:
        payload = json.loads(JOB_INDEX_FILE.read_text(encoding="utf-8"))
        jobs = payload.get("jobs")
        if isinstance(jobs, dict):
            for job_id, job in jobs.items():
                if not isinstance(job, dict):
                    continue
                output = job.get("output_file")
                if isinstance(output, str) and Path(output).exists():
                    JOBS[job_id] = job
    except Exception:
        # Corrupt index should not block bridge startup.
        pass


def _register_job(job: dict[str, Any]) -> None:
    JOBS[str(job["job_id"])] = job
    _save_jobs_index()


def _delete_job(job_id: str) -> dict[str, Any]:
    removed = JOBS.pop(job_id, None)
    output_file = JOBS_DIR / f"{job_id}.yaml"
    meta_file = JOBS_DIR / f"{job_id}.meta.json"
    file_deleted = False
    meta_deleted = False
    if output_file.exists():
        output_file.unlink()
        file_deleted = True
    if meta_file.exists():
        meta_file.unlink()
        meta_deleted = True
    _save_jobs_index()
    return {
        "removed_from_index": removed is not None,
        "file_deleted": file_deleted,
        "meta_deleted": meta_deleted,
    }


def _safe_waypoint_count(shape: dict[str, Any]) -> int:
    try:
        n = int(shape.get("n_points", 100))
        return max(4, min(5000, n))
    except Exception:
        return 100


def _shape_summary(shape: dict[str, Any]) -> str:
    shape_type = str(shape.get("type", "unknown"))
    keys = sorted(k for k in shape.keys() if k != "type")
    return f"type={shape_type}; params={','.join(keys)}"


def _iso_utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/")
        if value and all(ch in safe for ch in value):
            return value
        return json.dumps(value)
    return json.dumps(value)


def _yaml_lines(value: Any, indent: int = 0) -> list[str]:
    space = " " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(val, (dict, list)):
                out.append(f"{space}{key}:")
                out.extend(_yaml_lines(val, indent + 2))
            else:
                out.append(f"{space}{key}: {_yaml_scalar(val)}")
        if not value:
            out.append(f"{space}{{}}")
        return out

    if isinstance(value, list):
        if not value:
            out.append(f"{space}[]")
            return out
        for item in value:
            if isinstance(item, (dict, list)):
                out.append(f"{space}-")
                out.extend(_yaml_lines(item, indent + 2))
            else:
                out.append(f"{space}- {_yaml_scalar(item)}")
        return out

    out.append(f"{space}{_yaml_scalar(value)}")
    return out


def _render_yaml_document(value: dict[str, Any]) -> str:
    body = "\n".join(_yaml_lines(value))
    return f"---\n{body}\n"


def _artifact_payload(job_id: str, config: dict[str, Any], shape: dict[str, Any], waypoints: int) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "kind": "dexter_trajectory_plan",
        "job": {
            "id": job_id,
            "backend": "bridge",
            "created_at": _iso_utc_now(),
        },
        "provenance": {
            "bridge": {
                "service": app.title,
                "version": app.version,
            },
            "backend_selected": "bridge",
            "source_config_sha256": _sha256_json(config),
        },
        "request": {
            "shape": {
                "type": str(shape.get("type", "unknown")),
            },
            "config": config,
        },
        "trajectory": {
            "waypoint_count": waypoints,
            "shape_summary": _shape_summary(shape),
        },
    }


def _write_job_output(job_id: str, config: dict[str, Any], shape: dict[str, Any], waypoints: int) -> Path:
    output_path = JOBS_DIR / f"{job_id}.yaml"
    body = _artifact_payload(job_id, config, shape, waypoints)
    output_path.write_text(_render_yaml_document(body), encoding="utf-8")
    return output_path


def _job_from_disk(job_id: str) -> dict[str, Any] | None:
    output_file = JOBS_DIR / f"{job_id}.yaml"
    if not output_file.exists():
        return None

    meta_file = JOBS_DIR / f"{job_id}.meta.json"
    if meta_file.exists():
        try:
            payload = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("job_id", job_id)
                payload.setdefault("output_file", str(output_file))
                payload.setdefault("status", "done")
                payload.setdefault("backend", "bridge")
                payload.setdefault("artifact_schema", ARTIFACT_SCHEMA_VERSION)
                payload.setdefault("artifact_format", "yaml")
                payload.setdefault("contract_version", JOB_CONTRACT_VERSION)
                return payload
        except Exception:
            pass

    return {
        "job_id": job_id,
        "status": "done",
        "output_file": str(output_file),
        "duration": 0.05,
        "waypoints": None,
        "fraction": 100.0,
        "shape_summary": "unknown",
        "backend": "bridge",
        "artifact_schema": ARTIFACT_SCHEMA_VERSION,
        "artifact_format": "yaml",
        "contract_version": JOB_CONTRACT_VERSION,
        "created_at": output_file.stat().st_mtime,
    }


_load_jobs_index()


@app.get("/ping")
async def ping() -> dict[str, Any]:
    return {"ok": True, "service": "trajectory_bridge_compat"}


@app.post("/generate")
async def generate(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or not config:
        raise HTTPException(status_code=400, detail="Missing generation config")

    shape = config.get("shape") if isinstance(config.get("shape"), dict) else {}
    waypoints = _safe_waypoint_count(shape)

    job_id = uuid.uuid4().hex[:12]
    output_file = _write_job_output(job_id, config, shape, waypoints)

    job = {
        "job_id": job_id,
        "status": "done",
        "output_file": str(output_file),
        "duration": 0.05,
        "waypoints": waypoints,
        "fraction": 100.0,
        "shape_summary": _shape_summary(shape),
        "backend": "bridge",
        "artifact_schema": ARTIFACT_SCHEMA_VERSION,
        "artifact_format": "yaml",
        "contract_version": JOB_CONTRACT_VERSION,
        "created_at": time.time(),
    }
    (JOBS_DIR / f"{job_id}.meta.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    _register_job(job)

    return {
        "job_id": job_id,
        "status": "queued",
        "output_file": str(output_file),
        "backend": "bridge",
        "artifact_schema": ARTIFACT_SCHEMA_VERSION,
        "artifact_format": "yaml",
        "contract_version": JOB_CONTRACT_VERSION,
    }


@app.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        # Fallback for restarts: infer from output file if it exists.
        disk_job = _job_from_disk(job_id)
        if not disk_job:
            raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
        _register_job(disk_job)
        job = disk_job

    return job


@app.get("/jobs")
async def list_jobs(limit: int = 20) -> dict[str, Any]:
    bounded = max(1, min(200, int(limit)))
    jobs = sorted(JOBS.values(), key=lambda j: float(j.get("created_at", 0.0)), reverse=True)
    return {
        "ok": True,
        "count": len(jobs),
        "jobs": jobs[:bounded],
    }


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str) -> dict[str, Any]:
    result = _delete_job(job_id)
    if not result["removed_from_index"] and not result["file_deleted"]:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")

    return {
        "ok": True,
        "job_id": job_id,
        **result,
    }


@app.post("/jobs/cleanup")
async def cleanup_jobs(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    keep_latest = 20
    if isinstance(payload, dict) and "keep_latest" in payload:
        try:
            keep_latest = max(0, min(1000, int(payload.get("keep_latest", 20))))
        except Exception:
            keep_latest = 20

    jobs_sorted = sorted(JOBS.values(), key=lambda j: float(j.get("created_at", 0.0)), reverse=True)
    keep_ids = {str(j.get("job_id")) for j in jobs_sorted[:keep_latest]}

    removed_ids: list[str] = []
    for job in jobs_sorted[keep_latest:]:
        job_id = str(job.get("job_id"))
        if not job_id:
            continue
        _delete_job(job_id)
        removed_ids.append(job_id)

    # Also prune orphan files that are not in active index.
    for artifact in JOBS_DIR.glob("*.yaml"):
        if artifact.stem not in keep_ids and artifact.stem not in {j.get("job_id") for j in JOBS.values()}:
            artifact.unlink(missing_ok=True)

    _save_jobs_index()
    return {
        "ok": True,
        "kept": keep_latest,
        "removed_count": len(removed_ids),
        "removed_job_ids": removed_ids,
        "remaining": len(JOBS),
    }


@app.get("/download/{job_id}")
async def download(job_id: str) -> Response:
    job = JOBS.get(job_id)
    output_path = Path(job["output_file"]) if job else (JOBS_DIR / f"{job_id}.yaml")
    if not output_path.exists():
        raise HTTPException(status_code=404, detail=f"Output not found for job_id: {job_id}")

    content = output_path.read_bytes()
    headers = {
        "Content-Disposition": f"attachment; filename={output_path.name}",
    }
    return Response(content=content, media_type="application/x-yaml", headers=headers)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("DEXTER_TRAJECTORY_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("DEXTER_TRAJECTORY_BRIDGE_PORT", "8765"))
    uvicorn.run("trajectory_bridge_compat:app", host=host, port=port)
