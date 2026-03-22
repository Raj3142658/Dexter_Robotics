"""
Process Manager for Dexter Arm Dashboard
Manages ROS 2 process launching and monitoring using QProcess.
"""

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
import subprocess
import shutil
import psutil
import os
import threading
import time
from typing import Dict, Optional, List, Tuple
from pathlib import Path


class ProcessManager(QObject):
    """Manages ROS 2 processes launched from the dashboard using QProcess."""
    
    # Signals for process state changes
    processStarted = pyqtSignal(str)  # process_name
    processFinished = pyqtSignal(str, int)  # process_name, exit_code
    processError = pyqtSignal(str, str)  # process_name, error_message
    
    def __init__(self, workspace_dir: str):
        """
        Initialize process manager.
        
        Args:
            workspace_dir: Path to ROS 2 workspace
        """
        super().__init__()
        self.workspace_dir = Path(workspace_dir)
        self.processes: Dict[str, QProcess] = {}
        self.process_info: Dict[str, dict] = {}
        self.ros_distro = self._detect_ros_distro()  # Detect ROS version once on init

        # ── Cached process scanning (runs off main thread) ────────────────
        self._cached_running: Dict[str, bool] = {}   # name → is_running
        self._cached_active_names: list = []          # display names of active processes
        self._cached_active_count: int = 0
        self._pid_cache: Dict[str, int] = {}          # name → last-known PID for O(1) re-check
        self._scan_lock = threading.Lock()
        self._scan_thread: Optional[threading.Thread] = None

        # Background scan timer — fires every 2s, does the heavy psutil work off-thread
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(2000)
        self._scan_timer.timeout.connect(self._start_background_scan)
        self._scan_timer.start()
    
    def _detect_ros_distro(self) -> str:
        """
        Detect ROS_DISTRO by checking environment or /opt/ros directory.
        Same logic as dexter_arm_install.sh
        """
        # Check if ROS_DISTRO is already set in environment
        if 'ROS_DISTRO' in os.environ:
            distro = os.environ['ROS_DISTRO']
            print(f"[INFO] Using ROS_DISTRO from environment: {distro}")
            return distro
        
        # Check /opt/ros for installed distributions
        ros_path = Path('/opt/ros')
        if ros_path.exists():
            try:
                distros = sorted([d.name for d in ros_path.iterdir() if d.is_dir()])
                if distros:
                    ros_distro = distros[-1]  # Get latest
                    print(f"[INFO] Detected ROS_DISTRO: {ros_distro}")
                    return ros_distro
            except Exception as e:
                print(f"[WARN] Could not list /opt/ros: {e}")
        
        # Default to humble if nothing found
        print(f"[WARN] Could not detect ROS_DISTRO, defaulting to 'humble'")
        return "humble"
    
    def launch_command(self, name: str, command: str, use_terminal: bool = True, display_name: str = None) -> bool:
        """
        Launch a ROS 2 command using QProcess.

        Args:
            name: Unique name for this process
            command: Command to execute
            use_terminal: If True, launch in new terminal window
            display_name: Human-readable label shown in the Launched Apps panel

        Returns:
            True if launch successful, False otherwise
        """
        # Don't launch if already running
        if self.is_running(name):
            print(f"[WARNING] Process '{name}' is already running")
            return False
        
        try:
            process = QProcess(self)
            
            # Source ROS setup, then workspace setup, then run command
            ros_setup = f"/opt/ros/{self.ros_distro}/setup.bash"
            full_command = f"source {ros_setup} && cd {self.workspace_dir} && source install/setup.bash && {command}"
            
            if use_terminal:
                terminal = self._find_terminal()
                if terminal:
                    process.setProgram(terminal)
                    args = self._terminal_args(terminal, full_command)
                    process.setArguments(args)
                else:
                    print("[WARN] No terminal emulator found. Running in background.")
                    process.setProgram("/bin/bash")
                    process.setArguments(["-lc", full_command])
            else:
                # Launch in background
                process.setProgram("/bin/bash")
                process.setArguments(["-lc", full_command])
            
            # Connect signals
            process.started.connect(lambda: self._on_process_started(name))
            process.finished.connect(lambda exit_code, exit_status: self._on_process_finished(name, exit_code))
            process.errorOccurred.connect(lambda error: self._on_process_error(name, error))
            
            # Start the process
            process.start()
            
            # Store process
            self.processes[name] = process
            self.process_info[name] = {
                'command': command,
                'terminal': use_terminal,
                'process': process,
                'display_name': display_name or name,
            }
            
            return True
            
        except Exception as e:
            error_msg = f"Error launching {name}: {e}"
            print(f"[ERROR] {error_msg}")
            self.processError.emit(name, str(e))
            return False

    def _find_terminal(self):
        """Find an available terminal emulator."""
        candidates = [
            "gnome-terminal",
            "x-terminal-emulator",
            "konsole",
            "xfce4-terminal",
            "xterm"
        ]
        for name in candidates:
            path = shutil.which(name)
            if path:
                return path
        return None

    def _terminal_args(self, terminal_path: str, command: str):
        """
        Build arguments for the detected terminal emulator.

        Note:
            We intentionally do not append `exec bash` so the terminal closes
            automatically when the launched command exits.
        """
        terminal = Path(terminal_path).name
        if terminal == "gnome-terminal":
            return ["--", "bash", "-lc", command]
        if terminal in {"konsole", "xfce4-terminal", "xterm", "x-terminal-emulator"}:
            return ["-e", "bash", "-lc", command]
        return ["-e", "bash", "-lc", command]
    
    
    def _on_process_started(self, name: str):
        """Handle process started signal."""
        print(f"[INFO] Process '{name}' started")
        self.processStarted.emit(name)
    
    
    def _on_process_finished(self, name: str, exit_code: int):
        """Handle process finished signal."""
        # For terminal processes, delay cleanup - they might still be running
        if name in self.process_info and self.process_info[name].get('terminal', False):
            # Don't clean up immediately - the terminal spawned the process
            # Don't emit finished signal or clean up yet
            return
        
        print(f"[INFO] Process '{name}' finished with exit code {exit_code}")
        self.processFinished.emit(name, exit_code)
        
        # Clean up process after it finishes
        if name in self.processes:
            del self.processes[name]
        if name in self.process_info:
            del self.process_info[name]
    
    def _on_process_error(self, name: str, error: QProcess.ProcessError):
        """Handle process error signal."""
        error_strings = {
            QProcess.ProcessError.FailedToStart: "Failed to start",
            QProcess.ProcessError.Crashed: "Crashed",
            QProcess.ProcessError.Timedout: "Timed out",
            QProcess.ProcessError.WriteError: "Write error",
            QProcess.ProcessError.ReadError: "Read error",
            QProcess.ProcessError.UnknownError: "Unknown error"
        }
        error_msg = error_strings.get(error, "Unknown error")
        print(f"[ERROR] Process '{name}' error: {error_msg}")
        self.processError.emit(name, error_msg)
    
    def kill_process(self, name: str) -> bool:
        """
        Kill a specific process.
        For terminal processes, searches system and kills by command match.
        
        Args:
            name: Name of process to kill
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.process_info:
            print(f"[WARNING] Process '{name}' not found in tracked processes")
            return False
        
        try:
            # For terminal processes, find and kill via psutil
            if self.process_info[name].get('terminal', False):
                command = self.process_info[name]['command']
                killed = self._kill_ros_process(command)
                terminal_closed = False

                # Also close the spawned terminal window process itself.
                if name in self.processes:
                    proc_obj = self.processes[name]
                    try:
                        proc_obj.terminate()
                        if not proc_obj.waitForFinished(2000):
                            proc_obj.kill()
                            proc_obj.waitForFinished(1000)
                        terminal_closed = True
                    except Exception:
                        pass
                
                if killed or terminal_closed:
                    # Clean up tracking
                    if name in self.processes:
                        del self.processes[name]
                    if name in self.process_info:
                        del self.process_info[name]
                    
                    # Emit finished signal
                    self.processFinished.emit(name, 0)
                    return True
                else:
                    print(f"[WARNING] Could not find running process for '{name}'")
                    return False
            
            #For background processes, use QProcess
            if name in self.processes:
                process = self.processes[name]
                
                # Try graceful termination first
                process.terminate()
                
                # Wait up to 5 seconds for termination
                if not process.waitForFinished(5000):
                    # Force kill if termination doesn't work
                    process.kill()
                    process.waitForFinished(2000)
                
                # Clean up
                if name in self.processes:
                    del self.processes[name]
                if name in self.process_info:
                    del self.process_info[name]
                
                return True
            
        except Exception as e:
            print(f"[ERROR] Error killing {name}: {e}")
            return False
        
        return False
    
    def _kill_ros_process(self, command: str) -> bool:
        """
        Find and kill ROS processes matching the command.
        Uses the same robust matching as _is_ros_process_running.
        Recursively kills child processes (e.g., to close Gazebo/RViz windows).
        
        Args:
            command: The ROS launch command
            
        Returns:
            True if at least one process was killed, False otherwise
        """
        # Extract key parts from command for matching (same logic as _is_ros_process_running)
        search_terms = []
        
        if "ros2 launch" in command:
            parts = command.split()
            if len(parts) >= 3:
                package_name = parts[2]
                search_terms.append(package_name)
                if len(parts) >= 4:
                    launch_file = parts[3]
                    search_terms.append(launch_file)
        
        if not search_terms:
            search_terms = [command]
        
        killed_count = 0
        try:
            # Search for processes matching the command
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info['cmdline']
                    if cmdline and isinstance(cmdline, list):
                        cmdline_str = ' '.join(cmdline)
                        # Check if ALL search terms match
                        if all(term in cmdline_str for term in search_terms):
                            print(f"[INFO] Killing process PID {proc.info['pid']}: {proc.info['name']}")
                            
                            # Recursively kill children first
                            children = proc.children(recursive=True)
                            for child in children:
                                try:
                                    print(f"[DEBUG] Killing child PID {child.pid}")
                                    child.terminate()
                                except psutil.NoSuchProcess:
                                    pass
                            
                            # Kill parent
                            proc.terminate()
                            proc.wait(timeout=3)
                            killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    continue
        except Exception as e:
            print(f"[ERROR] Error killing ROS process: {e}")
        
        return killed_count > 0
    
    def kill_all_ros(self) -> None:
        """Kill all ROS-related processes system-wide."""
        self.kill_all_ros_with_report()

    def kill_all_ros_with_report(self) -> List[Tuple[str, str]]:
        """
        Kill all ROS-related processes and return status messages.

        Returns:
            List of (target, message) rows for UI logging.
        """
        default_targets = [
            "ros2",
            "gazebo",
            "rviz",
            "move_group",
            "controller_manager",
            "micro_ros_agent",
        ]
        return self.kill_selected_targets(default_targets)

    def kill_selected_targets(
        self,
        target_ids: List[str],
        serial_port: str = "/dev/ttyUSB0",
    ) -> List[Tuple[str, str]]:
        """
        Kill selected process groups and return status messages.

        Args:
            target_ids: Target identifiers to kill
            serial_port: Serial port used for "port_users" target

        Returns:
            List of (target_id, message) rows.
        """
        report: List[Tuple[str, str]] = []
        ran_kill_command = False

        for target_id in target_ids:
            # First close tracked launch sessions associated with this target.
            tracked_closed = self._kill_tracked_processes_for_target(target_id)
            if tracked_closed > 0:
                report.append(
                    (
                        target_id,
                        f"Closed {tracked_closed} tracked launch terminal(s)",
                    )
                )

            if target_id == "port_users":
                report.append(("port_users", self._kill_port_users(serial_port)))
                continue

            if target_id == "ros2":
                ran_kill_command = True
                msg = self._kill_by_match(
                    target_name="ROS 2",
                    cmd_terms=["ros2"],
                    name_terms=["ros2"],
                    exclude_terms=["dexter_arm_dashboard"],
                )
                report.append((target_id, msg))
                continue

            if target_id == "gazebo":
                ran_kill_command = True
                msg = self._kill_by_match(
                    target_name="Gazebo",
                    cmd_terms=["gazebo", "gzserver", "gzclient"],
                    name_terms=["gazebo", "gzserver", "gzclient"],
                    exclude_terms=[],
                )
                report.append((target_id, msg))
                continue

            if target_id == "rviz":
                ran_kill_command = True
                msg = self._kill_by_match(
                    target_name="RViz",
                    cmd_terms=["rviz"],
                    name_terms=["rviz", "rviz2"],
                    exclude_terms=[],
                )
                report.append((target_id, msg))
                continue

            if target_id == "move_group":
                ran_kill_command = True
                msg = self._kill_by_match(
                    target_name="MoveIt",
                    cmd_terms=["move_group"],
                    name_terms=["move_group"],
                    exclude_terms=[],
                )
                report.append((target_id, msg))
                continue

            if target_id == "controller_manager":
                ran_kill_command = True
                msg = self._kill_by_match(
                    target_name="Controller Manager",
                    cmd_terms=["controller_manager"],
                    name_terms=["controller_manager"],
                    exclude_terms=[],
                )
                report.append((target_id, msg))
                continue

            if target_id == "micro_ros_agent":
                ran_kill_command = True
                msg = self._kill_by_match(
                    target_name="micro-ROS Agent",
                    cmd_terms=["micro_ros_agent"],
                    name_terms=["micro_ros_agent"],
                    exclude_terms=[],
                )
                report.append((target_id, msg))
                continue

            report.append((target_id, f"Unknown target: {target_id}"))

        if ran_kill_command:
            # Keep dashboard process state consistent with system-wide kills.
            self.processes.clear()
            self.process_info.clear()

        return report

    def _kill_tracked_processes_for_target(self, target_id: str) -> int:
        """
        Kill tracked launched sessions related to a logical target.

        Returns:
            Number of tracked process entries killed.
        """
        target_launch_terms = {
            "rviz": [
                "dexter_arm_description view_model.launch.py",
                "dexter_arm_moveit_config demo.launch.py",
            ],
            "move_group": [
                "dexter_arm_moveit_config demo.launch.py",
                "dexter_arm_gazebo gazebo_bringup.launch.py",
                "dexter_arm_hardware hardware_bringup.launch.py",
            ],
            "gazebo": [
                "dexter_arm_gazebo gazebo.launch.py",
                "dexter_arm_gazebo gazebo_bringup.launch.py",
            ],
        }

        terms = target_launch_terms.get(target_id)
        if not terms:
            return 0

        killed_count = 0
        for process_name, info in list(self.process_info.items()):
            command = str(info.get('command', '')).lower()
            if any(term in command for term in terms):
                if self.kill_process(process_name):
                    killed_count += 1

        return killed_count

    def _kill_by_match(
        self,
        target_name: str,
        cmd_terms: List[str],
        name_terms: List[str],
        exclude_terms: List[str],
    ) -> str:
        """
        Kill processes matching cmdline or process-name terms.

        Args:
            target_name: Display name used in status text
            cmd_terms: Substrings matched against full command line
            name_terms: Substrings matched against process name
            exclude_terms: Substrings that should prevent a match

        Returns:
            Human-readable status message.
        """
        cmd_terms_l = [t.lower() for t in cmd_terms if t]
        name_terms_l = [t.lower() for t in name_terms if t]
        exclude_terms_l = [t.lower() for t in exclude_terms if t]

        protected_pids = {os.getpid(), os.getppid()}
        matches = []

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.pid in protected_pids:
                    continue

                cmdline_list = proc.info.get('cmdline') or []
                cmdline = " ".join(cmdline_list).lower()
                name = (proc.info.get('name') or "").lower()

                if any(term in cmdline for term in exclude_terms_l):
                    continue

                cmd_match = any(term in cmdline for term in cmd_terms_l)
                name_match = any(term in name for term in name_terms_l)
                if cmd_match or name_match:
                    matches.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Deduplicate by PID before acting.
        unique = {}
        for proc in matches:
            unique[proc.pid] = proc
        matches = list(unique.values())

        if not matches:
            return f"No {target_name} processes found"

        killed = 0
        denied = 0
        failed = 0
        processed = set()

        for proc in matches:
            if proc.pid in processed:
                continue
            processed.add(proc.pid)

            try:
                # Terminate descendants first to avoid orphaned subprocesses.
                for child in proc.children(recursive=True):
                    if child.pid in protected_pids or child.pid in processed:
                        continue
                    processed.add(child.pid)
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.ZombieProcess):
                        continue
                    except psutil.AccessDenied:
                        denied += 1
                    except Exception:
                        failed += 1

                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
                killed += 1
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied:
                denied += 1
            except Exception:
                failed += 1

        if killed == 0 and denied == 0 and failed == 0:
            return f"No {target_name} processes found"

        message = f"Killed {killed} {target_name} process(es)"
        if denied > 0:
            message += f", permission denied {denied}"
        if failed > 0:
            message += f", failed {failed}"
        return message

    def _kill_port_users(self, serial_port: str) -> str:
        """
        Kill processes currently using a serial port.

        Args:
            serial_port: e.g. /dev/ttyUSB0

        Returns:
            Human-readable status message.
        """
        if not serial_port:
            return "Serial port is empty"

        port_path = Path(serial_port)
        if not port_path.exists():
            return f"Port {serial_port} not found"

        pids: List[int] = []

        # First try lsof (most reliable for tty usage).
        if shutil.which("lsof"):
            try:
                result = subprocess.run(
                    ["lsof", "-t", serial_port],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if result.stdout.strip():
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line.isdigit():
                            pids.append(int(line))
            except Exception:
                pass

        # Fallback to fuser when lsof returns nothing.
        if not pids and shutil.which("fuser"):
            try:
                result = subprocess.run(
                    ["fuser", serial_port],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                text = (result.stdout or "") + " " + (result.stderr or "")
                for token in text.split():
                    if token.isdigit():
                        pids.append(int(token))
            except Exception:
                pass

        unique_pids = sorted(set(pids))
        if not unique_pids:
            return f"No processes found using {serial_port}"

        killed = 0
        denied = 0
        failed = 0

        for pid in unique_pids:
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
                killed += 1
            except psutil.AccessDenied:
                denied += 1
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                failed += 1
            except Exception:
                failed += 1

        summary = f"Killed {killed} process(es) using {serial_port}"
        if denied > 0:
            summary += f", permission denied for {denied}"
        if failed > 0:
            summary += f", failed {failed}"
        return summary
    
    
    
    # ──────────────────────────────────────────────────────────────────────
    # Cached process status (non-blocking, main-thread safe)
    # ──────────────────────────────────────────────────────────────────────

    def is_running(self, name: str) -> bool:
        """Return cached running status (instant, non-blocking).

        For background QProcess entries the live QProcess.state() is checked
        (this is already O(1)). For terminal processes the result comes from
        the last background scan.
        """
        info = self.process_info.get(name)
        if info is None:
            return False

        # Background processes: direct QProcess state check is cheap & live
        if not info.get('terminal', False):
            if name in self.processes:
                return self.processes[name].state() != QProcess.ProcessState.NotRunning
            return False

        # Terminal processes: return cached result from background scan
        return self._cached_running.get(name, False)

    def get_active_count(self) -> int:
        """Return cached active-process count (instant)."""
        return self._cached_active_count

    def get_active_processes(self) -> list:
        """Return cached list of active-process display names (instant)."""
        return list(self._cached_active_names)

    # ── background scan (runs on a daemon thread, never blocks UI) ────────

    def _start_background_scan(self) -> None:
        """Kick off a background thread to refresh the process cache."""
        if self._scan_thread is not None and self._scan_thread.is_alive():
            return  # previous scan still running, skip

        # Snapshot the data needed by the scanner (all read-only on this thread)
        names = list(self.process_info.keys())
        infos = {n: dict(self.process_info[n]) for n in names if n in self.process_info}
        proc_states = {
            n: (self.processes[n].state() != QProcess.ProcessState.NotRunning)
            for n in names if n in self.processes
        }
        pid_cache_snapshot = dict(self._pid_cache)

        self._scan_thread = threading.Thread(
            target=self._bg_scan,
            args=(names, infos, proc_states, pid_cache_snapshot),
            daemon=True,
        )
        self._scan_thread.start()

    def _bg_scan(
        self,
        names: list,
        infos: dict,
        proc_states: dict,
        pid_cache: dict,
    ) -> None:
        """Heavy psutil work — runs entirely off the main thread."""
        running_map: Dict[str, bool] = {}
        active_names: list = []
        active_count = 0
        new_pid_cache: Dict[str, int] = {}
        dead_names: list = []

        for name in names:
            info = infos.get(name)
            if info is None:
                continue

            if info.get('terminal', False):
                command = info.get('command', '')
                alive, pid = self._is_ros_process_running_cached(command, pid_cache.get(name))
                running_map[name] = alive
                if alive:
                    active_count += 1
                    active_names.append(info.get('display_name', name))
                    if pid:
                        new_pid_cache[name] = pid
                else:
                    dead_names.append(name)
            else:
                alive = proc_states.get(name, False)
                running_map[name] = alive
                if alive:
                    active_count += 1
                    active_names.append(info.get('display_name', name))
                else:
                    dead_names.append(name)

        # Publish results back — the timer callback on the main thread will
        # pick these up on the next tick.
        with self._scan_lock:
            self._cached_running = running_map
            self._cached_active_count = active_count
            self._cached_active_names = active_names
            self._pid_cache = new_pid_cache
            self._pending_dead = dead_names

        # Schedule cleanup of dead entries on the main thread via a 0-ms single-shot
        QTimer.singleShot(0, self._cleanup_dead_entries)

    def _cleanup_dead_entries(self) -> None:
        """Remove confirmed-dead processes from tracking (runs on main thread)."""
        with self._scan_lock:
            dead = getattr(self, '_pending_dead', [])
            self._pending_dead = []

        for name in dead:
            if name in self.processes:
                del self.processes[name]
            if name in self.process_info:
                del self.process_info[name]

    @staticmethod
    def _extract_search_terms(command: str) -> list:
        """Extract key search terms from a ROS command string."""
        search_terms = []
        if "ros2 launch" in command:
            parts = command.split()
            if len(parts) >= 3:
                search_terms.append(parts[2])  # package name
            if len(parts) >= 4:
                search_terms.append(parts[3])  # launch file
        if not search_terms:
            search_terms = [command]
        return search_terms

    def _is_ros_process_running_cached(self, command: str, cached_pid: Optional[int] = None) -> tuple:
        """Check if a ROS command is running. Returns (alive, pid).

        First tries the cached PID (O(1)), then falls back to a full scan.
        """
        search_terms = self._extract_search_terms(command)

        # Fast path: re-check the previously known PID
        if cached_pid is not None:
            try:
                proc = psutil.Process(cached_pid)
                cmdline = proc.cmdline()
                if cmdline:
                    cmdline_str = ' '.join(cmdline)
                    if all(term in cmdline_str for term in search_terms):
                        return (True, cached_pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # Slow path: full process table scan
        try:
            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline')
                    if cmdline and isinstance(cmdline, list):
                        cmdline_str = ' '.join(cmdline)
                        if all(term in cmdline_str for term in search_terms):
                            return (True, proc.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        return (False, None)
    
    def cleanup(self) -> None:
        """Clean up all processes on shutdown."""
        self._scan_timer.stop()
        print("[INFO] Cleaning up all processes...")
        for name in list(self.processes.keys()):
            self.kill_process(name)
