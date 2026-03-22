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


class CleanupRequest(BaseModel):
    ports: list[int] = Field(default_factory=lambda: [8080, 8083, 8084, 8090])
    serial_port: str = Field(default="/dev/ttyUSB0")
    include_port_cleanup: bool = True
    include_serial_cleanup: bool = True


class FirmwareUploadStartRequest(BaseModel):
    filename: str = Field(min_length=1)
    method: str = Field(default="serial", pattern="^(serial|ota)$")
    serial_port: str = Field(default="/dev/ttyUSB0")
    serial_baud: int = Field(default=921600, ge=9600, le=2000000)
    fqbn: str = Field(default="esp32:esp32:esp32")
    ota_ip: str = Field(default="")
    ota_password: str = Field(default="")


class TrajectorySafetyLimitsRequest(BaseModel):
    arm: str = Field(default="left", pattern="^(left|right)$")
    surface: str = Field(default="XY")
    ref_x: float = 0.25
    ref_y: float = 0.0
    ref_z: float = 0.2
    shape: str = Field(default="circle")


class TrajectorySafetyCheckRequest(BaseModel):
    arm: str = Field(default="left", pattern="^(left|right)$")
    surface: str = Field(default="XY")
    shape: str = Field(default="circle")
    params: dict[str, float] = Field(default_factory=dict)
    ref_x: float = 0.25
    ref_y: float = 0.0
    ref_z: float = 0.2


class TrajectorySafetyDefaultReferenceRequest(BaseModel):
    arm: str = Field(default="left", pattern="^(left|right)$")
    surface: str = Field(default="XY")
    shape: str = Field(default="circle")


class TrajectoryGenerateRequest(BaseModel):
    config: dict = Field(default_factory=dict)


class TrajectoryJobStatusRequest(BaseModel):
    job_id: str = Field(min_length=1)
