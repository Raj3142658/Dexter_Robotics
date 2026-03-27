const API_BASE = "http://127.0.0.1:8080";
const WS_URL = "ws://127.0.0.1:8080/ws/events";

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");

const rvizStatusEl = document.getElementById("rvizStatus");
const moveitStatusEl = document.getElementById("moveitStatus");
const gazeboStatusEl = document.getElementById("gazeboStatus");
const fullStackStatusEl = document.getElementById("fullStackStatus");
const hardwareStatusEl = document.getElementById("hardwareStatus");
const healthStatusEl = document.getElementById("healthStatus");
const systemMonitorStatusEl = document.getElementById("systemMonitorStatus");
const systemCleanupStatusEl = document.getElementById("systemCleanupStatus");
const firmwareMdnsStatusEl = document.getElementById("firmwareMdnsStatus");
const firmwareUploadStatusEl = document.getElementById("firmwareUploadStatus");
const firmwareUploadLogEl = document.getElementById("firmwareUploadLog");
const teachStatusEl = document.getElementById("teachStatus");
const teachLogEl = document.getElementById("teachLog");

const modelLogEl = document.getElementById("modelLog");
const plannerLogEl = document.getElementById("plannerLog");
const gazeboLogEl = document.getElementById("gazeboLog");
const fullStackLogEl = document.getElementById("fullStackLog");

const hardwareSessionStateEl = document.getElementById("hardwareSessionState");
const hardwareSessionHintEl = document.getElementById("hardwareSessionHint");
const hardwareSessionLogEl = document.getElementById("hardwareSessionLog");

let hardwarePollTimer = null;
let firmwarePollTimer = null;
let liveStatusTimer = null;

function nowTime() {
  return new Date().toLocaleTimeString();
}

function prependLine(el, line) {
  const withTs = `[${nowTime()}] ${line}`;
  el.textContent = `${withTs}\n${el.textContent}`.trim();
}

function logGlobal(line) {
  prependLine(eventsEl, line);
}

function logPanel(panel, line) {
  const map = {
    model: modelLogEl,
    planner: plannerLogEl,
    gazebo: gazeboLogEl,
    fullstack: fullStackLogEl,
  };
  if (map[panel]) {
    prependLine(map[panel], line);
  }
}

function selectedHardwareDevicePort() {
  const transport = document.getElementById("hardwareTransport").value;
  if (transport === "udp") {
    return String(document.getElementById("hardwareUdpPort").value || "8888");
  }
  return document.getElementById("hardwareSerialDevice").value || "/dev/ttyUSB0";
}

function updateHardwareTransportFields() {
  const transport = document.getElementById("hardwareTransport").value;
  const serialField = document.getElementById("serialField");
  const udpField = document.getElementById("udpField");

  if (transport === "serial") {
    serialField.style.display = "";
    udpField.style.display = "none";
    document.getElementById("hardwareSerialDevice").value = "/dev/ttyUSB0";
  } else {
    serialField.style.display = "none";
    udpField.style.display = "";
    document.getElementById("hardwareUdpPort").value = "8888";
  }
}

function renderHardwareSessionUi(data) {
  const phase = data.phase || "idle";
  const state = data.state || "idle";
  const elapsed = Number(data.elapsed_sec || 0);
  const attempt = Number(data.current_attempt || 0);
  const maxAttempts = Number(data.max_attempts || 0);
  const logs = Array.isArray(data.session_logs) ? data.session_logs : [];

  hardwareSessionStateEl.textContent = `${state} | ${phase} | ${elapsed}s`;

  let hintMessage = data.message || "Idle";
  if (state === "bootstrapping" && phase === "agent_connecting") {
    hintMessage = `Establishing micro-ROS session... attempt ${attempt}/${maxAttempts || "?"} (${elapsed}s elapsed)`;
  }
  if (data.last_error) {
    hintMessage += `\nLast error: ${data.last_error}`;
  }

  hardwareSessionHintEl.textContent = hintMessage;
  hardwareSessionLogEl.textContent = logs.length ? logs.join("\n") : "No session logs yet.";
}

function applySnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") {
    return;
  }

  if (snapshot.rviz) rvizStatusEl.textContent = JSON.stringify(snapshot.rviz, null, 2);
  if (snapshot.moveit) moveitStatusEl.textContent = JSON.stringify(snapshot.moveit, null, 2);
  if (snapshot.gazebo) gazeboStatusEl.textContent = JSON.stringify(snapshot.gazebo, null, 2);
  if (snapshot.full_stack) fullStackStatusEl.textContent = JSON.stringify(snapshot.full_stack, null, 2);
  if (snapshot.hardware) {
    hardwareStatusEl.textContent = JSON.stringify(snapshot.hardware, null, 2);
    renderHardwareSessionUi(snapshot.hardware);

    const st = String(snapshot.hardware.state || "");
    if (st === "bootstrapping") {
      startHardwarePolling();
    } else if (st === "running" || st === "failed" || st === "idle") {
      stopHardwarePolling();
    }
  }
}

