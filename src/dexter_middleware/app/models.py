from pydantic import BaseModel, Field


class JogJointRequest(BaseModel):
    joint_index: int = Field(ge=0, le=5)
    delta: float = Field(description="Joint delta in degrees")


class ExecuteTrajectoryRequest(BaseModel):
    name: str = Field(min_length=1)
    duration_sec: float = Field(gt=0)


class EventMessage(BaseModel):
    type: str
    message: str
    payload: dict = Field(default_factory=dict)


class RvizStartRequest(BaseModel):
    gui: bool = True


class MoveitStartRequest(BaseModel):
    use_sim_time: bool = False


class GazeboStartRequest(BaseModel):
    gui: bool = True


class FullStackStartRequest(BaseModel):
    use_rviz: bool = True
    load_moveit: bool = True


class HardwareBootstrapStartRequest(BaseModel):
    transport: str = Field(default="serial", pattern="^(serial|udp)$")
    device_port: str = Field(default="/dev/ttyUSB0", description="Serial device or UDP port")
    use_rviz: bool = True
    load_moveit: bool = True
    agent_timeout_sec: int = Field(default=30, ge=10, le=120)
    agent_max_retries: int = Field(default=3, ge=1, le=5)
