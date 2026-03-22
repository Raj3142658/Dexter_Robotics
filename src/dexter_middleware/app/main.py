import asyncio
import json
import subprocess
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .models import EventMessage, ExecuteTrajectoryRequest, FullStackStartRequest, GazeboStartRequest, HardwareBootstrapStartRequest, JogJointRequest, MoveitStartRequest, RvizStartRequest
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


@app.get("/ros/rviz/status")
async def rviz_status() -> dict:
    return snapshot()["rviz"]


@app.post("/ros/rviz/start")
async def rviz_start(req: RvizStartRequest) -> dict:
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
    # Prevent conflicting launch graphs by stopping standalone sessions first.
    async with moveit_lock:
        moveit_service.stop()
    async with rviz_lock:
        rviz_service.stop()
    async with gazebo_lock:
        gazebo_service.stop()

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

    # Prevent conflicting launch graphs by stopping all standalone/simulation sessions first.
    async with moveit_lock:
        moveit_service.stop()
    async with rviz_lock:
        rviz_service.stop()
    async with gazebo_lock:
        gazebo_service.stop()
    async with full_stack_lock:
        full_stack_service.stop()
    
    await asyncio.sleep(1)  # Give services time to clean up

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
