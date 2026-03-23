import asyncio
import json
import math
import os
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .models import CleanupRequest, EventMessage, ExecuteTrajectoryRequest, FirmwareUploadStartRequest, FullStackStartRequest, GazeboStartRequest, HardwareBootstrapStartRequest, JogJointRequest, MoveitStartRequest, RvizStartRequest, TrajectoryGenerateRequest, TrajectorySafetyCheckRequest, TrajectorySafetyDefaultReferenceRequest, TrajectorySafetyLimitsRequest
from .services.full_stack_service import FullStackService
from .services.gazebo_service import GazeboService
from .services.hardware_bootstrap_service import HardwareBootstrapService
from .services.moveit_service import MoveitService
from .services.rviz_service import RvizService
from .state import RobotState

app = FastAPI(title="Dexter Middleware", version="0.1.0")
REPO_ROOT = Path(__file__).resolve().parents[3]
STOP_SCRIPT = REPO_ROOT / "scripts" / "stop_control_center.sh"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

state = RobotState()
clients: set[WebSocket] = set()
state_lock = asyncio.Lock()
rviz_lock = asyncio.Lock()
rviz_service = RvizService()
moveit_lock = asyncio.Lock()
moveit_service = MoveitService()
gazebo_lock = asyncio.Lock()
gazebo_service = GazeboService()
full_stack_lock = asyncio.Lock()
full_stack_service = FullStackService()
hardware_lock = asyncio.Lock()
hardware_service = HardwareBootstrapService()
hardware_bootstrap_task: asyncio.Task | None = None
middleware_started_at = time.time()
firmware_lock = asyncio.Lock()
firmware_upload_task: asyncio.Task | None = None
firmware_upload_state: dict = {
    "running": False,
    "success": False,
    "message": "Idle",
    "logs": [],
    "started_at": None,
    "finished_at": None,
    "command": None,
    "filename": None,
}

LAUNCH_TRANSITION_TIMEOUT_SEC = 10.0
LAUNCH_TRANSITION_COOLDOWN_SEC = 2.0
FIRMWARE_DIR = REPO_ROOT / "src" / "dexter_arm_hardware" / "firmware"
SAFETY_CONFIG_FILE = REPO_ROOT / "src" / "dexter_middleware" / "config" / "safety_zones.json"
BRIDGE_BASE_URL = os.getenv("DEXTER_TRAJECTORY_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")

DEFAULT_TRAJECTORY_SAFETY: dict[str, Any] = {
    "defaults": {
        "reach_soft_ratio": 0.95,
        "supported_surfaces": ["XY"],
    },
    "left": {
        "shoulder": [-0.185, 0.0, 0.486],
        "reach_m": 0.444,
        "x_range": [-0.55, 0.15],
        "y_range": [-0.35, 0.35],
        "z_range": [0.10, 0.85],
        "reach_soft_ratio": 0.95,
    },
    "right": {
        "shoulder": [0.185, 0.0, 0.486],
        "reach_m": 0.444,
        "x_range": [-0.15, 0.55],
        "y_range": [-0.35, 0.35],
        "z_range": [0.10, 0.85],
        "reach_soft_ratio": 0.95,
    },
}


def _load_trajectory_safety() -> dict[str, Any]:
    if SAFETY_CONFIG_FILE.exists():
        try:
            return json.loads(SAFETY_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_TRAJECTORY_SAFETY


TRAJECTORY_SAFETY = _load_trajectory_safety()


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return min(max_val, max(min_val, value))


def _bridge_json_request(method: str, path: str, payload: dict | None = None, timeout_sec: float = 10.0) -> dict:
    url = f"{BRIDGE_BASE_URL}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, method=method.upper(), data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=detail or f"Bridge HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail=f"Bridge unreachable at {BRIDGE_BASE_URL}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Bridge returned invalid JSON for {path}") from exc


def _bridge_binary_request(path: str, timeout_sec: float = 20.0) -> tuple[bytes, str, str | None]:
    url = f"{BRIDGE_BASE_URL}{path}"
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read()
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            disposition = resp.headers.get("Content-Disposition")
            return body, content_type, disposition
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=detail or f"Bridge HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail=f"Bridge unreachable at {BRIDGE_BASE_URL}: {exc.reason}") from exc


