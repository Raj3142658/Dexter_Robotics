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

JOBS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job registry for bridge lifetime.
JOBS: dict[str, dict[str, Any]] = {}


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
    JOBS[job_id] = job

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
        output_file = JOBS_DIR / f"{job_id}.yaml"
        if output_file.exists():
            job = {
                "job_id": job_id,
                "status": "done",
                "output_file": str(output_file),
                "duration": 0.05,
                "waypoints": None,
                "fraction": 100.0,
            }
        else:
            raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")

    return job


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
