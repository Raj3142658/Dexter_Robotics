const API_BASE = "http://127.0.0.1:8084";
const WS_URL = "ws://127.0.0.1:8084/ws/events";

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

const modelLogEl = document.getElementById("modelLog");
const plannerLogEl = document.getElementById("plannerLog");
const gazeboLogEl = document.getElementById("gazeboLog");
const fullStackLogEl = document.getElementById("fullStackLog");

const hardwareSessionStateEl = document.getElementById("hardwareSessionState");
const hardwareSessionHintEl = document.getElementById("hardwareSessionHint");
const hardwareSessionLogEl = document.getElementById("hardwareSessionLog");

let hardwarePollTimer = null;
let firmwarePollTimer = null;

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
  if (data.suggest_reset) {
    hintMessage += "\nNo session after 10s. Press ESP32 RESET once, then wait for session marker.";
  }
  if (data.last_error) {
    hintMessage += `\nLast error: ${data.last_error}`;
  }

  hardwareSessionHintEl.textContent = hintMessage;
  hardwareSessionLogEl.textContent = logs.length ? logs.join("\n") : "No session logs yet.";
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
    serial_port: document.getElementById("firmwareSerialPort")?.value || "/dev/ttyUSB0",
    serial_baud: Number(document.getElementById("firmwareSerialBaud")?.value || 921600),
    fqbn: document.getElementById("firmwareFqbn")?.value || "esp32:esp32:esp32",
    ota_ip: document.getElementById("firmwareOtaIp")?.value || "",
    ota_password: document.getElementById("firmwareOtaPassword")?.value || "",
  };

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

function connectEvents() {
  const ws = new WebSocket(WS_URL);
  ws.onopen = () => logGlobal("WebSocket connected");
  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      logGlobal(`${msg.type}: ${msg.message}`);
      if (msg.payload) {
        statusEl.textContent = JSON.stringify(msg.payload, null, 2);
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

async function initialize() {
  wireTabs();
  wireModelViewer();
  wirePlanner();
  wireGazebo();
  wireFullStack();
  wireHardware();
  wireOps();
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
    getFirmwareUploadStatus(),
  ]);

  connectEvents();
}

initialize().catch((e) => {
  logGlobal(`Initialization failed: ${e.message}`);
});