function startHardwarePolling() {
  if (hardwarePollTimer) {
    clearInterval(hardwarePollTimer);
  }
  hardwarePollTimer = setInterval(() => {
    getHardwareStatus();
  }, 1200);
}

function stopHardwarePolling() {
  if (hardwarePollTimer) {
    clearInterval(hardwarePollTimer);
    hardwarePollTimer = null;
  }
}

function startLiveStatusRefresh() {
  if (liveStatusTimer) {
    return;
  }
  liveStatusTimer = setInterval(() => {
    getStatus();
    getHardwareStatus();
    getFirmwareUploadStatus();
  }, 1800);
}

function parsePortList(raw) {
  return String(raw || "")
    .split(",")
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isInteger(v) && v > 0 && v <= 65535);
}

function updateFirmwareMethodFields() {
  const method = document.getElementById("firmwareMethod")?.value || "serial";
  const serialVisible = method === "serial";
  const otaVisible = method === "ota";

  const serialPortField = document.getElementById("firmwareSerialPortField");
  const serialBaudField = document.getElementById("firmwareSerialBaudField");
  const otaIpField = document.getElementById("firmwareOtaIpField");
  const otaPasswordField = document.getElementById("firmwareOtaPasswordField");

  if (serialPortField) serialPortField.style.display = serialVisible ? "" : "none";
  if (serialBaudField) serialBaudField.style.display = serialVisible ? "" : "none";
  if (otaIpField) otaIpField.style.display = otaVisible ? "" : "none";
  if (otaPasswordField) otaPasswordField.style.display = otaVisible ? "" : "none";
}

function activateTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  });
}

async function getStatus() {
  const res = await fetch(`${API_BASE}/status`);
  const data = await res.json();
  statusEl.textContent = JSON.stringify(data, null, 2);
  applySnapshot(data);
}

async function getHealthStatus() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    const data = await res.json();
    healthStatusEl.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    healthStatusEl.textContent = `Failed to fetch health: ${err.message}`;
  }
}

async function getSystemMonitorStatus() {
  try {
    const res = await fetch(`${API_BASE}/system/monitor`);
    const data = await res.json();
    systemMonitorStatusEl.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    systemMonitorStatusEl.textContent = `Failed to fetch system monitor: ${err.message}`;
  }
}

async function runSystemCleanup() {
  const payload = {
    ports: parsePortList(document.getElementById("cleanupPorts")?.value),
    serial_port: document.getElementById("cleanupSerialPort")?.value || "/dev/ttyUSB0",
    include_port_cleanup: (document.getElementById("cleanupPortsEnabled")?.value || "true") === "true",
    include_serial_cleanup: (document.getElementById("cleanupSerialEnabled")?.value || "true") === "true",
  };

  const ok = window.confirm("Run system cleanup (stop sessions + cleanup selected resources)?");
  if (!ok) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/system/cleanup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    systemCleanupStatusEl.textContent = JSON.stringify(data, null, 2);
    if (!res.ok) {
      logGlobal(`ERROR /system/cleanup: ${JSON.stringify(data)}`);
      return;
    }
    logGlobal("OK /system/cleanup");
    await Promise.all([getStatus(), getSystemMonitorStatus(), getHardwareStatus()]);
  } catch (err) {
    systemCleanupStatusEl.textContent = `Cleanup failed: ${err.message}`;
  }
}

function renderFirmwareFiles(data) {
  const select = document.getElementById("firmwareFileSelect");
  if (!select) {
    return;
  }
  const files = Array.isArray(data?.files) ? data.files : [];

  select.innerHTML = "";
  if (!files.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No firmware files found";
    select.appendChild(opt);
    return;
  }

  for (const file of files) {
    const opt = document.createElement("option");
    opt.value = file.name;
    opt.textContent = `${file.name} (${file.size_bytes} bytes)`;
    select.appendChild(opt);
  }
}

function renderFirmwareStatus(data) {
  firmwareUploadStatusEl.textContent = JSON.stringify(data, null, 2);
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  firmwareUploadLogEl.textContent = logs.length ? logs.join("\n") : "No firmware logs yet.";
}

