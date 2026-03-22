import os
import signal
import subprocess
import time
import tempfile
from pathlib import Path
from dataclasses import dataclass


@dataclass
class MoveitStatus:
    running: bool
    pid: int | None
    command: list[str] | None


class MoveitService:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._command: list[str] | None = None
        self._started_at: float | None = None
        self._log_path: str | None = None

    def _wrap_ros_command(self, ros_command: str) -> list[str]:
        repo_root = Path(__file__).resolve().parents[4]
        ws_setup = repo_root / "install" / "setup.bash"
        wrapped = (
            "source /opt/ros/jazzy/setup.bash && "
            f"if [ -f '{ws_setup}' ]; then source '{ws_setup}'; fi && "
            f"{ros_command}"
        )
        return ["/bin/bash", "-lc", wrapped]

    def _sanitized_env(self) -> dict[str, str]:
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

    def _tail_logs(self, max_lines: int = 40) -> str:
        if not self._log_path:
            return "(no moveit log file)"
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-max_lines:]).strip() or "(moveit log file empty)"
        except Exception:
            return "(failed to read moveit log file)"

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

    def _required_children_present(self) -> bool:
        if not self._process:
            return False
        descendants = self._collect_descendant_pids(self._process.pid)
        if not descendants:
            return False
        has_move_group = False
        has_rviz = False
        for pid, _ppid, cmd in self._ps_rows():
            if pid not in descendants:
                continue
            if "move_group" in cmd:
                has_move_group = True
            if "rviz2" in cmd:
                has_rviz = True
        return has_move_group and has_rviz

    def status(self) -> MoveitStatus:
        if self._process and self._process.poll() is not None:
            self._process = None
            self._command = None
            self._started_at = None

        if self._process and self._started_at is not None and (time.time() - self._started_at) > 2.0:
            if not self._required_children_present():
                self._teardown_process_group()
                self._process = None
                self._command = None
                self._started_at = None

        return MoveitStatus(
            running=self._process is not None,
            pid=self._process.pid if self._process else None,
            command=self._command,
        )

    def start(self, use_sim_time: bool = False) -> MoveitStatus:
        current = self.status()
        if current.running:
            return current

        command = [
            "ros2",
            "launch",
            "dexter_arm_moveit_config",
            "demo.launch.py",
            f"use_sim_time:={'true' if use_sim_time else 'false'}",
        ]
        shell_command = self._wrap_ros_command(" ".join(command))

        try:
            log_file = tempfile.NamedTemporaryFile(
                mode="w",
                prefix="dexter_moveit_",
                suffix=".log",
                delete=False,
                encoding="utf-8",
            )
            self._log_path = log_file.name
            self._process = subprocess.Popen(
                shell_command,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
                env=self._sanitized_env(),
            )
            log_file.close()
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Unable to start MoveIt demo: 'ros2' command not found in middleware environment. "
                "Source the ROS workspace before starting middleware."
            ) from exc

        self._command = shell_command
        self._started_at = time.time()

        time.sleep(0.3)
        if self._process.poll() is not None:
            logs = self._tail_logs()
            self._process = None
            self._command = None
            self._started_at = None
            raise RuntimeError(
                "MoveIt demo launch exited immediately. Ensure install/setup.bash is sourced and MoveIt is installed. "
                f"Recent logs:\n{logs}"
            )

        deadline = time.time() + 8.0
        stable_seen_at: float | None = None
        while time.time() < deadline:
            if self._process.poll() is not None:
                break
            if self._required_children_present():
                if stable_seen_at is None:
                    stable_seen_at = time.time()
                elif (time.time() - stable_seen_at) >= 1.2:
                    return self.status()
            else:
                stable_seen_at = None
            time.sleep(0.2)

        logs = self._tail_logs()
        self.stop()
        raise RuntimeError(
            "MoveIt required processes (rviz2/move_group) did not stay up after launch. "
            f"Recent logs:\n{logs}"
        )

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
            line = line.strip()
            if not line:
                continue
            parts = line.split()
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

    def _kill_pid_if_alive(self, pid: int, sig: int) -> None:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return

        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            return

    def _teardown_process_group(self) -> None:
        if not self._process:
            return
        root_pid = self._process.pid
        descendant_pids = self._collect_descendant_pids(root_pid)

        try:
            os.killpg(root_pid, signal.SIGTERM)
            self._process.wait(timeout=4)
        except Exception:
            try:
                os.killpg(root_pid, signal.SIGKILL)
                self._process.wait(timeout=2)
            except Exception:
                pass

        for pid in sorted(descendant_pids):
            self._kill_pid_if_alive(pid, signal.SIGTERM)
        time.sleep(0.2)
        for pid in sorted(descendant_pids):
            self._kill_pid_if_alive(pid, signal.SIGKILL)

    def stop(self) -> MoveitStatus:
        if not self._process:
            return self.status()

        self._teardown_process_group()

        self._process = None
        self._command = None
        self._started_at = None
        return self.status()