def _bridge_is_online(timeout_sec: float = 1.5) -> bool:
    req = urllib.request.Request(url=f"{BRIDGE_BASE_URL}/ping", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return int(getattr(resp, "status", 0)) == 200
    except Exception:
        return False


def _bridge_probe(timeout_sec: float = 1.5) -> tuple[bool, str]:
    req = urllib.request.Request(url=f"{BRIDGE_BASE_URL}/ping", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = int(getattr(resp, "status", 0))
            if status == 200:
                return True, "ready"
            return False, f"Bridge responded with HTTP {status}"
    except urllib.error.HTTPError as exc:
        return False, f"Bridge HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"Bridge unreachable: {exc.reason}"
    except Exception as exc:
        return False, f"Bridge probe failed: {exc}"


async def broadcast(event: EventMessage) -> None:
    if not clients:
        return
    payload = event.model_dump_json()
    stale = []
    for ws in clients:
        try:
            await ws.send_text(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        clients.discard(ws)


async def _shutdown_control_center() -> None:
    # Delay ensures API response reaches the browser before services are terminated.
    await asyncio.sleep(0.7)
    cmd = ["/bin/bash", "-lc", f"{STOP_SCRIPT} --from-api"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def snapshot() -> dict:
    rviz_status = rviz_service.status()
    moveit_status = moveit_service.status()
    gazebo_status = gazebo_service.status()
    full_stack_status = full_stack_service.status()
    hardware_status = hardware_service.status()
    return {
        "connected": state.connected,
        "enabled": state.enabled,
        "joints_deg": state.joints_deg,
        "trajectory": {
            "name": state.trajectory_name,
            "progress": round(state.trajectory_progress, 3),
            "running": state.trajectory_running,
            "paused": state.trajectory_paused,
        },
        "rviz": {
            "running": rviz_status.running,
            "pid": rviz_status.pid,
            "command": rviz_status.command,
        },
        "moveit": {
            "running": moveit_status.running,
            "pid": moveit_status.pid,
            "command": moveit_status.command,
        },
        "gazebo": {
            "running": gazebo_status.running,
            "pid": gazebo_status.pid,
            "command": gazebo_status.command,
        },
        "full_stack": {
            "running": full_stack_status.running,
            "pid": full_stack_status.pid,
            "command": full_stack_status.command,
        },
        "hardware": hardware_status,
    }


def _hardware_bootstrap_in_progress() -> bool:
    return hardware_bootstrap_task is not None and not hardware_bootstrap_task.done()


def _launch_conflicts() -> dict[str, bool]:
    rviz_running = rviz_service.status().running
    moveit_running = moveit_service.status().running
    gazebo_running = gazebo_service.status().running
    full_stack_running = full_stack_service.status().running
    hardware_status = hardware_service.status()
    hardware_running = bool(hardware_status.get("agent_running") or hardware_status.get("launch_running"))
    return {
        "rviz": rviz_running,
        "moveit": moveit_running,
        "gazebo": gazebo_running,
        "full_stack": full_stack_running,
        "hardware": hardware_running,
        "hardware_bootstrap": _hardware_bootstrap_in_progress(),
    }


async def _wait_for_sessions_stopped(session_names: list[str], timeout_sec: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        conflicts = _launch_conflicts()
        still_running = [name for name in session_names if conflicts.get(name, False)]
        if not still_running:
            return
        await asyncio.sleep(0.25)

    conflicts = _launch_conflicts()
    still_running = [name for name in session_names if conflicts.get(name, False)]
    raise HTTPException(
        status_code=409,
        detail=(
            "Launch transition timed out while waiting for previous sessions to stop: "
            + ", ".join(still_running)
        ),
    )


async def _preempt_simulation_for(target_name: str, include_full_stack: bool) -> None:
    stopped: list[str] = []

    async with moveit_lock:
        if moveit_service.status().running:
            moveit_service.stop()
            stopped.append("moveit")

    async with rviz_lock:
        if rviz_service.status().running:
            rviz_service.stop()
            stopped.append("rviz")

    async with gazebo_lock:
        if gazebo_service.status().running:
            gazebo_service.stop()
            stopped.append("gazebo")

    if include_full_stack:
        async with full_stack_lock:
            if full_stack_service.status().running:
                full_stack_service.stop()
                stopped.append("full_stack")

    if stopped:
        await broadcast(
            EventMessage(
                type="launch_transition",
                message=f"Preparing {target_name}: stopped conflicting sessions ({', '.join(stopped)})",
                payload=snapshot(),
            )
        )

    wait_for = ["moveit", "rviz", "gazebo"]
    if include_full_stack:
        wait_for.append("full_stack")

    await _wait_for_sessions_stopped(wait_for, timeout_sec=LAUNCH_TRANSITION_TIMEOUT_SEC)
    await asyncio.sleep(LAUNCH_TRANSITION_COOLDOWN_SEC)


def _append_firmware_log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    firmware_upload_state["logs"].append(f"[{ts}] {line}")
    firmware_upload_state["logs"] = firmware_upload_state["logs"][-300:]


def _arm_safety_zone(arm: str) -> dict[str, Any]:
    arm_key = arm.lower().strip()
    zone = TRAJECTORY_SAFETY.get(arm_key)
    if not isinstance(zone, dict):
        raise HTTPException(status_code=400, detail=f"Unknown arm '{arm}'. Use left/right.")
    return zone


def _shape_param_limits(shape: str, available: float) -> dict[str, dict[str, float]]:
    # Conservative caps keep the arm away from hard boundaries and singular zones.
    a = max(0.02, available)
    return {
        "circle": {
            "radius": {"min": 0.01, "max": min(0.20, a * 0.5), "step": 0.005},
        },
        "line": {
            "length": {"min": 0.02, "max": min(0.35, a * 1.2), "step": 0.005},
        },
        "rectangle": {
            "width": {"min": 0.02, "max": min(0.30, a * 1.0), "step": 0.005},
            "height": {"min": 0.02, "max": min(0.25, a * 1.0), "step": 0.005},
        },
        "arc": {
            "radius": {"min": 0.02, "max": min(0.20, a * 0.5), "step": 0.005},
            "angle": {"min": 30.0, "max": 330.0, "step": 5.0},
        },
        "zigzag": {
            "length": {"min": 0.04, "max": min(0.30, a * 1.2), "step": 0.005},
            "width": {"min": 0.01, "max": min(0.12, a * 0.4), "step": 0.005},
            "steps": {"min": 2.0, "max": 10.0, "step": 1.0},
        },
        "spiral": {
            "r1": {"min": 0.01, "max": min(0.10, a * 0.35), "step": 0.005},
            "r2": {"min": 0.04, "max": min(0.20, a * 0.55), "step": 0.005},
            "turns": {"min": 1.0, "max": 5.0, "step": 0.5},
        },
    }.get(shape, {})


def _xy_shape_waypoints(shape: str, params: dict[str, float], ref_x: float, ref_y: float, ref_z: float, n: int = 60) -> list[tuple[float, float, float]]:
    pts2d: list[tuple[float, float]] = []
    if shape == "circle":
        r = float(params.get("radius", 0.08))
        for i in range(n + 1):
            a = (i / n) * math.pi * 2.0
            pts2d.append((r * math.cos(a), r * math.sin(a)))
    elif shape == "line":
        l = float(params.get("length", 0.15))
        for i in range(n + 1):
            pts2d.append((-l / 2.0 + (l * i / n), 0.0))
    elif shape == "rectangle":
        w = float(params.get("width", 0.12))
        h = float(params.get("height", 0.08))
        corners = [(-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0), (w / 2.0, h / 2.0), (-w / 2.0, h / 2.0), (-w / 2.0, -h / 2.0)]
        for s in range(4):
            for i in range(15):
                t = i / 15.0
                x = corners[s][0] * (1.0 - t) + corners[s + 1][0] * t
                y = corners[s][1] * (1.0 - t) + corners[s + 1][1] * t
                pts2d.append((x, y))
    elif shape == "arc":
        r = float(params.get("radius", 0.10))
        ang = math.radians(float(params.get("angle", 180.0)))
        for i in range(n + 1):
            a = -ang / 2.0 + (i / n) * ang
            pts2d.append((r * math.cos(a), r * math.sin(a)))
    elif shape == "zigzag":
        l = float(params.get("length", 0.15))
        w = float(params.get("width", 0.04))
        steps = int(round(float(params.get("steps", 4.0))))
        raw: list[tuple[float, float]] = []
        for i in range(steps + 1):
            x = -l / 2.0 + (l * i / max(steps, 1))
            y = -w / 2.0 if i % 2 == 0 else w / 2.0
            raw.append((x, y))
        for i in range(len(raw) - 1):
            for j in range(12):
                t = j / 12.0
                x = raw[i][0] * (1.0 - t) + raw[i + 1][0] * t
                y = raw[i][1] * (1.0 - t) + raw[i + 1][1] * t
                pts2d.append((x, y))
        pts2d.append(raw[-1])
    elif shape == "spiral":
        r1 = float(params.get("r1", 0.03))
        r2 = float(params.get("r2", 0.10))
        turns = float(params.get("turns", 2.0))
        for i in range(n + 1):
            t = i / n
            r = r1 + (r2 - r1) * t
            a = t * turns * math.pi * 2.0
            pts2d.append((r * math.cos(a), r * math.sin(a)))

    return [(ref_x + u, ref_y + v, ref_z) for (u, v) in pts2d]


def _validate_xy_shape_request(arm: str, shape: str, params: dict[str, float], ref_x: float, ref_y: float, ref_z: float) -> list[str]:
    zone = _arm_safety_zone(arm)
    x_lo, x_hi = float(zone["x_range"][0]), float(zone["x_range"][1])
    y_lo, y_hi = float(zone["y_range"][0]), float(zone["y_range"][1])
    z_lo, z_hi = float(zone["z_range"][0]), float(zone["z_range"][1])
    sx, sy, sz = [float(v) for v in zone["shoulder"]]
    reach = float(zone["reach_m"])
    ratio = float(zone.get("reach_soft_ratio", TRAJECTORY_SAFETY.get("defaults", {}).get("reach_soft_ratio", 0.95)))

    violations: list[str] = []
    points = _xy_shape_waypoints(shape, params, ref_x, ref_y, ref_z)
    if not points:
        return [f"Unsupported shape '{shape}'"]

    eps = 1e-6
    for idx, (px, py, pz) in enumerate(points):
        if px < (x_lo - eps) or px > (x_hi + eps):
            violations.append(f"Waypoint {idx}: x={px:.3f} out of range [{x_lo:.3f}, {x_hi:.3f}]")
            break
        if py < (y_lo - eps) or py > (y_hi + eps):
            violations.append(f"Waypoint {idx}: y={py:.3f} out of range [{y_lo:.3f}, {y_hi:.3f}]")
            break
        if pz < (z_lo - eps) or pz > (z_hi + eps):
            violations.append(f"Waypoint {idx}: z={pz:.3f} out of range [{z_lo:.3f}, {z_hi:.3f}]")
            break
        dist = math.sqrt((px - sx) ** 2 + (py - sy) ** 2 + (pz - sz) ** 2)
        if dist > (reach * ratio + eps):
            violations.append(
                f"Waypoint {idx}: distance {dist:.3f} exceeds {ratio*100:.0f}% reach ({reach:.3f}m)"
            )
            break
    return violations


def _default_safe_reference(arm: str) -> tuple[float, float, float]:
    """Return a conservative reference point close to each arm's stable mid-workspace."""
    zone = _arm_safety_zone(arm)
    sx, sy, _ = [float(v) for v in zone["shoulder"]]
    x_lo, x_hi = float(zone["x_range"][0]), float(zone["x_range"][1])
    y_lo, y_hi = float(zone["y_range"][0]), float(zone["y_range"][1])
    z_lo, z_hi = float(zone["z_range"][0]), float(zone["z_range"][1])
    reach = float(zone["reach_m"])
    ratio = float(zone.get("reach_soft_ratio", TRAJECTORY_SAFETY.get("defaults", {}).get("reach_soft_ratio", 0.95)))

    inward_sign = 1.0 if sx < 0.0 else -1.0
    target_xy = min(0.16, max(0.08, reach * ratio * 0.35))

    rx = _clamp(sx + inward_sign * target_xy, x_lo, x_hi)
    ry = _clamp(sy, y_lo, y_hi)
    rz = _clamp(0.22, z_lo, z_hi)
    return rx, ry, rz


def _shape_params_from_config(shape_type: str, shape_cfg: dict[str, Any]) -> dict[str, float]:
    """Normalize UI/bridge shape keys into safety-check parameter keys."""
    shape = shape_type.lower().strip()
    out: dict[str, float] = {}

    def _num(key: str, default: float = 0.0) -> float:
        try:
            return float(shape_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    if shape == "circle":
        out["radius"] = _num("radius", 0.08)
    elif shape == "line":
        out["length"] = _num("length", 0.15)
    elif shape == "rectangle":
        out["width"] = _num("width", 0.12)
        out["height"] = _num("height", 0.08)
    elif shape == "arc":
        out["radius"] = _num("radius", 0.10)
        if "angle" in shape_cfg:
            out["angle"] = _num("angle", 180.0)
        else:
            start = _num("start_angle_deg", -90.0)
            end = _num("end_angle_deg", 90.0)
            out["angle"] = abs(end - start)
    elif shape == "zigzag":
        out["length"] = _num("length", 0.15)
        out["width"] = _num("zag_width", _num("width", 0.04))
        out["steps"] = _num("steps", 4.0)
    elif shape == "spiral":
        out["r1"] = _num("inner_radius", _num("r1", 0.03))
        out["r2"] = _num("outer_radius", _num("r2", 0.10))
        out["turns"] = _num("turns", 2.0)

    return out


def _preflight_shape_generation_config(config: dict[str, Any]) -> tuple[str, str, dict[str, float], float, float, float, list[str]]:
    """Extract generation fields and return (arm, surface, params, ref_x, ref_y, ref_z, violations)."""
    arm = str(config.get("arm", "left")).lower().strip()
    surface_cfg = config.get("surface") if isinstance(config.get("surface"), dict) else {}
    normal = surface_cfg.get("normal", [0, 0, 1])
    surface = "XY"
    if isinstance(normal, list) and len(normal) >= 3:
        try:
            nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
            if abs(nx) > 0.5 and abs(ny) < 0.5 and abs(nz) < 0.5:
                surface = "YZ"
            elif abs(ny) > 0.5 and abs(nx) < 0.5 and abs(nz) < 0.5:
                surface = "XZ"
            elif abs(nz) > 0.5 and abs(nx) < 0.5 and abs(ny) < 0.5:
                surface = "XY"
        except (TypeError, ValueError):
            pass

    ref = config.get("reference_point") if isinstance(config.get("reference_point"), dict) else {}
    ref_x = float(ref.get("x", 0.25))
    ref_y = float(ref.get("y", 0.0))
    ref_z = float(ref.get("z", 0.2))

    shape_cfg = config.get("shape") if isinstance(config.get("shape"), dict) else {}
    shape = str(shape_cfg.get("type", "")).lower().strip()
    params = _shape_params_from_config(shape, shape_cfg)
    violations = _validate_xy_shape_request(arm, shape, params, ref_x, ref_y, ref_z)
    return arm, surface, params, ref_x, ref_y, ref_z, violations


def _kill_pid_gracefully(pid: int) -> str:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return f"pid {pid} already exited"
    except PermissionError:
        return f"pid {pid} permission denied"

    deadline = time.time() + 1.5
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return f"pid {pid} terminated"
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
        return f"pid {pid} force-killed"
    except ProcessLookupError:
        return f"pid {pid} exited after timeout"
    except PermissionError:
        return f"pid {pid} force-kill denied"


def _list_port_user_pids(port: int) -> list[int]:
    pids: list[int] = []
    try:
        out = subprocess.run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
    except FileNotFoundError:
        pass
    return sorted(set(pids))


def _list_serial_user_pids(serial_port: str) -> list[int]:
    pids: list[int] = []
    try:
        out = subprocess.run(
            ["lsof", "-t", serial_port],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
    except FileNotFoundError:
        pass
    return sorted(set(pids))


def _proc_cmdline(pid: int) -> str:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return out or "(unknown)"
    except Exception:
        return "(unknown)"


def _system_load() -> dict:
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    return {
        "load_1m": round(load1, 3),
        "load_5m": round(load5, 3),
        "load_15m": round(load15, 3),
        "cpu_count": cpu_count,
        "load_1m_per_cpu": round(load1 / cpu_count, 3),
    }


def _memory_info() -> dict:
    mem_total = 0
    mem_available = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
    except Exception:
        return {"total_bytes": 0, "available_bytes": 0, "used_bytes": 0, "used_percent": 0.0}

    used = max(0, mem_total - mem_available)
    used_percent = (used / mem_total * 100.0) if mem_total else 0.0
    return {
        "total_bytes": mem_total,
        "available_bytes": mem_available,
        "used_bytes": used,
        "used_percent": round(used_percent, 2),
    }


def _disk_info() -> dict:
    total, used, free = shutil.disk_usage(REPO_ROOT)
    used_percent = (used / total * 100.0) if total else 0.0
    return {
        "path": str(REPO_ROOT),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_percent": round(used_percent, 2),
    }


def _firmware_files() -> list[dict]:
    if not FIRMWARE_DIR.exists():
        return []
    result = []
    for f in sorted(FIRMWARE_DIR.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".ino", ".bin"}:
            continue
        result.append(
            {
                "name": f.name,
                "relative_path": str(f.relative_to(REPO_ROOT)),
                "size_bytes": f.stat().st_size,
                "type": f.suffix.lower().lstrip("."),
            }
        )
    return result


def _find_espota() -> Optional[str]:
    candidates: list[Path] = []

    home = Path.home()
    search_roots = [home / ".arduino15", Path("/usr"), Path("/opt")]
    for root in search_roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("espota.py"):
                if p.is_file():
                    candidates.append(p)
        except Exception:
            continue

    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda p: len(str(p)))
    return str(candidates[0])


async def _run_firmware_upload(request: FirmwareUploadStartRequest) -> None:
    selected_path = (FIRMWARE_DIR / request.filename).resolve()
    firmware_root = FIRMWARE_DIR.resolve()
    if firmware_root not in selected_path.parents and selected_path != firmware_root:
        raise RuntimeError("Invalid firmware file path")
    if not selected_path.exists() or not selected_path.is_file():
        raise RuntimeError("Firmware file not found")

    firmware_upload_state["running"] = True
    firmware_upload_state["success"] = False
    firmware_upload_state["message"] = "Uploading firmware"
    firmware_upload_state["logs"] = []
    firmware_upload_state["started_at"] = time.time()
    firmware_upload_state["finished_at"] = None
    firmware_upload_state["filename"] = request.filename

    method = request.method.lower()
    if method not in {"serial", "ota"}:
        raise RuntimeError("Unsupported firmware upload method")

    if method == "ota" and not request.ota_ip.strip():
        raise RuntimeError("OTA IP is required for OTA uploads")

    command: str
    temp_dir_obj: Optional[tempfile.TemporaryDirectory] = None
    espota_path: Optional[str] = None

    if method == "ota":
        espota_path = _find_espota()
        if not espota_path:
            raise RuntimeError("espota.py not found. Install Arduino ESP32 core to use OTA.")

    if selected_path.suffix.lower() == ".ino":
        if not shutil.which("arduino-cli"):
            raise RuntimeError("arduino-cli not found in PATH")

        sketch_name = selected_path.stem
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="dexter_fw_")
        sketch_dir = Path(temp_dir_obj.name) / sketch_name
        sketch_dir.mkdir(parents=True, exist_ok=True)
        temp_sketch = sketch_dir / f"{sketch_name}.ino"
        temp_sketch.write_text(selected_path.read_text(encoding="utf-8"), encoding="utf-8")

        # Copy sibling headers/sources so sketch compiles similarly to the dashboard uploader.
        for ext in ("*.h", "*.hpp", "*.cpp"):
            for src in selected_path.parent.glob(ext):
                if src.is_file():
                    shutil.copy2(src, sketch_dir / src.name)

        if method == "serial":
            command = (
                f"arduino-cli compile --fqbn {request.fqbn} {shlex.quote(str(sketch_dir))} && "
                f"arduino-cli upload --fqbn {request.fqbn} -p {shlex.quote(request.serial_port)} {shlex.quote(str(sketch_dir))}"
            )
        else:
            ota_flags = f"-a {shlex.quote(request.ota_password)}" if request.ota_password else ""
            bin_candidate = sketch_dir / "build" / "esp32.esp32.esp32" / f"{sketch_name}.ino.bin"
            command = (
                f"arduino-cli compile --fqbn {request.fqbn} {shlex.quote(str(sketch_dir))} && "
                f"python3 {shlex.quote(espota_path)} -i {shlex.quote(request.ota_ip)} "
                f"-f {shlex.quote(str(bin_candidate))} {ota_flags}"
            )
    elif selected_path.suffix.lower() == ".bin":
        if method == "serial":
            esptool_cmd = shutil.which("esptool.py") or shutil.which("esptool")
            if not esptool_cmd:
                raise RuntimeError("esptool.py not found in PATH")
            command = (
                f"{shlex.quote(esptool_cmd)} --chip esp32 --port {shlex.quote(request.serial_port)} "
                f"--baud {request.serial_baud} write_flash 0x10000 {shlex.quote(str(selected_path))}"
            )
        else:
            ota_flags = f"-a {shlex.quote(request.ota_password)}" if request.ota_password else ""
            command = (
                f"python3 {shlex.quote(espota_path)} -i {shlex.quote(request.ota_ip)} "
                f"-f {shlex.quote(str(selected_path))} {ota_flags}"
            )
    else:
        raise RuntimeError("Unsupported firmware type. Use .ino or .bin")

    firmware_upload_state["command"] = command
    _append_firmware_log(f"Starting upload for {request.filename}")

    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-lc",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            _append_firmware_log(line.decode("utf-8", errors="replace").rstrip())

        code = await proc.wait()
        if code == 0:
            firmware_upload_state["success"] = True
            firmware_upload_state["message"] = "Firmware upload completed"
            _append_firmware_log("[DONE] Firmware upload completed")
        else:
            firmware_upload_state["success"] = False
            firmware_upload_state["message"] = f"Firmware upload failed (exit {code})"
            _append_firmware_log(f"[ERROR] Upload failed with exit code {code}")
    finally:
        firmware_upload_state["running"] = False
        firmware_upload_state["finished_at"] = time.time()
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()


async def _run_trajectory(name: str, duration_sec: float) -> None:
    steps = 20
    sleep_s = duration_sec / steps
    try:
        for i in range(1, steps + 1):
            while state.trajectory_paused:
                await asyncio.sleep(0.2)

            await asyncio.sleep(sleep_s)
            state.trajectory_progress = i / steps
            await broadcast(
                EventMessage(
                    type="trajectory_progress",
                    message=f"Trajectory {name} at {int(state.trajectory_progress * 100)}%",
                    payload=snapshot(),
                )
            )

        state.trajectory_running = False
        state.trajectory_name = None
        await broadcast(
            EventMessage(
                type="trajectory_completed",
                message=f"Trajectory {name} completed",
                payload=snapshot(),
            )
        )
    except asyncio.CancelledError:
        state.trajectory_running = False
        state.trajectory_paused = False
        state.trajectory_name = None
        state.trajectory_progress = 0.0
        await broadcast(
            EventMessage(
                type="trajectory_stopped",
                message="Trajectory stopped",
                payload=snapshot(),
            )
        )
        raise


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "dexter-middleware"}


@app.get("/status")
async def status() -> dict:
    return snapshot()


@app.post("/connect")
async def connect() -> dict:
    async with state_lock:
        state.connected = True
    await broadcast(EventMessage(type="connected", message="Robot connected", payload=snapshot()))
    return snapshot()


@app.post("/disconnect")
async def disconnect() -> dict:
    async with state_lock:
        state.connected = False
        state.enabled = False
        if state.worker_task:
            state.worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.worker_task
            state.worker_task = None
    async with moveit_lock:
        moveit_service.stop()
    async with rviz_lock:
        rviz_service.stop()
    async with gazebo_lock:
        gazebo_service.stop()
    async with full_stack_lock:
        full_stack_service.stop()
    async with hardware_lock:
        await hardware_service.stop()
    await broadcast(EventMessage(type="disconnected", message="Robot disconnected", payload=snapshot()))
    return snapshot()


@app.post("/enable")
async def enable() -> dict:
    if not state.connected:
        raise HTTPException(status_code=400, detail="Robot must be connected first")

    state.enabled = True
    await broadcast(EventMessage(type="enabled", message="Robot enabled", payload=snapshot()))
    return snapshot()


@app.post("/disable")
async def disable() -> dict:
    state.enabled = False
    await broadcast(EventMessage(type="disabled", message="Robot disabled", payload=snapshot()))
    return snapshot()


@app.post("/jog/joint")
async def jog_joint(req: JogJointRequest) -> dict:
    if not state.connected or not state.enabled:
        raise HTTPException(status_code=400, detail="Robot must be connected and enabled")

    state.joints_deg[req.joint_index] += req.delta
    await broadcast(
        EventMessage(
            type="joint_jogged",
            message=f"Jogged J{req.joint_index + 1} by {req.delta:.2f} deg",
            payload=snapshot(),
        )
    )
    return snapshot()


@app.post("/trajectory/execute")
async def execute_trajectory(req: ExecuteTrajectoryRequest) -> dict:
    if not state.connected or not state.enabled:
        raise HTTPException(status_code=400, detail="Robot must be connected and enabled")
    if state.trajectory_running:
        raise HTTPException(status_code=409, detail="Another trajectory is already running")

    state.trajectory_running = True
    state.trajectory_paused = False
    state.trajectory_name = req.name
    state.trajectory_progress = 0.0
    state.worker_task = asyncio.create_task(_run_trajectory(req.name, req.duration_sec))

    await broadcast(
        EventMessage(
            type="trajectory_started",
            message=f"Trajectory {req.name} started",
            payload=snapshot(),
        )
    )
    return snapshot()


@app.post("/trajectory/pause")
async def pause_trajectory() -> dict:
    if not state.trajectory_running:
        raise HTTPException(status_code=400, detail="No trajectory is running")

    state.trajectory_paused = True
    await broadcast(EventMessage(type="trajectory_paused", message="Trajectory paused", payload=snapshot()))
    return snapshot()


@app.post("/trajectory/resume")
async def resume_trajectory() -> dict:
    if not state.trajectory_running:
        raise HTTPException(status_code=400, detail="No trajectory is running")

    state.trajectory_paused = False
    await broadcast(EventMessage(type="trajectory_resumed", message="Trajectory resumed", payload=snapshot()))
    return snapshot()


@app.post("/trajectory/stop")
async def stop_trajectory() -> dict:
    if not state.trajectory_running or not state.worker_task:
        raise HTTPException(status_code=400, detail="No trajectory is running")

    state.worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await state.worker_task
    state.worker_task = None

    return snapshot()


@app.post("/trajectory/generate")
async def trajectory_generate(req: TrajectoryGenerateRequest) -> dict:
    config = req.config if isinstance(req.config, dict) else {}
    if not config:
        raise HTTPException(status_code=400, detail="Missing trajectory generation config")

    arm, surface, _params, _rx, _ry, _rz, violations = _preflight_shape_generation_config(config)
    supported_surfaces = TRAJECTORY_SAFETY.get("defaults", {}).get("supported_surfaces", ["XY"])
    if surface not in supported_surfaces:
        raise HTTPException(
            status_code=400,
            detail=f"Surface {surface} not supported in Phase 7 MVP. Allowed: {', '.join(supported_surfaces)}",
        )

    if violations:
        raise HTTPException(
            status_code=400,
            detail=f"Safety preflight failed for {arm} arm: {violations[0]}",
        )

    return _bridge_json_request("POST", "/generate", payload=config, timeout_sec=20.0)


@app.get("/trajectory/backend/status")
async def trajectory_backend_status() -> dict:
    bridge_online, bridge_detail = _bridge_probe()
    return {
        "ok": True,
        "middleware_online": True,
        "bridge_online": bridge_online,
        "bridge_base_url": BRIDGE_BASE_URL,
        "message": bridge_detail,
    }


@app.get("/trajectory/jobs/{job_id}")
async def trajectory_job_status(job_id: str) -> dict:
    job = job_id.strip()
    if not job:
        raise HTTPException(status_code=400, detail="job_id is required")
    return _bridge_json_request("GET", f"/jobs/{job}", timeout_sec=10.0)


@app.get("/trajectory/download/{job_id}")
async def trajectory_download(job_id: str) -> Response:
    job = job_id.strip()
    if not job:
        raise HTTPException(status_code=400, detail="job_id is required")

    body, content_type, disposition = _bridge_binary_request(f"/download/{job}", timeout_sec=30.0)
    headers = {}
    if disposition:
        headers["Content-Disposition"] = disposition
    return Response(content=body, media_type=content_type, headers=headers)


@app.post("/trajectory/safety/limits")
async def trajectory_safety_limits(req: TrajectorySafetyLimitsRequest) -> dict:
    supported_surfaces = TRAJECTORY_SAFETY.get("defaults", {}).get("supported_surfaces", ["XY"])
    if req.surface not in supported_surfaces:
        return {
            "ok": False,
            "message": f"Surface {req.surface} not supported yet. Allowed: {', '.join(supported_surfaces)}",
            "supported_surfaces": supported_surfaces,
        }

    zone = _arm_safety_zone(req.arm)
    sx, sy, _ = [float(v) for v in zone["shoulder"]]
    reach = float(zone["reach_m"])
    ratio = float(zone.get("reach_soft_ratio", TRAJECTORY_SAFETY.get("defaults", {}).get("reach_soft_ratio", 0.95)))
    clamped_ref_x = _clamp(req.ref_x, float(zone["x_range"][0]), float(zone["x_range"][1]))
    clamped_ref_y = _clamp(req.ref_y, float(zone["y_range"][0]), float(zone["y_range"][1]))
    clamped_ref_z = _clamp(req.ref_z, float(zone["z_range"][0]), float(zone["z_range"][1]))

    dist_xy = math.sqrt((clamped_ref_x - sx) ** 2 + (clamped_ref_y - sy) ** 2)
    available = max(0.02, (reach * ratio) - dist_xy)

    limits = _shape_param_limits(req.shape, available)
    return {
        "ok": True,
        "arm": req.arm,
        "surface": req.surface,
        "reference": {"x": clamped_ref_x, "y": clamped_ref_y, "z": clamped_ref_z},
        "ref_ranges": {
            "x": {"min": float(zone["x_range"][0]), "max": float(zone["x_range"][1]), "step": 0.005},
            "y": {"min": float(zone["y_range"][0]), "max": float(zone["y_range"][1]), "step": 0.005},
            "z": {"min": float(zone["z_range"][0]), "max": float(zone["z_range"][1]), "step": 0.005},
        },
        "param_ranges": limits,
        "reach_margin_m": round(available, 4),
    }


@app.post("/trajectory/safety/default-reference")
async def trajectory_safety_default_reference(req: TrajectorySafetyDefaultReferenceRequest) -> dict:
    supported_surfaces = TRAJECTORY_SAFETY.get("defaults", {}).get("supported_surfaces", ["XY"])
    if req.surface not in supported_surfaces:
        return {
            "ok": False,
            "message": f"Surface {req.surface} not supported yet. Allowed: {', '.join(supported_surfaces)}",
            "supported_surfaces": supported_surfaces,
        }

    ref_x, ref_y, ref_z = _default_safe_reference(req.arm)
    zone = _arm_safety_zone(req.arm)
    sx, sy, _ = [float(v) for v in zone["shoulder"]]
    reach = float(zone["reach_m"])
    ratio = float(zone.get("reach_soft_ratio", TRAJECTORY_SAFETY.get("defaults", {}).get("reach_soft_ratio", 0.95)))
    dist_xy = math.sqrt((ref_x - sx) ** 2 + (ref_y - sy) ** 2)
    available = max(0.02, (reach * ratio) - dist_xy)

    return {
        "ok": True,
        "arm": req.arm,
        "surface": req.surface,
        "reference": {"x": round(ref_x, 4), "y": round(ref_y, 4), "z": round(ref_z, 4)},
        "param_ranges": _shape_param_limits(req.shape, available),
        "reach_margin_m": round(available, 4),
    }


@app.post("/trajectory/safety/check")
async def trajectory_safety_check(req: TrajectorySafetyCheckRequest) -> dict:
    supported_surfaces = TRAJECTORY_SAFETY.get("defaults", {}).get("supported_surfaces", ["XY"])
    if req.surface not in supported_surfaces:
        return {
            "ok": True,
            "valid": False,
            "message": f"Surface {req.surface} not supported in Phase 7 MVP. Use XY.",
            "violations": [f"Unsupported surface: {req.surface}"],
        }

    violations = _validate_xy_shape_request(
        arm=req.arm,
        shape=req.shape,
        params=req.params,
        ref_x=req.ref_x,
        ref_y=req.ref_y,
        ref_z=req.ref_z,
    )
    if violations:
        return {
            "ok": True,
            "valid": False,
            "message": "Trajectory request is outside safety zone",
            "violations": violations,
        }

    return {
        "ok": True,
        "valid": True,
        "message": "Trajectory request is inside safety zone",
        "violations": [],
    }


@app.get("/ros/rviz/status")
async def rviz_status() -> dict:
    return snapshot()["rviz"]


@app.post("/ros/rviz/start")
async def rviz_start(req: RvizStartRequest) -> dict:
    conflicts = _launch_conflicts()
    if conflicts["full_stack"]:
        raise HTTPException(status_code=409, detail="Full system simulation is running. Stop it before starting RViz-only.")
    if conflicts["hardware"] or conflicts["hardware_bootstrap"]:
        raise HTTPException(status_code=409, detail="Hardware mode is active. Stop hardware session before starting RViz-only.")

    try:
        async with rviz_lock:
            before = rviz_service.status()
            after = rviz_service.start(gui=req.gui)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if before.running:
        await broadcast(
            EventMessage(
                type="rviz_already_running",
                message="RViz was already running",
                payload=snapshot(),
            )
        )
    else:
        await broadcast(
            EventMessage(
                type="rviz_started",
                message="RViz started with model-only launch",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.post("/ros/rviz/stop")
async def rviz_stop() -> dict:
    async with rviz_lock:
        before = rviz_service.status()
        after = rviz_service.stop()

    if before.running:
        await broadcast(
            EventMessage(
                type="rviz_stopped",
                message="RViz stopped",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.get("/ros/moveit/status")
async def moveit_status() -> dict:
    return snapshot()["moveit"]


@app.post("/ros/moveit/start")
async def moveit_start(req: MoveitStartRequest) -> dict:
    conflicts = _launch_conflicts()
    if conflicts["full_stack"]:
        raise HTTPException(status_code=409, detail="Full system simulation is running. Stop it before starting MoveIt-only.")
    if conflicts["hardware"] or conflicts["hardware_bootstrap"]:
        raise HTTPException(status_code=409, detail="Hardware mode is active. Stop hardware session before starting MoveIt-only.")

    try:
        async with moveit_lock:
            before = moveit_service.status()
            after = moveit_service.start(use_sim_time=req.use_sim_time)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if before.running:
        await broadcast(
            EventMessage(
                type="moveit_already_running",
                message="MoveIt demo was already running",
                payload=snapshot(),
            )
        )
    else:
        await broadcast(
            EventMessage(
                type="moveit_started",
                message="MoveIt demo started (RViz + move_group)",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.post("/ros/moveit/stop")
async def moveit_stop() -> dict:
    async with moveit_lock:
        before = moveit_service.status()
        after = moveit_service.stop()

    if before.running:
        await broadcast(
            EventMessage(
                type="moveit_stopped",
                message="MoveIt demo stopped",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.get("/ros/gazebo/status")
async def gazebo_status() -> dict:
    return snapshot()["gazebo"]


@app.post("/ros/gazebo/start")
async def gazebo_start(req: GazeboStartRequest) -> dict:
    conflicts = _launch_conflicts()
    if conflicts["full_stack"]:
        raise HTTPException(status_code=409, detail="Full system simulation is running. Stop it before starting Gazebo-only.")
    if conflicts["hardware"] or conflicts["hardware_bootstrap"]:
        raise HTTPException(status_code=409, detail="Hardware mode is active. Stop hardware session before starting Gazebo-only.")

    try:
        async with gazebo_lock:
            before = gazebo_service.status()
            after = gazebo_service.start(gui=req.gui)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if before.running:
        await broadcast(
            EventMessage(
                type="gazebo_already_running",
                message="Gazebo-only session was already running",
                payload=snapshot(),
            )
        )
    else:
        await broadcast(
            EventMessage(
                type="gazebo_started",
                message="Gazebo-only session started",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.post("/ros/gazebo/stop")
async def gazebo_stop() -> dict:
    async with gazebo_lock:
        before = gazebo_service.status()
        after = gazebo_service.stop()

    if before.running:
        await broadcast(
            EventMessage(
                type="gazebo_stopped",
                message="Gazebo-only session stopped",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.get("/ros/full-stack/status")
async def full_stack_status() -> dict:
    return snapshot()["full_stack"]


@app.post("/ros/full-stack/start")
async def full_stack_start(req: FullStackStartRequest) -> dict:
    conflicts = _launch_conflicts()
    if conflicts["hardware"] or conflicts["hardware_bootstrap"]:
        raise HTTPException(
            status_code=409,
            detail="Hardware mode is active. Stop hardware session before starting full system simulation.",
        )

    await _preempt_simulation_for("full system simulation", include_full_stack=False)

    try:
        async with full_stack_lock:
            before = full_stack_service.status()
            after = full_stack_service.start(use_rviz=req.use_rviz, load_moveit=req.load_moveit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if before.running:
        await broadcast(
            EventMessage(
                type="full_stack_already_running",
                message="Phase 3 full stack was already running",
                payload=snapshot(),
            )
        )
    else:
        await broadcast(
            EventMessage(
                type="full_stack_started",
                message="Phase 3 full stack started (Gazebo + RViz + MoveIt + controllers)",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.post("/ros/full-stack/stop")
async def full_stack_stop() -> dict:
    async with full_stack_lock:
        before = full_stack_service.status()
        after = full_stack_service.stop()

    if before.running:
        await broadcast(
            EventMessage(
                type="full_stack_stopped",
                message="Phase 3 full stack stopped",
                payload=snapshot(),
            )
        )

    return {
        "running": after.running,
        "pid": after.pid,
        "command": after.command,
    }


@app.get("/ros/hardware/status")
async def hardware_status() -> dict:
    return snapshot()["hardware"]


@app.post("/ros/hardware/start")
async def hardware_start(req: HardwareBootstrapStartRequest) -> dict:
    global hardware_bootstrap_task

    if hardware_bootstrap_task and not hardware_bootstrap_task.done():
        raise HTTPException(status_code=409, detail="Hardware bootstrap already in progress")

    await _preempt_simulation_for("hardware mode", include_full_stack=True)

    if req.transport == "serial":
        serial_pids = _list_serial_user_pids(req.device_port)
        serial_pids = [pid for pid in serial_pids if pid != os.getpid()]
        if serial_pids:
            for pid in serial_pids:
                _kill_pid_gracefully(pid)
            await asyncio.sleep(0.5)

    async def _run_hardware_bootstrap() -> None:
        try:
            async with hardware_lock:
                result = await hardware_service.start(
                    transport=req.transport,
                    device_port=req.device_port,
                    use_rviz=req.use_rviz,
                    load_moveit=req.load_moveit,
                    agent_timeout_sec=req.agent_timeout_sec,
                    agent_max_retries=req.agent_max_retries,
                )

            if result["status"] == "running":
                await broadcast(
                    EventMessage(
                        type="hardware_started",
                        message="Phase 4 hardware bootstrap complete (micro-ROS agent + hardware_bringup active)",
                        payload=snapshot(),
                    )
                )
            else:
                await broadcast(
                    EventMessage(
                        type="hardware_start_failed",
                        message=f"Phase 4 hardware bootstrap failed: {result['message']}",
                        payload=snapshot(),
                    )
                )
        except Exception as exc:
            await broadcast(
                EventMessage(
                    type="hardware_start_failed",
                    message=f"Phase 4 hardware bootstrap exception: {exc}",
                    payload=snapshot(),
                )
            )

    hardware_bootstrap_task = asyncio.create_task(_run_hardware_bootstrap())

    return {
        "accepted": True,
        "status": "bootstrapping",
        "message": "Hardware bootstrap started in background",
        "hardware": hardware_service.status(),
    }


@app.post("/ros/hardware/stop")
async def hardware_stop() -> dict:
    async with hardware_lock:
        result = await hardware_service.stop()

    await broadcast(
        EventMessage(
            type="hardware_stopped",
            message="Phase 4 hardware disconnected (agent + launch terminated)",
            payload=snapshot(),
        )
    )

    return hardware_service.status()


@app.post("/ros/hardware/reset")
async def hardware_reset() -> dict:
    global hardware_bootstrap_task

    if hardware_bootstrap_task and not hardware_bootstrap_task.done():
        raise HTTPException(status_code=409, detail="Cannot reset while bootstrap is in progress")

    status = hardware_service.status()
    if status["agent_running"] or status["launch_running"]:
        raise HTTPException(status_code=409, detail="Stop hardware before reset")

    async with hardware_lock:
        reset_status = hardware_service.reset_status()

    await broadcast(
        EventMessage(
            type="hardware_reset",
            message="Phase 4 hardware session reset to fresh state",
            payload=snapshot(),
        )
    )

    return reset_status


@app.get("/firmware/mdns-lookup")
async def firmware_mdns_lookup() -> dict:
    """Resolve ESP32 mDNS hostname to IP address with 3-second timeout."""
    try:
        loop = asyncio.get_event_loop()
        ip = await asyncio.wait_for(
            loop.run_in_executor(None, socket.gethostbyname, "dexter-esp32.local"),
            timeout=3.0
        )
        return {"success": True, "ip": ip, "message": f"Auto-detected {ip}"}
    except asyncio.TimeoutError:
        return {
            "success": False,
            "ip": None,
            "message": "mDNS lookup timed out (3s). Ensure ESP32 is online and connected to same WiFi.",
        }
    except socket.gaierror as e:
        return {
            "success": False,
            "ip": None,
            "message": f"mDNS lookup failed: {e}. Try entering the IP manually or use dexter-esp32.local",
        }
    except Exception as e:
        return {
            "success": False,
            "ip": None,
            "message": f"Unexpected error during mDNS lookup: {e}",
        }


@app.get("/firmware/files")
async def firmware_files() -> dict:
    return {
        "firmware_root": str(FIRMWARE_DIR.relative_to(REPO_ROOT)),
        "files": _firmware_files(),
    }


@app.get("/firmware/upload/status")
async def firmware_upload_status() -> dict:
    elapsed = 0
    started = firmware_upload_state.get("started_at")
    finished = firmware_upload_state.get("finished_at")
    if started:
        end_time = float(finished) if finished else time.time()
        elapsed = max(0, int(end_time - float(started)))
    return {
        **firmware_upload_state,
        "elapsed_sec": elapsed,
    }


@app.post("/firmware/upload/start")
async def firmware_upload_start(req: FirmwareUploadStartRequest) -> dict:
    global firmware_upload_task

    if firmware_upload_task and not firmware_upload_task.done():
        raise HTTPException(status_code=409, detail="Firmware upload already in progress")

    firmware_upload_state["running"] = True
    firmware_upload_state["success"] = False
    firmware_upload_state["message"] = f"Upload queued for {req.filename}"
    firmware_upload_state["logs"] = [f"[{time.strftime('%H:%M:%S')}] Queued firmware upload"]
    firmware_upload_state["started_at"] = time.time()
    firmware_upload_state["finished_at"] = None
    firmware_upload_state["command"] = None
    firmware_upload_state["filename"] = req.filename

    async def _runner() -> None:
        try:
            async with firmware_lock:
                await _run_firmware_upload(req)
            await broadcast(
                EventMessage(
                    type="firmware_upload_completed",
                    message=f"Firmware upload completed for {req.filename}",
                    payload=snapshot(),
                )
            )
        except Exception as exc:
            firmware_upload_state["running"] = False
            firmware_upload_state["success"] = False
            firmware_upload_state["message"] = f"Firmware upload failed: {exc}"
            firmware_upload_state["finished_at"] = time.time()
            _append_firmware_log(f"[ERROR] {exc}")
            await broadcast(
                EventMessage(
                    type="firmware_upload_failed",
                    message=f"Firmware upload failed: {exc}",
                    payload=snapshot(),
                )
            )

    firmware_upload_task = asyncio.create_task(_runner())

    return {
        "accepted": True,
        "message": f"Firmware upload queued for {req.filename}",
        "status": await firmware_upload_status(),
    }


@app.get("/system/monitor")
async def system_monitor() -> dict:
    port_info: list[dict] = []
    for port in [8080, 8083, 8084, 8090]:
        pids = _list_port_user_pids(port)
        port_info.append(
            {
                "port": port,
                "occupied": len(pids) > 0,
                "pids": pids,
                "commands": [_proc_cmdline(pid) for pid in pids[:4]],
            }
        )

    return {
        "timestamp": int(time.time()),
        "middleware_pid": os.getpid(),
        "middleware_uptime_sec": int(time.time() - middleware_started_at),
        "health": {
            "load": _system_load(),
            "memory": _memory_info(),
            "disk": _disk_info(),
        },
        "session": {
            "snapshot": snapshot(),
            "hardware_bootstrap_in_progress": _hardware_bootstrap_in_progress(),
            "firmware_upload": await firmware_upload_status(),
        },
        "ports": port_info,
    }


@app.post("/system/cleanup")
async def system_cleanup(req: CleanupRequest) -> dict:
    # Stop managed sessions first for a safe baseline.
    async with moveit_lock:
        moveit_service.stop()
    async with rviz_lock:
        rviz_service.stop()
    async with gazebo_lock:
        gazebo_service.stop()
    async with full_stack_lock:
        full_stack_service.stop()
    async with hardware_lock:
        await hardware_service.stop()

    report: dict = {
        "stopped_managed_sessions": True,
        "ports": {},
        "serial": {},
    }

    current_pid = os.getpid()

    if req.include_port_cleanup:
        for port in req.ports:
            pids = [pid for pid in _list_port_user_pids(port) if pid != current_pid]
            actions = [_kill_pid_gracefully(pid) for pid in pids]
            report["ports"][str(port)] = {
                "found_pids": pids,
                "actions": actions,
            }

    if req.include_serial_cleanup and req.serial_port:
        serial_pids = [pid for pid in _list_serial_user_pids(req.serial_port) if pid != current_pid]
        serial_actions = [_kill_pid_gracefully(pid) for pid in serial_pids]
        report["serial"] = {
            "port": req.serial_port,
            "found_pids": serial_pids,
            "actions": serial_actions,
        }

    await broadcast(
        EventMessage(
            type="system_cleanup",
            message="System cleanup executed (sessions stopped, stale port users flushed)",
            payload=snapshot(),
        )
    )

    return report


@app.post("/system/exit")
async def system_exit() -> dict:
    await broadcast(
        EventMessage(
            type="system_exit_requested",
            message="Stopping local control center services",
            payload=snapshot(),
        )
    )
    asyncio.create_task(_shutdown_control_center())
    return {
        "accepted": True,
        "message": "Shutdown requested. Services will stop now.",
    }


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await websocket.accept()
    clients.add(websocket)
    await websocket.send_text(json.dumps({"type": "hello", "message": "connected", "payload": snapshot()}))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)