async function getFirmwareSerialPorts() {
  const select = document.getElementById("firmwareSerialPortSelect");
  if (!select) {
    return;
  }

  const current = select.value;
  try {
    const res = await fetch(`${API_BASE}/firmware/serial-ports`);
    const data = await res.json();
    const ports = Array.isArray(data?.ports) ? data.ports : [];

    select.innerHTML = "";
    if (!ports.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No serial ports detected";
      select.appendChild(opt);
      return;
    }

    for (const p of ports) {
      const path = String(p?.path || "");
      if (!path) continue;
      const busy = Boolean(p?.busy);
      const desc = String(p?.description || "Serial Device");
      const label = busy ? `${path} (${desc}, busy)` : `${path} (${desc})`;
      const opt = document.createElement("option");
      opt.value = path;
      opt.textContent = label;
      select.appendChild(opt);
    }

    if (current && ports.some((p) => String(p?.path || "") === current)) {
      select.value = current;
    } else if (typeof data?.suggested_port === "string" && data.suggested_port) {
      select.value = data.suggested_port;
    }
  } catch (err) {
    select.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = `Port detection failed: ${err.message}`;
    select.appendChild(opt);
  }
}

async function getFirmwareFiles() {
  try {
    const res = await fetch(`${API_BASE}/firmware/files`);
    const data = await res.json();
    renderFirmwareFiles(data);
  } catch (err) {
    firmwareUploadStatusEl.textContent = `Failed to fetch firmware files: ${err.message}`;
  }
}

async function getFirmwareUploadStatus() {
  try {
    const res = await fetch(`${API_BASE}/firmware/upload/status`);
    const data = await res.json();
    renderFirmwareStatus(data);

    if (data.running) {
      if (!firmwarePollTimer) {
        firmwarePollTimer = setInterval(() => {
          getFirmwareUploadStatus();
        }, 1200);
      }
    } else if (firmwarePollTimer) {
      clearInterval(firmwarePollTimer);
      firmwarePollTimer = null;
    }
  } catch (err) {
    firmwareUploadStatusEl.textContent = `Failed to fetch firmware status: ${err.message}`;
    if (firmwarePollTimer) {
      clearInterval(firmwarePollTimer);
      firmwarePollTimer = null;
    }
  }
}

async function firmwareMdnsLookup() {
  try {
    const res = await fetch(`${API_BASE}/firmware/mdns-lookup`);
    const data = await res.json();
    firmwareMdnsStatusEl.textContent = JSON.stringify(data, null, 2);
    if (data.success && data.ip && document.getElementById("firmwareMethod")?.value === "ota") {
      document.getElementById("firmwareOtaIp").value = data.ip;
    }
  } catch (err) {
    firmwareMdnsStatusEl.textContent = `mDNS lookup failed: ${err.message}`;
  }
}

async function startFirmwareUpload() {
  const filename = document.getElementById("firmwareFileSelect")?.value || "";
  if (!filename) {
    firmwareUploadStatusEl.textContent = "Select a firmware file first.";
    return;
  }

  const method = document.getElementById("firmwareMethod")?.value || "serial";
  const payload = {
    filename,
    method,
    serial_port: document.getElementById("firmwareSerialPortSelect")?.value || "",
    serial_baud: Number(document.getElementById("firmwareSerialBaud")?.value || 921600),
    fqbn: document.getElementById("firmwareFqbn")?.value || "esp32:esp32:esp32",
    ota_ip: document.getElementById("firmwareOtaIp")?.value || "",
    ota_password: document.getElementById("firmwareOtaPassword")?.value || "",
  };

  if (method === "serial" && !payload.serial_port.trim()) {
    firmwareUploadStatusEl.textContent = "No serial port detected. Click Detect Serial Ports and reconnect ESP32.";
    return;
  }

  if (method === "ota" && !payload.ota_ip.trim()) {
    firmwareUploadStatusEl.textContent = "OTA method requires OTA IP/hostname.";
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/firmware/upload/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    firmwareUploadStatusEl.textContent = JSON.stringify(data, null, 2);
    if (!res.ok) {
      logGlobal(`ERROR /firmware/upload/start: ${JSON.stringify(data)}`);
      return;
    }

    logGlobal(`OK /firmware/upload/start (${filename})`);
    await getFirmwareUploadStatus();
  } catch (err) {
    firmwareUploadStatusEl.textContent = `Firmware upload request failed: ${err.message}`;
  }
}

async function getRvizStatus() {
  try {
    const res = await fetch(`${API_BASE}/ros/rviz/status`);
    const data = await res.json();
    rvizStatusEl.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    rvizStatusEl.textContent = `Failed to fetch status: ${err.message}`;
  }
}

