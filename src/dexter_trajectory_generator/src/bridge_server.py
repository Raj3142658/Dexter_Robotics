#!/usr/bin/env python3
"""
DEXTER Bridge Server
====================
FastAPI server that sits between the HTML workspace analyzer and the ROS2
trajectory generator node.

Flow:
    HTML  →  POST /generate  →  bridge_server.py  →  writes shape_config.yaml
                                                   →  ros2 run ... trajectory_node
                                                   →  streams live logs back
                                                   →  returns output YAML path

    HTML  →  GET  /status          →  last job status
    HTML  →  GET  /download/{file} →  download generated YAML
    HTML  →  GET  /jobs            →  job history

Run:
    python3 bridge_server.py
    # or with custom ports / paths:
    python3 bridge_server.py --port 8765 --output-dir ~/trajectories
"""

import asyncio
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

# ─── CONFIG ──────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT_DIR = Path.home() / "dexter_trajectories"
DEFAULT_PORT       = 8765

# The ROS2 package and launch file to invoke
ROS2_PACKAGE      = "dexter_trajectory_generator"
ROS2_LAUNCH_FILE  = "trajectory_node.launch.py"

# dexter_arm_ws setup script — provides robot_description + MoveIt config
DEXTER_ARM_WS_SETUP = Path.home() / "dexter_arm_ws" / "install" / "setup.bash"

# ─── PYDANTIC MODELS (what the HTML POSTs) ───────────────────────────────────

class SurfaceConfig(BaseModel):
    normal:        list[float] = [0.0, 0.0, 1.0]
    tool_tilt_deg: float       = 0.0

class ReferencePoint(BaseModel):
    x: float
    y: float
    z: float

class ShapeConfig(BaseModel):
    type:     str
    # Circle
    radius:           Optional[float] = None
    # Line
    length:           Optional[float] = None
    direction_u:      Optional[float] = None
    direction_v:      Optional[float] = None
    # Rectangle
    width:            Optional[float] = None
    height:           Optional[float] = None
    # Arc
    start_angle_deg:  Optional[float] = None
    end_angle_deg:    Optional[float] = None
    # Zigzag
    zag_width:        Optional[float] = None
    steps:            Optional[int]   = None
    # Spiral
    inner_radius:     Optional[float] = None
    outer_radius:     Optional[float] = None
    turns:            Optional[float] = None
    # Common
    n_points:         Optional[int]   = None

class ExecutionParams(BaseModel):
    eef_step:                    float  = 0.005
    jump_threshold:              float  = 0.0
    max_velocity_scaling:        float  = 0.3
    max_acceleration_scaling:    float  = 0.1
    avoid_collisions:            bool   = True
    time_param_method:           str    = "totg"

class GenerateRequest(BaseModel):
    arm:             str            = "left"
    surface:         SurfaceConfig  = Field(default_factory=SurfaceConfig)
    reference_point: ReferencePoint
    shape:           ShapeConfig
    execution:       ExecutionParams = Field(default_factory=ExecutionParams)
    description:     str            = ""
    output_filename: Optional[str]  = None   # optional custom name


# ─── JOB STORE (in-memory) ───────────────────────────────────────────────────

jobs: dict[str, dict] = {}   # job_id → {status, config_path, output_path, log, started, finished}


