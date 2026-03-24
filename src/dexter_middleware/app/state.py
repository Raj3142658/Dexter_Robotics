import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RobotState:
    connected: bool = False
    enabled: bool = False
    joints_deg: list[float] = field(default_factory=lambda: [0.0] * 6)
    trajectory_name: Optional[str] = None
    trajectory_progress: float = 0.0
    trajectory_running: bool = False
    trajectory_paused: bool = False
    worker_task: Optional[asyncio.Task] = None
    execution_context: str = "simulated"  # "simulated" | "hardware" | "gazebo" | "full_stack"