async function getMoveitStatus() {
  try {
    const res = await fetch(`${API_BASE}/ros/moveit/status`);
    const data = await res.json();
    moveitStatusEl.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    moveitStatusEl.textContent = `Failed to fetch status: ${err.message}`;
  }
}

async function getGazeboStatus() {
  try {
    const res = await fetch(`${API_BASE}/ros/gazebo/status`);
    const data = await res.json();
    gazeboStatusEl.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    gazeboStatusEl.textContent = `Failed to fetch status: ${err.message}`;
  }
}

async function getFullStackStatus() {
  try {
    const res = await fetch(`${API_BASE}/ros/full-stack/status`);
    const data = await res.json();
    fullStackStatusEl.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    fullStackStatusEl.textContent = `Failed to fetch status: ${err.message}`;
  }
}

async function getHardwareStatus() {
  try {
    const res = await fetch(`${API_BASE}/ros/hardware/status`);
    const data = await res.json();
    hardwareStatusEl.textContent = JSON.stringify(data, null, 2);
    renderHardwareSessionUi(data);

    if (data.state === "running" || data.state === "failed" || data.state === "idle") {
      stopHardwarePolling();
    }
  } catch (err) {
    hardwareStatusEl.textContent = `Failed to fetch hardware status: ${err.message}`;
    hardwareSessionHintEl.textContent = `Failed to fetch session status: ${err.message}`;
  }
}

async function callApi(path, body) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });

    const data = await res.json();
    if (!res.ok) {
      logGlobal(`ERROR ${path}: ${JSON.stringify(data)}`);
      return { ok: false, data };
    }

    logGlobal(`OK ${path}`);
    await getStatus();
    return { ok: true, data };
  } catch (err) {
    logGlobal(`NETWORK ${path}: ${err.message}`);
    return { ok: false, data: { detail: err.message } };
  }
}

function wireTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });
}

function wireModelViewer() {
  document.getElementById("rvizStart").addEventListener("click", async () => {
    await callApi("/ros/rviz/start", {
      gui: document.getElementById("rvizGui").value === "true",
    });
    await getRvizStatus();
    logPanel("model", "Model viewer start requested");
  });

  document.getElementById("rvizStop").addEventListener("click", async () => {
    await callApi("/ros/rviz/stop");
    await getRvizStatus();
    logPanel("model", "Model viewer stop requested");
  });

  document.getElementById("rvizStatusBtn").addEventListener("click", async () => {
    await getRvizStatus();
    logPanel("model", "Model viewer status refreshed");
  });
}

function wirePlanner() {
  document.getElementById("moveitStart").addEventListener("click", async () => {
    await callApi("/ros/moveit/start", {
      use_sim_time: document.getElementById("moveitUseSimTime").value === "true",
    });
    await getMoveitStatus();
    logPanel("planner", "Motion planner start requested");
  });

  document.getElementById("moveitStop").addEventListener("click", async () => {
    await callApi("/ros/moveit/stop");
    await getMoveitStatus();
    logPanel("planner", "Motion planner stop requested");
  });

  document.getElementById("moveitStatusBtn").addEventListener("click", async () => {
    await getMoveitStatus();
    logPanel("planner", "Motion planner status refreshed");
  });
}

function wireGazebo() {
  document.getElementById("gazeboStart").addEventListener("click", async () => {
    await callApi("/ros/gazebo/start", {
      gui: document.getElementById("gazeboGui").value === "true",
    });
    await getGazeboStatus();
    logPanel("gazebo", "Gazebo start requested");
  });

  document.getElementById("gazeboStop").addEventListener("click", async () => {
    await callApi("/ros/gazebo/stop");
    await getGazeboStatus();
    logPanel("gazebo", "Gazebo stop requested");
  });

  document.getElementById("gazeboStatusBtn").addEventListener("click", async () => {
    await getGazeboStatus();
    logPanel("gazebo", "Gazebo status refreshed");
  });
}

function wireFullStack() {
  document.getElementById("fullStackStart").addEventListener("click", async () => {
    const ok = window.confirm(
      "Starting Full System will stop active RViz-only, MoveIt-only, and Gazebo-only sessions. Continue?"
    );
    if (!ok) {
      return;
    }

    await callApi("/ros/full-stack/start", {
      use_rviz: document.getElementById("fullStackUseRviz").value === "true",
      load_moveit: document.getElementById("fullStackLoadMoveit").value === "true",
      gazebo_gui: document.getElementById("fullStackGazeboGui").value === "true",
    });
    await getFullStackStatus();
    logPanel("fullstack", "Full simulation start requested");
  });

  document.getElementById("fullStackStop").addEventListener("click", async () => {
    await callApi("/ros/full-stack/stop");
    await getFullStackStatus();
    logPanel("fullstack", "Full simulation stop requested");
  });

  document.getElementById("fullStackStatusBtn").addEventListener("click", async () => {
    await getFullStackStatus();
    logPanel("fullstack", "Full simulation status refreshed");
  });
}

