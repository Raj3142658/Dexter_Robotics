import os
import signal
import subprocess
import time
import tempfile
from pathlib import Path
from dataclasses import dataclass


@dataclass
class RvizStatus:
    running: bool
    pid: int | None
    command: list[str] | None


class RvizService:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._command: list[str] | None = None
        self._started_at: float | None = None
        self._log_path: str | None = None

    def _ps_rows(self) -> list[tuple[int, int, str]]:
        """Return process rows as (pid, ppid, command)."""
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
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
            except ValueError:
                continue
            rows.append((pid, ppid, parts[2]))
        return rows

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
        """
        Remove SNAP-related runtime pollution that can break ROS GUI binaries.
        """
        env = os.environ.copy()

        for key in list(env.keys()):
            if key.startswith("SNAP"):
                env.pop(key, None)

        # Drop known GUI/runtime variables injected by VS Code Snap runtime.
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

        # Restore non-snap XDG_DATA_DIRS if available.
        xdg_orig = os.environ.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG")
        if xdg_orig:
            env["XDG_DATA_DIRS"] = xdg_orig

        # Remove snap entries from PATH too.
        path = env.get("PATH", "")
        if path:
            kept_path = [p for p in path.split(":") if p and "/snap/" not in p]
            env["PATH"] = ":".join(kept_path)

        ld_path = env.get("LD_LIBRARY_PATH", "")
        if ld_path:
            kept = [p for p in ld_path.split(":") if p and "/snap/" not in p]
            if kept:
                env["LD_LIBRARY_PATH"] = ":".join(kept)
            else:
                env.pop("LD_LIBRARY_PATH", None)

        return env

    def _rviz_child_present(self) -> bool:
        if not self._process:
            return False
        root_pid = self._process.pid
        descendants = self._collect_descendant_pids(root_pid)
        if not descendants:
            return False

        for pid, _ppid, cmd in self._ps_rows():
            if pid in descendants and "rviz2" in cmd:
                return True
        return False

    def _tail_logs(self, max_lines: int = 30) -> str:
        if not self._log_path:
            return "(no rviz log file)"
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-max_lines:]).strip() or "(rviz log file empty)"
        except Exception:
            return "(failed to read rviz log file)"

    def status(self) -> RvizStatus:
        if self._process and self._process.poll() is not None:
            self._process = None
            self._command = None
            self._started_at = None

        # Guard against a launch process that is alive but rviz2 has already failed.
        if self._process and self._started_at is not None and (time.time() - self._started_at) > 2.0:
            if not self._rviz_child_present():
                self._teardown_process_group()
                self._process = None
                self._command = None
                self._started_at = None

        return RvizStatus(
            running=self._process is not None,
            pid=self._process.pid if self._process else None,
            command=self._command,
        )

    def start(self, gui: bool = True) -> RvizStatus:
        current = self.status()
        if current.running:
            return current

        if gui and not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "RViz requires a GUI display, but DISPLAY is not set in middleware environment. "
                "Launch from desktop session or export DISPLAY before starting middleware."
            )

        command = [
            "ros2",
            "launch",
            "dexter_arm_description",
            "view_model.launch.py",
            f"gui:={'true' if gui else 'false'}",
        ]
        shell_command = self._wrap_ros_command(" ".join(command))

        # start_new_session=True creates a process group for clean stop handling.
        try:
            log_file = tempfile.NamedTemporaryFile(
                mode="w",
                prefix="dexter_rviz_",
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
                "Unable to start RViz: 'ros2' command not found in middleware environment. "
                "Source the ROS workspace before starting middleware."
            ) from exc

        self._command = shell_command
        self._started_at = time.time()

        # If launch exits immediately, surface a clear startup failure to callers.
        time.sleep(0.2)
        if self._process.poll() is not None:
            logs = self._tail_logs()
            self._process = None
            self._command = None
            self._started_at = None
            raise RuntimeError(
                "RViz launch exited immediately. Ensure install/setup.bash is sourced and a GUI session is available. "
                f"Recent logs:\n{logs}"
            )

        # Wait for actual rviz2 child and ensure it stays alive briefly.
        deadline = time.time() + 5.0
        stable_seen_at: float | None = None
        while time.time() < deadline:
            if self._process.poll() is not None:
                break
            if self._rviz_child_present():
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
            "RViz process did not appear after launch start. "
            "Check GUI availability and RViz dependencies. "
            f"Recent logs:\n{logs}"
        )

    def _collect_descendant_pids(self, root_pid: int) -> set[int]:
        """Return all descendants for a process id using a parent map from ps output."""
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
        except ProcessLookupError:
            return
        except PermissionError:
            return

        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            return

    def _teardown_process_group(self) -> None:
        if not self._process:
            return

        root_pid = self._process.pid
        descendant_pids = self._collect_descendant_pids(root_pid)

        try:
            os.killpg(root_pid, signal.SIGTERM)
            self._process.wait(timeout=3)
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

    def stop(self) -> RvizStatus:
        if not self._process:
            return self.status()

        self._teardown_process_group()

        self._process = None
        self._command = None
        self._started_at = None
        return self.status()