# ─── APP ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="DEXTER Bridge Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # HTML file opens from file:// so we need wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = DEFAULT_OUTPUT_DIR   # overridden by CLI arg at startup


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.get("/ping")
def ping():
    """Health check — HTML polls this to show server status dot."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/jobs")
def list_jobs():
    """Returns all jobs, newest first."""
    return sorted(jobs.values(), key=lambda j: j["started"], reverse=True)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, f"Job {job_id} not found")
    return jobs[job_id]


@app.get("/download/{job_id}")
def download_trajectory(job_id: str):
    """Download the generated YAML file."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(400, f"Job not complete (status={job['status']})")
    path = job.get("output_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "Output file not found")
    return FileResponse(
        path,
        media_type="application/x-yaml",
        filename=Path(path).name,
    )


@app.post("/generate")
async def generate(req: GenerateRequest):
    """
    Main endpoint. Accepts the full config from the HTML tool,
    writes shape_config.yaml, launches the ROS2 node, streams logs.
    Returns job_id immediately — poll /jobs/{job_id} for status.
    """
    job_id = str(uuid.uuid4())[:8]
    started = datetime.now().isoformat()

    # ── Build shape_config dict (same structure as shape_config.yaml) ─────────
    shape_dict = {k: v for k, v in req.shape.model_dump().items() if v is not None}

    config = {
        "arm": req.arm,
        "surface": {
            "normal":        req.surface.normal,
            "tool_tilt_deg": req.surface.tool_tilt_deg,
        },
        "reference_point": {
            "x": req.reference_point.x,
            "y": req.reference_point.y,
            "z": req.reference_point.z,
        },
        "shape": shape_dict,
    }

    # ── Write temp config YAML ────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config_path = OUTPUT_DIR / f"config_{job_id}.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # ── Determine output filename ─────────────────────────────────────────────
    if req.output_filename:
        fname = req.output_filename
        if not fname.endswith(".yaml"):
            fname += ".yaml"
    else:
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        shape = req.shape.type
        arm   = req.arm
        fname = f"dexter_{arm}_{shape}_{ts}.yaml"

    output_path = OUTPUT_DIR / fname
    desc = req.description or f"{req.shape.type.title()} trajectory — {req.arm} arm"

    # ── Register job ──────────────────────────────────────────────────────────
    jobs[job_id] = {
        "job_id":      job_id,
        "status":      "queued",
        "config":      config,       # echo back for debug
        "config_path": str(config_path),
        "output_path": str(output_path),
        "output_file": fname,
        "description": desc,
        "log":         [],
        "started":     started,
        "finished":    None,
        "fraction":    None,
        "waypoints":   None,
        "duration":    None,
    }

    # ── Build ros2 launch command ─────────────────────────────────────────────
    ex = req.execution
    cmd = [
        "bash", "-c",
        f"source /opt/ros/jazzy/setup.bash && "
        f"source {DEXTER_ARM_WS_SETUP} && "
        f"source {Path.home() / 'install' / 'setup.bash'} && "
        f"ros2 launch {ROS2_PACKAGE} {ROS2_LAUNCH_FILE} "
        f"config_file:={config_path} "
        f"output_file:={output_path} "
        f"description:='{desc}' "
        f"eef_step:={ex.eef_step} "
        f"jump_threshold:={ex.jump_threshold} "
        f"max_velocity_scaling:={ex.max_velocity_scaling} "
        f"max_acceleration_scaling:={ex.max_acceleration_scaling} "
        f"avoid_collisions:={str(ex.avoid_collisions).lower()} "
        f"time_param_method:={ex.time_param_method}"
    ]

    # ── Run async so the HTTP response returns immediately ────────────────────
    asyncio.create_task(_run_node(job_id, cmd))

    return {
        "job_id":      job_id,
        "status":      "queued",
        "output_file": fname,
        "message":     "Job queued. Poll /jobs/{job_id} for progress.",
    }


@app.get("/stream/{job_id}")
async def stream_logs(job_id: str):
    """
    Server-Sent Events stream of live log lines for a job.
    The HTML EventSource connects here to show live terminal output.
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    async def event_generator():
        last_idx = 0
        while True:
            job  = jobs.get(job_id, {})
            logs = job.get("log", [])
            while last_idx < len(logs):
                line = logs[last_idx]
                yield f"data: {json.dumps({'line': line, 'status': job['status']})}\n\n"
                last_idx += 1
            if job.get("status") in ("done", "error"):
                yield f"data: {json.dumps({'line': '__DONE__', 'status': job['status'], 'job': job})}\n\n"
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ─── ASYNC NODE RUNNER ────────────────────────────────────────────────────────

async def _run_node(job_id: str, cmd: list[str]):
    """Runs the ROS2 node as a subprocess, captures stdout/stderr line by line."""
    job = jobs[job_id]
    job["status"] = "running"
    job["log"].append(f"[BRIDGE] Starting: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").rstrip()
            job["log"].append(line)

            # Parse key metrics from node output
            if "Cartesian path:" in line and "%" in line:
                try:
                    pct = float(line.split("%")[0].split()[-1])
                    job["fraction"] = pct
                except Exception:
                    pass
            if "waypoints," in line:
                try:
                    job["waypoints"] = int(line.split("waypoints")[0].split("(")[-1].strip())
                except Exception:
                    pass
            if "Trajectory saved" in line:
                job["status"] = "done"

        await proc.wait()

        if proc.returncode != 0 and job["status"] != "done":
            job["status"] = "error"
            job["log"].append(f"[BRIDGE] Node exited with code {proc.returncode}")
        else:
            job["status"] = "done"

        # Read final YAML to extract duration + waypoint_count
        out_path = Path(job["output_path"])
        if out_path.exists():
            with open(out_path) as f:
                traj = yaml.safe_load(f)
            job["duration"]  = traj.get("duration")
            job["waypoints"] = traj.get("waypoint_count")

    except Exception as e:
        job["status"] = "error"
        job["log"].append(f"[BRIDGE] Exception: {e}")

    job["finished"] = datetime.now().isoformat()


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def main():
    global OUTPUT_DIR
    parser = argparse.ArgumentParser(description="DEXTER Bridge Server")
    parser.add_argument("--port",       type=int,  default=DEFAULT_PORT,
                        help="HTTP port (default 8765)")
    parser.add_argument("--output-dir", type=str,  default=str(DEFAULT_OUTPUT_DIR),
                        help="Directory to save generated trajectories")
    args = parser.parse_args()

    OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n  DEXTER Bridge Server")
    print(f"  ─────────────────────────────────────────")
    print(f"  Listening on  http://localhost:{args.port}")
    print(f"  Outputs →     {OUTPUT_DIR}")
    print(f"  Health:       http://localhost:{args.port}/ping")
    print(f"  Job history:  http://localhost:{args.port}/jobs")
    print(f"  ─────────────────────────────────────────\n")

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