function wireHardware() {
  document.getElementById("hardwareTransport").addEventListener("change", () => {
    updateHardwareTransportFields();
  });

  document.getElementById("hardwareStart").addEventListener("click", async () => {
    const ok = window.confirm(
      "Starting Hardware mode will stop all simulation sessions (RViz/MoveIt/Gazebo/Full System). Continue?"
    );
    if (!ok) {
      return;
    }

    startHardwarePolling();
    await callApi("/ros/hardware/start", {
      transport: document.getElementById("hardwareTransport").value,
      device_port: selectedHardwareDevicePort(),
      use_rviz: document.getElementById("hardwareUseRviz").value === "true",
      load_moveit: document.getElementById("hardwareLoadMoveit").value === "true",
      agent_timeout_sec: Number(document.getElementById("hardwareAgentTimeout").value),
      agent_max_retries: Number(document.getElementById("hardwareMaxRetries").value),
    });
    await getHardwareStatus();
  });

  document.getElementById("hardwareStop").addEventListener("click", async () => {
    stopHardwarePolling();
    await callApi("/ros/hardware/stop");
    await getHardwareStatus();
  });

  document.getElementById("hardwareForceKillAgent").addEventListener("click", async () => {
    const ok = window.confirm("Force kill micro-ROS agent now? This sends SIGKILL and may leave hardware launch running.");
    if (!ok) {
      return;
    }

    await callApi("/ros/hardware/force-kill-agent");
    await getHardwareStatus();
  });

  document.getElementById("hardwareReset").addEventListener("click", async () => {
    stopHardwarePolling();
    await callApi("/ros/hardware/reset");
    await getHardwareStatus();
  });

  document.getElementById("hardwareStatusBtn").addEventListener("click", async () => {
    await getHardwareStatus();
  });
}

function wireGlobalButtons() {
  document.getElementById("refreshAllBtn").addEventListener("click", async () => {
    await Promise.all([
      getHealthStatus(),
      getStatus(),
      getRvizStatus(),
      getMoveitStatus(),
      getGazeboStatus(),
      getFullStackStatus(),
      getHardwareStatus(),
      getSystemMonitorStatus(),
      getFirmwareUploadStatus(),
    ]);
    logGlobal("All status panels refreshed");
  });

  document.getElementById("exitAppBtn").addEventListener("click", async () => {
    const ok = window.confirm("Stop middleware + UI servers and close this tab?");
    if (!ok) {
      return;
    }

    stopHardwarePolling();
    await callApi("/system/exit");

    setTimeout(() => {
      window.close();
      // Fallback when browser blocks scripted close.
      setTimeout(() => {
        window.location.href = "about:blank";
      }, 250);
    }, 450);
  });
}

function wireOps() {
  document.getElementById("healthCheckBtn")?.addEventListener("click", async () => {
    await getHealthStatus();
  });

  document.getElementById("systemMonitorBtn")?.addEventListener("click", async () => {
    await getSystemMonitorStatus();
  });

  document.getElementById("systemCleanupBtn")?.addEventListener("click", async () => {
    await runSystemCleanup();
  });

  document.getElementById("firmwareMethod")?.addEventListener("change", () => {
    updateFirmwareMethodFields();
  });

  document.getElementById("firmwareRefreshFilesBtn")?.addEventListener("click", async () => {
    await getFirmwareFiles();
  });

  document.getElementById("firmwareRefreshPortsBtn")?.addEventListener("click", async () => {
    await getFirmwareSerialPorts();
  });

  document.getElementById("firmwareStatusBtn")?.addEventListener("click", async () => {
    await getFirmwareUploadStatus();
  });

  document.getElementById("firmwareMdnsBtn")?.addEventListener("click", async () => {
    await firmwareMdnsLookup();
  });

  document.getElementById("firmwareStartBtn")?.addEventListener("click", async () => {
    await startFirmwareUpload();
  });
}

// ─── TEACH & REPEAT TAB ─────────────────────────────────────────────────────
function teachLog(msg) {
  if (!teachLogEl) return;
  prependLine(teachLogEl, msg);
}

