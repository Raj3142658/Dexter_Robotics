"""
Hardware Bootstrap Service (Phase 4)

Manages two-stage bootstrap for real hardware control:
  Stage 1: Start micro-ROS agent, validate session connection
  Stage 2: Launch hardware_bringup.launch.py with RViz + MoveIt
"""

import asyncio
import os
import re
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional


class HardwareBootstrapService:
    """Manages real hardware bootstrap and lifecycle (agent + hardware_bringup)."""

    def __init__(self):
        self._agent_process: Optional[subprocess.Popen] = None
        self._agent_command: Optional[str] = None
        self._agent_transport: Optional[str] = None
        self._agent_device: Optional[str] = None
        self._agent_session_markers: list[str] = []

        self._hardware_process: Optional[subprocess.Popen] = None
        self._hardware_command: Optional[str] = None
        self._hardware_log_path: Optional[str] = None

        self._use_rviz: bool = False
        self._load_moveit: bool = False
        self._state: str = "idle"
        self._phase: str = "idle"
        self._message: str = "Idle"
        self._last_error: Optional[str] = None
        self._logs: list[str] = []
        self._started_at: Optional[float] = None
        self._current_attempt: int = 0
        self._max_attempts: int = 0
        self._reset_hint_logged: bool = False

    def _append_log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self._logs.append(f"[{ts}] {message}")
        self._logs = self._logs[-120:]

    def _firmware_uses_wifi_transport(self) -> bool:
        """Best-effort hint: detect if project firmware is configured for WiFi micro-ROS transport."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            firmware = repo_root / "src" / "dexter_arm_hardware" / "firmware" / "esp32_firmware_wireless.ino"
            if not firmware.exists():
                return False
            text = firmware.read_text(encoding="utf-8", errors="replace")
            return "set_microros_wifi_transports" in text
        except Exception:
            return False

    def _wireless_firmware_agent_config(self) -> dict[str, str] | None:
        """Read AGENT_IP/AGENT_PORT from wireless firmware when available."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            firmware = repo_root / "src" / "dexter_arm_hardware" / "firmware" / "esp32_firmware_wireless.ino"
            if not firmware.exists():
                return None
            text = firmware.read_text(encoding="utf-8", errors="replace")
            ip_match = re.search(r'^\s*#define\s+AGENT_IP\s+"([^"]+)"', text, re.MULTILINE)
            port_match = re.search(r'^\s*#define\s+AGENT_PORT\s+(\d+)', text, re.MULTILINE)
            if not ip_match and not port_match:
                return None
            return {
                "ip": ip_match.group(1) if ip_match else "",
                "port": port_match.group(1) if port_match else "",
            }
        except Exception:
            return None

    def _host_lan_ip(self) -> str:
        """Best-effort host LAN IP for UDP agent hinting."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return ""

    def _elapsed_sec(self) -> int:
        if self._started_at is None:
            return 0
        return max(0, int(time.time() - self._started_at))

    def _set_state(self, state: str, phase: str, message: str) -> None:
        self._state = state
        self._phase = phase
        self._message = message
        self._append_log(message)

    def _wrap_ros_command(self, ros_command: str) -> list[str]:
        """Run command in shell with ROS + Dexter + micro-ROS overlays sourced."""
        repo_root = Path(__file__).resolve().parents[4]
        dexter_ws_setup = repo_root / "install" / "setup.bash"
        wrapped = (
            "source /opt/ros/jazzy/setup.bash && "
            f"if [ -f '{dexter_ws_setup}' ]; then source '{dexter_ws_setup}'; fi && "
            "if [ -f \"$HOME/microros_ws/install/setup.bash\" ]; then "
            "source \"$HOME/microros_ws/install/setup.bash\"; "
            "fi && "
            f"{ros_command}"
        )
        return ["/bin/bash", "-lc", wrapped]

    def _sanitized_env(self) -> dict[str, str]:
        """Remove snap/vscode runtime pollution from GUI/ROS launches."""
        env = os.environ.copy()

        for key in list(env.keys()):
            if key.startswith("SNAP"):
                env.pop(key, None)

        for key in [
            "GTK_PATH",
            "GTK_EXE_PREFIX",
            "GTK_IM_MODULE_FILE",
            "GSETTINGS_SCHEMA_DIR",
            "GIO_MODULE_DIR",
            "GIO_LAUNCHED_DESKTOP_FILE",
            "LOCPATH",
            "GIT_ASKPASS",
            "VSCODE_GIT_ASKPASS_MAIN",
            "VSCODE_GIT_ASKPASS_NODE",
            "XDG_DATA_HOME",
            "XDG_DATA_DIRS",
        ]:
            env.pop(key, None)

        xdg_orig = os.environ.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG")
        if xdg_orig:
            env["XDG_DATA_DIRS"] = xdg_orig

        path = env.get("PATH", "")
        if path:
            env["PATH"] = ":".join([p for p in path.split(":") if p and "/snap/" not in p])

        ld_path = env.get("LD_LIBRARY_PATH", "")
        if ld_path:
            kept = [p for p in ld_path.split(":") if p and "/snap/" not in p]
            if kept:
                env["LD_LIBRARY_PATH"] = ":".join(kept)
            else:
                env.pop("LD_LIBRARY_PATH", None)

        return env

    def _ps_rows(self) -> list[tuple[int, int, str]]:
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid=,ppid=,args="],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except Exception:
            return []

        rows: list[tuple[int, int, str]] = []
        for line in out.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            try:
                rows.append((int(parts[0]), int(parts[1]), parts[2]))
            except ValueError:
                continue
        return rows

    def _collect_descendant_pids(self, root_pid: int) -> set[int]:
        try:
            ps_out = subprocess.run(
                ["ps", "-eo", "pid=,ppid="],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except Exception:
            return set()

        children: dict[int, list[int]] = {}
        for line in ps_out.splitlines():
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
            except ValueError:
                continue
            children.setdefault(ppid, []).append(pid)

        descendants: set[int] = set()
        queue = [root_pid]
        while queue:
            parent = queue.pop(0)
            for child in children.get(parent, []):
                if child not in descendants:
                    descendants.add(child)
                    queue.append(child)
        return descendants

    async def _terminate_pid(self, pid: int, name: str, timeout_sec: int = 3) -> bool:
        """Terminate a PID, preferring process-group kill when possible."""
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return True
        except Exception:
            pgid = None

        try:
            if pgid is not None and pgid == pid:
                os.killpg(pgid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except Exception as exc:
            self._append_log(f"Failed to terminate {name} PID {pid}: {exc}")
            return False

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                self._append_log(f"{name} PID {pid} stopped gracefully")
                return True
            await asyncio.sleep(0.15)

        try:
            if pgid is not None and pgid == pid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
            self._append_log(f"Force-killed {name} PID {pid}")
            return True
        except ProcessLookupError:
            return True
        except Exception as exc:
            self._append_log(f"Failed to force-kill {name} PID {pid}: {exc}")
            return False

    async def _cleanup_stale_micro_ros_agents(self, transport: str, device_port: str) -> int:
        """Kill orphan micro-ROS agent processes left from previous failed starts."""
        rows = self._ps_rows()
        if not rows:
            return 0

        wanted: list[int] = []
        dev_real = os.path.realpath(device_port) if device_port.startswith("/dev/") else device_port
        for pid, _ppid, cmd in rows:
            cmd_l = cmd.lower()
            if "micro_ros_agent" not in cmd_l:
                continue
            if self._agent_process and pid == self._agent_process.pid:
                continue

            if transport == "serial":
                serial_match = " serial " in f" {cmd_l} " and (device_port in cmd or dev_real in cmd)
                if serial_match:
                    wanted.append(pid)
            elif transport == "udp":
                udp_match = " udp4 " in f" {cmd_l} " and f"--port {device_port}" in cmd
                if udp_match:
                    wanted.append(pid)
            else:
                wanted.append(pid)

        if not wanted:
            return 0

        for pid in sorted(set(wanted)):
            await self._terminate_pid(pid, name="stale_micro_ros_agent")
        return len(set(wanted))

    def _hardware_ready(self, use_rviz: bool, load_moveit: bool) -> bool:
        if not self._hardware_process:
            return False

        descendants = self._collect_descendant_pids(self._hardware_process.pid)
        if not descendants:
            return False

        has_controller_manager = False
        has_rviz = not use_rviz
        has_move_group = not load_moveit

        for pid, _ppid, cmd in self._ps_rows():
            if pid not in descendants:
                continue
            cmd_l = cmd.lower()
            if "controller_manager" in cmd_l:
                has_controller_manager = True
            if "rviz2" in cmd_l:
                has_rviz = True
            if "move_group" in cmd_l:
                has_move_group = True

        return has_controller_manager and has_rviz and has_move_group

    def _tail_hardware_logs(self, max_lines: int = 80) -> str:
        if not self._hardware_log_path:
            return "(no hardware launch log file)"
        try:
            with open(self._hardware_log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-max_lines:]).strip() or "(hardware log file empty)"
        except Exception:
            return "(failed to read hardware launch log file)"

    def status(self) -> dict:
        agent_running = False
        agent_pid = None
        if self._agent_process:
            agent_running = self._agent_process.poll() is None
            if agent_running:
                agent_pid = self._agent_process.pid

        hardware_running = False
        hardware_pid = None
        if self._hardware_process:
            hardware_running = self._hardware_process.poll() is None
            if hardware_running:
                hardware_pid = self._hardware_process.pid

        return {
            "state": self._state,
            "phase": self._phase,
            "message": self._message,
            "last_error": self._last_error,
            "elapsed_sec": self._elapsed_sec(),
            "current_attempt": self._current_attempt,
            "max_attempts": self._max_attempts,
            "suggest_reset": (
                self._agent_transport == "serial"
                and self._phase == "agent_connecting"
                and self._elapsed_sec() >= 10
            ),
            "session_logs": self._logs,
            "agent_running": agent_running,
            "agent_pid": agent_pid,
            "agent_transport": self._agent_transport,
            "agent_device": self._agent_device,
            "agent_session_established": len(self._agent_session_markers) > 0,
            "agent_session_markers": self._agent_session_markers,
            "launch_running": hardware_running,
            "launch_pid": hardware_pid,
            "hardware_connected": agent_running and hardware_running,
            "use_rviz": self._use_rviz,
            "load_moveit": self._load_moveit,
            "command_agent": self._agent_command,
            "command_hardware": self._hardware_command,
        }

    async def start(
        self,
        transport: str = "serial",
        device_port: str = "/dev/ttyUSB0",
        use_rviz: bool = True,
        load_moveit: bool = True,
        agent_timeout_sec: int = 30,
        agent_max_retries: int = 3,
    ) -> dict:
        effective_timeout_sec = agent_timeout_sec
        effective_max_retries = agent_max_retries
        if transport == "udp":
            # UDP over WiFi is bursty on startup; use a wider connect window.
            effective_timeout_sec = max(30, min(agent_timeout_sec, 120))
            effective_max_retries = max(3, agent_max_retries)

        self._use_rviz = use_rviz
        self._load_moveit = load_moveit
        self._agent_transport = transport
        self._agent_device = device_port
        self._agent_session_markers = []
        self._last_error = None
        self._logs = []
        self._started_at = time.time()
        self._current_attempt = 0
        self._max_attempts = effective_max_retries
        self._reset_hint_logged = False
        self._set_state("bootstrapping", "agent_connecting", "Starting micro-ROS agent connection")

        if transport == "serial" and self._firmware_uses_wifi_transport():
            self._last_error = (
                "Detected WiFi micro-ROS firmware; serial transport cannot establish runtime ROS session. "
                "Use transport='udp' (typically port 8888)."
            )
            self._set_state("failed", "agent_unavailable", self._last_error)
            return {"status": "failed", "stage": 1, "message": self._message}

        if transport == "udp":
            cfg = self._wireless_firmware_agent_config()
            host_ip = self._host_lan_ip()
            if cfg:
                cfg_ip = cfg.get("ip", "")
                cfg_port = cfg.get("port", "")
                if cfg_ip and host_ip and cfg_ip != host_ip:
                    self._append_log(
                        f"Firmware AGENT_IP is {cfg_ip}, but host LAN IP appears {host_ip}. "
                        "If these differ, ESP32 cannot reach micro-ROS agent."
                    )
                if cfg_port and str(cfg_port) != str(device_port):
                    self._append_log(
                        f"Firmware AGENT_PORT is {cfg_port}, but middleware UDP port is {device_port}. "
                        "These should match."
                    )

        stale_killed = await self._cleanup_stale_micro_ros_agents(transport=transport, device_port=device_port)
        if stale_killed > 0:
            self._append_log(f"Cleaned {stale_killed} stale micro-ROS agent process(es) before retry")

        agent_connected = False
        for attempt in range(effective_max_retries):
            self._current_attempt = attempt + 1
            try:
                self._append_log(f"Agent connection attempt {attempt + 1}/{effective_max_retries}")
                result = await self._start_agent_and_wait(
                    transport=transport,
                    device_port=device_port,
                    timeout_sec=effective_timeout_sec,
                    reuse_existing=(transport == "udp"),
                )
                success = result["success"]
                fatal = result["fatal"]
                fatal_message = result["message"]

                if success:
                    agent_connected = True
                    self._set_state("bootstrapping", "agent_connected", "Agent session established")
                    break

                self._append_log(f"Agent connection timeout (attempt {attempt + 1})")
                if fatal:
                    self._last_error = fatal_message
                    self._set_state("failed", "agent_unavailable", fatal_message)
                    break

                if attempt < effective_max_retries - 1:
                    backoff_sec = min(8, 2 * (attempt + 1))
                    self._append_log(f"Retrying in {backoff_sec} seconds...")
                    # Keep UDP agent running while waiting for late ESP32 session.
                    if transport != "udp":
                        await self._cleanup_agent()
                    await asyncio.sleep(backoff_sec)
            except Exception as e:
                self._last_error = str(e)
                self._append_log(f"Agent error: {e}")
                await self._cleanup_agent()

        if not agent_connected:
            if self._phase != "agent_unavailable":
                self._set_state(
                    "failed",
                    "agent_failed",
                    f"Agent session not established after {effective_max_retries} attempts",
                )
            await self._cleanup_agent()
            return {"status": "failed", "stage": 1, "message": self._message}

        try:
            self._set_state("bootstrapping", "launch_starting", "Starting hardware bringup launch")
            self._start_hardware_bringup(use_rviz, load_moveit)

            deadline = time.time() + 24.0
            stable_seen_at: Optional[float] = None
            while time.time() < deadline:
                if not self._hardware_process or self._hardware_process.poll() is not None:
                    break
                if self._hardware_ready(use_rviz, load_moveit):
                    if stable_seen_at is None:
                        stable_seen_at = time.time()
                    elif (time.time() - stable_seen_at) >= 1.2:
                        self._set_state("running", "running", "Hardware bootstrap complete")
                        return {
                            "status": "running",
                            "stage": 2,
                            "message": "Real hardware bootstrap complete (agent + launch active)",
                        }
                else:
                    stable_seen_at = None
                await asyncio.sleep(0.3)

            logs = self._tail_hardware_logs()
            self._set_state("failed", "launch_failed", f"Hardware launch did not reach ready state. Recent logs:\n{logs}")
            await self.stop()
            return {"status": "failed", "stage": 2, "message": self._message}
        except Exception as e:
            self._last_error = str(e)
            self._set_state("failed", "launch_failed", f"Hardware launch error: {e}")
            await self._cleanup_agent()
            return {"status": "failed", "stage": 2, "message": f"Hardware launch error: {e}"}

    async def _start_agent_and_wait(
        self,
        transport: str,
        device_port: str,
        timeout_sec: int,
        reuse_existing: bool = False,
    ) -> dict:
        if transport == "serial":
            cmd = [
                "ros2",
                "run",
                "micro_ros_agent",
                "micro_ros_agent",
                "serial",
                "--dev",
                device_port,
                "-b",
                "115200",
            ]
        elif transport == "udp":
            cmd = [
                "ros2",
                "run",
                "micro_ros_agent",
                "micro_ros_agent",
                "udp4",
                "--port",
                str(device_port),
                "-v4",
            ]
        else:
            raise ValueError(f"Unknown transport: {transport}")

        shell_cmd = self._wrap_ros_command(" ".join(cmd))
        self._agent_command = " ".join(shell_cmd)

        try:
            reusing_agent = (
                reuse_existing
                and self._agent_process is not None
                and self._agent_process.poll() is None
            )

            if not reusing_agent:
                self._agent_process = subprocess.Popen(
                    shell_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=self._sanitized_env(),
                    start_new_session=True,
                )
                self._append_log(f"Agent subprocess started (PID {self._agent_process.pid})")
            else:
                self._append_log(f"Reusing running agent process (PID {self._agent_process.pid})")

            start_time = time.time()
            # Important: do not treat generic agent-start text as a valid ESP32 session.
            # Stage 2 must start only after an explicit client/session marker appears.
            session_patterns = [
                r"New session",
                r"Client connected",
                r"session established",
                r"create_client",
                r"create session",
                r"session created",
                r"session re-established",
                r"new client",
                r"create participant",
                r"create publisher",
                r"create subscriber",
            ]

            while time.time() - start_time < timeout_sec:
                if self._agent_process.poll() is not None:
                    self._append_log("Agent process exited before session establishment")
                    break

                try:
                    line = await asyncio.wait_for(
                        asyncio.to_thread(self._agent_process.stdout.readline),
                        timeout=0.5,
                    )
                except asyncio.TimeoutError:
                    if (time.time() - start_time) >= 10 and not self._reset_hint_logged:
                        self._append_log("No micro-ROS client session yet; waiting for ESP32 UDP connection...")
                        self._reset_hint_logged = True
                    continue
                except Exception as e:
                    self._append_log(f"Log reading error: {e}")
                    break

                if not line:
                    continue

                line = line.strip()
                if line:
                    self._append_log(f"agent> {line}")

                if "Package 'micro_ros_agent' not found" in line:
                    return {
                        "success": False,
                        "fatal": True,
                        "message": (
                            "micro_ros_agent package not found. Build/source ~/microros_ws "
                            "(create_agent_ws.sh + build_agent.sh), then retry."
                        ),
                    }

                if "ros2: command not found" in line:
                    return {
                        "success": False,
                        "fatal": True,
                        "message": "ROS 2 environment not found at /opt/ros/jazzy/setup.bash.",
                    }

                for pattern in session_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        self._agent_session_markers.append(line)
                        return {"success": True, "fatal": False, "message": "ok"}

            if transport == "udp":
                self._append_log(
                    "UDP timeout: verify ESP32 is online, AGENT_IP/AGENT_PORT in firmware match this host, "
                    "and ESP32 and host are on the same WiFi network."
                )
            return {"success": False, "fatal": False, "message": "timeout"}
        except Exception as e:
            self._last_error = str(e)
            self._append_log(f"Failed to start agent: {e}")
            return {"success": False, "fatal": True, "message": str(e)}

    def _start_hardware_bringup(self, use_rviz: bool, load_moveit: bool) -> None:
        cmd = [
            "ros2",
            "launch",
            "dexter_arm_hardware",
            "hardware_bringup.launch.py",
            f"use_rviz:={'true' if use_rviz else 'false'}",
            f"load_moveit:={'true' if load_moveit else 'false'}",
        ]
        shell_cmd = self._wrap_ros_command(" ".join(cmd))
        self._hardware_command = " ".join(shell_cmd)

        log_file = tempfile.NamedTemporaryFile(
            mode="w",
            prefix="dexter_hw_launch_",
            suffix=".log",
            delete=False,
            encoding="utf-8",
        )
        self._hardware_log_path = log_file.name

        self._hardware_process = subprocess.Popen(
            shell_cmd,
            stdout=log_file,
            stderr=log_file,
            env=self._sanitized_env(),
            start_new_session=True,
        )
        log_file.close()

        self._append_log(f"Hardware bringup subprocess started (PID {self._hardware_process.pid})")

    async def stop(self) -> dict:
        self._append_log("Stopping hardware + agent (teardown)")

        if self._hardware_process and self._hardware_process.poll() is None:
            self._append_log(f"Terminating hardware launch (PID {self._hardware_process.pid})")
            await self._terminate_process(self._hardware_process, name="hardware_bringup")
            self._hardware_process = None

        if self._agent_process and self._agent_process.poll() is None:
            self._append_log(f"Terminating agent (PID {self._agent_process.pid})")
            await self._terminate_process(self._agent_process, name="agent")
            self._agent_process = None

        self._agent_command = None
        self._agent_session_markers = []
        self._hardware_command = None
        self._hardware_log_path = None
        self._state = "idle"
        self._phase = "idle"
        self._message = "Stopped"
        self._last_error = None
        self._started_at = None
        self._current_attempt = 0
        self._max_attempts = 0
        self._reset_hint_logged = False

        return {
            "agent_terminated": self._agent_process is None,
            "launch_terminated": self._hardware_process is None,
            "message": "Hardware + agent stopped",
        }

    async def force_kill_agent(self) -> dict:
        """Forcefully kill any running micro-ROS agent process(es) without touching hardware launch."""
        rows = self._ps_rows()
        agent_pids: set[int] = set()

        for pid, _ppid, cmd in rows:
            if "micro_ros_agent" in cmd.lower():
                agent_pids.add(pid)

        if self._agent_process and self._agent_process.poll() is None:
            agent_pids.add(self._agent_process.pid)

        killed: list[int] = []
        failed: list[int] = []

        for pid in sorted(agent_pids):
            try:
                pgid = os.getpgid(pid)
                if pgid == pid:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
                killed.append(pid)
                self._append_log(f"Force-killed micro-ROS agent PID {pid}")
            except ProcessLookupError:
                continue
            except Exception as exc:
                failed.append(pid)
                self._append_log(f"Failed to force-kill micro-ROS agent PID {pid}: {exc}")

        if self._agent_process:
            self._agent_process = None
        self._agent_command = None
        self._agent_session_markers = []

        if killed:
            if self._hardware_process and self._hardware_process.poll() is None:
                self._state = "failed"
                self._phase = "agent_force_stopped"
                self._message = "micro-ROS agent force-stopped while hardware launch is still running"
            else:
                self._state = "idle"
                self._phase = "idle"
                self._message = "micro-ROS agent force-stopped"
                self._started_at = None
                self._current_attempt = 0
                self._max_attempts = 0

        return {
            "killed_pids": killed,
            "failed_pids": failed,
            "message": "micro-ROS agent force kill completed",
        }

    def reset_status(self) -> dict:
        self._agent_command = None
        self._agent_transport = None
        self._agent_device = None
        self._agent_session_markers = []
        self._hardware_command = None
        self._hardware_log_path = None
        self._use_rviz = False
        self._load_moveit = False
        self._state = "idle"
        self._phase = "idle"
        self._message = "Idle"
        self._last_error = None
        self._logs = []
        self._started_at = None
        self._current_attempt = 0
        self._max_attempts = 0
        self._reset_hint_logged = False
        return self.status()

    async def _cleanup_agent(self) -> None:
        if self._agent_process and self._agent_process.poll() is None:
            await self._terminate_process(self._agent_process, name="agent")
            self._agent_process = None

    async def _terminate_process(self, proc: subprocess.Popen, name: str, timeout_sec: int = 4) -> None:
        try:
            pid = proc.pid
            await self._terminate_pid(pid=pid, name=name, timeout_sec=timeout_sec)
            for _ in range(timeout_sec * 2):
                if proc.poll() is not None:
                    self._append_log(f"{name} stopped gracefully")
                    return
                await asyncio.sleep(0.5)

            self._append_log(f"Force killing {name} (SIGKILL)")
            proc.kill()
            proc.wait(timeout=2)
        except Exception as e:
            self._append_log(f"Error terminating {name}: {e}")
