import json
import os
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


def _write_job_output(job_id: str, config: dict[str, Any]) -> Path:
    output_path = JOBS_DIR / f"{job_id}.yaml"

    # Keep output human-readable and deterministic without introducing PyYAML dependency.
    body = {
        "bridge": "trajectory_bridge_compat",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": config,
    }
    output_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return output_path


def _job_from_disk(job_id: str) -> dict[str, Any] | None:
    output_file = JOBS_DIR / f"{job_id}.yaml"
    if not output_file.exists():
        return None

    return {
        "job_id": job_id,
        "status": "done",
        "output_file": str(output_file),
        "duration": 0.05,
        "waypoints": None,
        "fraction": 100.0,
        "shape_summary": "unknown",
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
    output_file = _write_job_output(job_id, config)

    job = {
        "job_id": job_id,
        "status": "done",
        "output_file": str(output_file),
        "duration": 0.05,
        "waypoints": waypoints,
        "fraction": 100.0,
        "shape_summary": _shape_summary(shape),
        "created_at": time.time(),
    }
    _register_job(job)

    return {
        "job_id": job_id,
        "status": "queued",
        "output_file": str(output_file),
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