function teachDefaultRef(arm) {
  if (arm === "right") {
    return { x: 0.05, y: 0.0, z: 0.24 };
  }
  return { x: -0.05, y: 0.0, z: 0.24 };
}

function teachShapeConfig(shape) {
  const s = String(shape || "line").toLowerCase();
  if (s === "circle") return { type: "circle", radius: 0.08, n_points: 30 };
  if (s === "rectangle") return { type: "rectangle", width: 0.12, height: 0.08, n_points: 30 };
  if (s === "arc") return { type: "arc", radius: 0.10, angle: 180, n_points: 30 };
  if (s === "zigzag") return { type: "zigzag", length: 0.16, width: 0.04, steps: 4, n_points: 30 };
  if (s === "spiral") return { type: "spiral", r1: 0.03, r2: 0.10, turns: 2, n_points: 30 };
  return { type: "line", length: 0.10, n_points: 30 };
}

function teachBuildConfig() {
  const arm = document.getElementById("teachArm")?.value || "left";
  const shape = document.getElementById("teachShape")?.value || "line";
  const ref = teachDefaultRef(arm);
  return {
    arm,
    surface: { normal: [0, 0, 1], tool_tilt_deg: 0.0 },
    reference_point: ref,
    shape: teachShapeConfig(shape),
    execution: {
      eef_step: 0.01,
      jump_threshold: 0.0,
      max_velocity_scaling: 0.2,
      max_acceleration_scaling: 0.1,
      avoid_collisions: true,
      time_param_method: "totg",
    },
  };
}

async function teachRefreshStatus() {
  try {
    const res = await fetch(`${API_BASE}/trajectory/teach/status`);
    const data = await res.json();
    if (teachStatusEl) {
      teachStatusEl.textContent = JSON.stringify(data, null, 2);
    }
    if (!res.ok) {
      teachLog(`[ERROR] Status failed: ${JSON.stringify(data)}`);
    }
  } catch (err) {
    if (teachStatusEl) {
      teachStatusEl.textContent = `Failed to fetch teach status: ${err.message}`;
    }
    teachLog(`[ERROR] Status request failed: ${err.message}`);
  }
}

async function teachCaptureSegment() {
  const config = teachBuildConfig();
  try {
    const res = await fetch(`${API_BASE}/trajectory/teach/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    });
    const data = await res.json();
    if (!res.ok) {
      teachLog(`[ERROR] Capture failed: ${JSON.stringify(data)}`);
      return;
    }
    teachLog(`[OK] Segment captured (${data.segment_id || "n/a"}), total=${data.segments_count}`);
    await teachRefreshStatus();
  } catch (err) {
    teachLog(`[ERROR] Capture request failed: ${err.message}`);
  }
}

async function teachCompileTrajectory() {
  const name = String(document.getElementById("teachSaveName")?.value || "").trim();
  try {
    const res = await fetch(`${API_BASE}/trajectory/teach/compile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(name ? { name } : {}),
    });
    const data = await res.json();
    if (!res.ok) {
      teachLog(`[ERROR] Compile failed: ${JSON.stringify(data)}`);
      return;
    }
    teachLog(`[OK] Compiled teach job ${data.compiled_job_id || "n/a"}`);
    await teachRefreshStatus();
  } catch (err) {
    teachLog(`[ERROR] Compile request failed: ${err.message}`);
  }
}

async function teachSaveTrajectory() {
  const name = String(document.getElementById("teachSaveName")?.value || "").trim();
  if (!name) {
    teachLog("[WARN] Save name is required.");
    return;
  }
  try {
    const res = await fetch(`${API_BASE}/trajectory/teach/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) {
      teachLog(`[ERROR] Save failed: ${JSON.stringify(data)}`);
      return;
    }
    teachLog(`[OK] Saved teach trajectory to ${data.saved_file || "n/a"}`);
    await Promise.all([teachRefreshStatus(), executeRefreshJobs()]);
  } catch (err) {
    teachLog(`[ERROR] Save request failed: ${err.message}`);
  }
}

async function teachClearBuffer() {
  const ok = window.confirm("Clear all captured teach segments?");
  if (!ok) return;
  try {
    const res = await fetch(`${API_BASE}/trajectory/teach/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json();
    if (!res.ok) {
      teachLog(`[ERROR] Clear failed: ${JSON.stringify(data)}`);
      return;
    }
    teachLog("[OK] Teach buffer cleared.");
    await teachRefreshStatus();
  } catch (err) {
    teachLog(`[ERROR] Clear request failed: ${err.message}`);
  }
}

function wireTeach() {
  document.getElementById("teachStatusBtn")?.addEventListener("click", teachRefreshStatus);
  document.getElementById("teachCaptureBtn")?.addEventListener("click", teachCaptureSegment);
  document.getElementById("teachCompileBtn")?.addEventListener("click", teachCompileTrajectory);
  document.getElementById("teachSaveBtn")?.addEventListener("click", teachSaveTrajectory);
  document.getElementById("teachClearBtn")?.addEventListener("click", teachClearBuffer);
}

function connectEvents() {
  const ws = new WebSocket(WS_URL);
  ws.onopen = () => logGlobal("WebSocket connected");
  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      logGlobal(`${msg.type}: ${msg.message}`);
      if (msg.payload) {
        statusEl.textContent = JSON.stringify(msg.payload, null, 2);
        applySnapshot(msg.payload);
      }
    } catch {
      logGlobal(`WS raw: ${evt.data}`);
    }
  };
  ws.onclose = () => {
    logGlobal("WebSocket disconnected, retrying in 2s");
    setTimeout(connectEvents, 2000);
  };
}

