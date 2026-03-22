const API_BASE = "http://127.0.0.1:8084";
const WS_URL = "ws://127.0.0.1:8084/ws/events";

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");

const rvizStatusEl = document.getElementById("rvizStatus");
const moveitStatusEl = document.getElementById("moveitStatus");
const gazeboStatusEl = document.getElementById("gazeboStatus");
const fullStackStatusEl = document.getElementById("fullStackStatus");
const hardwareStatusEl = document.getElementById("hardwareStatus");

const modelLogEl = document.getElementById("modelLog");
const plannerLogEl = document.getElementById("plannerLog");
const gazeboLogEl = document.getElementById("gazeboLog");
const fullStackLogEl = document.getElementById("fullStackLog");

const hardwareSessionStateEl = document.getElementById("hardwareSessionState");
const hardwareSessionHintEl = document.getElementById("hardwareSessionHint");
const hardwareSessionLogEl = document.getElementById("hardwareSessionLog");

let hardwarePollTimer = null;

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
      getStatus(),
      getRvizStatus(),
      getMoveitStatus(),
      getGazeboStatus(),
      getFullStackStatus(),
      getHardwareStatus(),
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
  wireGlobalButtons();
  updateHardwareTransportFields();

  await Promise.all([
    getStatus(),
    getRvizStatus(),
    getMoveitStatus(),
    getGazeboStatus(),
    getFullStackStatus(),
    getHardwareStatus(),
  ]);

  connectEvents();
}

initialize().catch((e) => {
  logGlobal(`Initialization failed: ${e.message}`);
});