// ─── EXECUTE SAVED TRAJECTORY TAB ────────────────────────────────────────────
let executeSelectedJobId = null;
let executeTargetMode = "simulated";

function updateExecutionTarget() {
  const selected = document.querySelector('input[name="executionMode"]:checked');
  if (selected) {
    executeTargetMode = selected.value;
    const targetDisplay = document.getElementById("executeTargetDisplay");
    const modeText = {
      simulated: "Simulated",
      gazebo: "🌍 Gazebo Simulation",
      hardware: "🖥️ Real Hardware"
    };
    if (targetDisplay) {
      targetDisplay.textContent = modeText[executeTargetMode] || executeTargetMode;
    }
  }
}

function executeLog(msg) {
  const el = document.getElementById("executeLog");
  if (el) {
    const ts = new Date().toLocaleTimeString();
    el.textContent += `\n[${ts}] ${msg}`;
    el.parentElement.scrollTop = el.parentElement.scrollHeight;
  }
}

async function executeRefreshJobs() {
  try {
    const res = await fetch(`${API_BASE}/trajectory/jobs?limit=30`);
    const data = await res.json();
    const jobs = data.jobs || [];
    
    const sel = document.getElementById("executeSavedJobSelect");
    if (!sel) return;
    
    sel.innerHTML = '';
    if (jobs.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No saved jobs available";
      sel.appendChild(opt);
      executeLog("No saved jobs found.");
      return;
    }
    
    for (const j of jobs) {
      const id = String(j.job_id || "").trim();
      if (!id) continue;
      const backend = String(j.backend || "unknown").toUpperCase();
      const status = String(j.status || "?").toUpperCase();
      const name = String(j.trajectory_name || "").trim();
      const label = name ? `${name} | ${id} | ${backend} | ${status}` : `${id} | ${backend} | ${status}`;
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = label;
      sel.appendChild(opt);
    }
    
    executeLog(`Loaded ${jobs.length} saved job(s).`);
    executeSelectedJobId = jobs[0]?.job_id || null;
    
  } catch (e) {
    executeLog(`[ERROR] Refresh jobs failed: ${e.message}`);
  }
}

async function executeValidateJob() {
  const sel = document.getElementById("executeSavedJobSelect");
  const jobId = sel?.value || executeSelectedJobId;
  
  if (!jobId) {
    executeLog("[WARN] Select a job first.");
    return;
  }
  
  try {
    const res = await fetch(`${API_BASE}/trajectory/artifacts/validate/${encodeURIComponent(jobId)}?strict=true`);
    const data = await res.json();
    
    if (!res.ok || !data.ok) {
      executeLog(`[ERROR] Validate failed: ${JSON.stringify(data)}`);
      return;
    }
    
    executeLog(`[OK] Job ${jobId} validated | backend=${data.backend}`);
    executeSelectedJobId = jobId;
  } catch (e) {
    executeLog(`[ERROR] Validate request failed: ${e.message}`);
  }
}

async function executePrecheckJob() {
  const sel = document.getElementById("executeSavedJobSelect");
  const jobId = sel?.value || executeSelectedJobId;
  
  if (!jobId) {
    executeLog("[WARN] Select a job first.");
    return;
  }
  
  try {
    const url = `${API_BASE}/trajectory/execute/precheck?artifact_job_id=${encodeURIComponent(jobId)}&artifact_strict=true`;
    const res = await fetch(url);
    const data = await res.json();
    
    if (data.ok) {
      executeLog(`[OK] Precheck passed for ${jobId}. Ready to execute.`);
      executeSelectedJobId = jobId;
      return true;
    } else {
      const reasons = Array.isArray(data.reasons) ? data.reasons.join(", ") : "unknown";
      executeLog(`[WARN] Precheck failed: ${reasons}`);
      return false;
    }
  } catch (e) {
    executeLog(`[ERROR] Precheck request failed: ${e.message}`);
    return false;
  }
}

async function executeStartTrajectory() {
  const sel = document.getElementById("executeSavedJobSelect");
  const jobId = sel?.value || executeSelectedJobId;
  
  if (!jobId) {
    executeLog("[WARN] Select a job first.");
    return;
  }
  
  // Check precheck first
  const ready = await executePrecheckJob();
  if (!ready) return;
  
  try {
    const url = `${API_BASE}/trajectory/execute?artifact_job_id=${encodeURIComponent(jobId)}&artifact_strict=true`;
    const body = {
      name: `execute-${jobId}-${executeTargetMode}`,
      duration_sec: 1.5,
    };
    
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    
    const data = await res.json();
    if (!res.ok) {
      const detail = data?.detail || JSON.stringify(data);
      executeLog(`[ERROR] Execute failed: ${detail}`);
      return;
    }
    
    const context = data.trajectory?.context || "simulated";
    const statusEl = document.getElementById("executeStatus");
    if (statusEl) statusEl.textContent = `Executing on ${context}`;
    
    executeLog(`[EXECUTE] Started on ${context} | ${jobId}`);
    executeSelectedJobId = jobId;
    
  } catch (e) {
    executeLog(`[ERROR] Execute request failed: ${e.message}`);
  }
}

async function executeStopTrajectory() {
  try {
    const res = await fetch(`${API_BASE}/trajectory/stop`, { method: "POST" });
    if (!res.ok) {
      const txt = await res.text();
      executeLog(`[WARN] Stop returned ${res.status}: ${txt}`);
      return;
    }
    executeLog("[STOP] Execution stopped.");
    const statusEl = document.getElementById("executeStatus");
    if (statusEl) statusEl.textContent = "Stopped";
  } catch (e) {
    executeLog(`[ERROR] Stop request failed: ${e.message}`);
  }
}

async function executeDeleteJob() {
  const sel = document.getElementById("executeSavedJobSelect");
  const jobId = sel?.value || executeSelectedJobId;
  
  if (!jobId) {
    executeLog("[WARN] Select a job first.");
    return;
  }
  
  if (!confirm(`Delete job ${jobId}?`)) return;
  
  try {
    const res = await fetch(`${API_BASE}/trajectory/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE"
    });
    
    const data = await res.json();
    if (!res.ok) {
      executeLog(`[ERROR] Delete failed: ${JSON.stringify(data)}`);
      return;
    }
    
    executeLog(`[DELETE] Removed ${jobId}.`);
    if (executeSelectedJobId === jobId) executeSelectedJobId = null;
    await executeRefreshJobs();
    
  } catch (e) {
    executeLog(`[ERROR] Delete request failed: ${e.message}`);
  }
}

function wireExecute() {
  document.getElementById("executeRefreshJobsBtn")?.addEventListener("click", executeRefreshJobs);
  document.getElementById("executeValidateBtn")?.addEventListener("click", executeValidateJob);
  document.getElementById("executePrecheckBtn")?.addEventListener("click", executePrecheckJob);
  document.getElementById("executeStartBtn")?.addEventListener("click", executeStartTrajectory);
  document.getElementById("executeStopBtn")?.addEventListener("click", executeStopTrajectory);
  document.getElementById("executeDeleteBtn")?.addEventListener("click", executeDeleteJob);
}

async function initialize() {
  wireTabs();
  wireModelViewer();
  wirePlanner();
  wireGazebo();
  wireFullStack();
  wireHardware();
  wireOps();
  wireTeach();
  wireExecute();
  wireGlobalButtons();
  updateHardwareTransportFields();
  updateFirmwareMethodFields();

  await Promise.all([
    getHealthStatus(),
    getStatus(),
    getRvizStatus(),
    getMoveitStatus(),
    getGazeboStatus(),
    getFullStackStatus(),
    getHardwareStatus(),
    getSystemMonitorStatus(),
    getFirmwareFiles(),
    getFirmwareSerialPorts(),
    getFirmwareUploadStatus(),
    teachRefreshStatus(),
    executeRefreshJobs(),
  ]);

  connectEvents();
  startLiveStatusRefresh();
}

initialize().catch((e) => {
  logGlobal(`Initialization failed: ${e.message}`);
});
