/**
 * ============================================================================
 * ESP32 Joint Executor - WiFi + OTA (FINAL v2.3)
 * ============================================================================
 * 
 * WiFi + OTA Configuration:
 * - Connects via WiFi instead of Serial
 * - Supports Over-The-Air (OTA) firmware updates
 * - Uses UDP transport to micro-ROS agent
 * - Faster communication than Serial (1000+ msg/sec vs ~11 msg/sec)
 */

#include <micro_ros_arduino.h>
#include <rcl/rcl.h>
#include <rclc/rclc.h>
#include <rclc/executor.h>
#include <std_msgs/msg/float64_multi_array.h>
#include <rmw_microros/rmw_microros.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <math.h>

// WiFi & OTA libraries
#include <WiFi.h>
#include <ArduinoOTA.h>

// =========================== WiFi CONFIGURATION =============================
// ⚠️ IMPORTANT: Configure these before uploading!
#define WIFI_SSID       "realme 5i"         // Your WiFi network name
#define WIFI_PASSWORD   "123456790"         // Your WiFi password
#define AGENT_IP        "192.168.43.253"    // Your PC's IP address (Updated automatically)
#define AGENT_PORT      8888                // micro-ROS agent UDP port
#define OTA_HOSTNAME    "dexter-esp32"      // Hostname for OTA
#define OTA_PASSWORD    "dexter123"         // OTA update password

// =========================== FAST TUNING ====================================
#define MOTION_DURATION_MS      220
#define MIN_MOTION_DURATION_MS  20
#define PWM_THRESHOLD_US        60
#define BYPASS_THRESHOLD_US     90
#define LOOP_PERIOD_US          2000        // 500 Hz
#define SERVO_FREQ              50
#define COMMAND_TIMEOUT_MS      200
#define STATE_PUB_PERIOD_MS     10        // 100 Hz
#define HEALTH_PUB_PERIOD_MS    250       // 4 Hz
#define ENABLE_DYNAMIC_SCALING  true
#define EXECUTOR_SPIN_MS        1         // Keep ROS spin short so PWM loop does not stall
#define I2C_CLOCK_HZ            100000    // Lower I2C speed improves robustness on noisy wiring
#define I2C_TIMEOUT_MS          5
#define MAX_TARGET_DELTA_US     260       // Hard clamp per command frame to reject disturbed jumps

// =========================== HARDWARE =======================================
#define NUM_JOINTS      14
#define SERVO_MIN_US    500
#define SERVO_MAX_US    2400
#define LED_PIN         2
#define SERIAL_BAUD     115600

// =========================== JOINT LIMITS ===================================
const float JOINT_MIN[NUM_JOINTS] = {-1.57,-1.57,-1.57,-1.57,-1.57,-1.57, 0.0, -1.57,-1.57,-1.57,-1.57,-1.57,-1.57, 0.0};
const float JOINT_MAX[NUM_JOINTS] = { 1.57, 1.57, 1.57, 1.57, 1.57, 1.57, 3.14159, 1.57, 1.57, 1.57, 1.57, 1.57, 1.57, 3.14159};

// ====================== 🏠 INIT PWM (Home Position + Calibration) ==========
const uint16_t INIT_PWM[NUM_JOINTS] = {
  1545, 1800, 1600, 1750, 1450, 1850, 500,   // Left arm (0-5) + gripper (6 = 180° closed)
  1500, 1500, 1500, 1500, 1500, 1500, 500   // Right arm (7-12) + gripper (13 = 0° open)
};

// =========================== ROS / PWM ======================================
Adafruit_PWMServoDriver pwm(0x40);
rcl_node_t node;
rclc_support_t support;
rclc_executor_t executor;
rcl_subscription_t command_sub;
rcl_publisher_t state_pub;
rcl_publisher_t health_pub;
std_msgs__msg__Float64MultiArray command_msg;
std_msgs__msg__Float64MultiArray state_msg;
std_msgs__msg__Float64MultiArray health_msg;

// =========================== STATE ==========================================
struct JointState {
  double position;
  double velocity;
  uint16_t current_pwm;
  uint16_t target_pwm;
};

struct MotionProfile {
  uint16_t start_pwm;
  uint16_t target_pwm;
  unsigned long start_time_us;
  unsigned long duration_us;
  bool active;
};

JointState joints[NUM_JOINTS];
MotionProfile motion[NUM_JOINTS];
uint16_t last_pwm[NUM_JOINTS];
unsigned long last_cmd_time = 0;
unsigned long last_pub_time = 0;
unsigned long last_health_pub_time = 0;

// Link/session diagnostics.
uint32_t rx_total = 0;
uint32_t rx_accepted = 0;
uint32_t drop_bad_size = 0;
uint32_t drop_invalid = 0;
uint32_t drop_stale_seq = 0;
uint32_t timeout_events = 0;
uint32_t last_rx_seq = 0;
bool seq_initialized = false;
bool command_stale_active = false;

// =========================== QUINTIC PROFILE ================================
inline float quintic_profile(float t) {
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  return t*t*t*(10.0f + t*(-15.0f + 6.0f*t));
}

// =========================== PWM MAPPING ====================================
uint16_t radians_to_pwm(float rad, int i) {
  rad = constrain(rad, JOINT_MIN[i], JOINT_MAX[i]);
  int pwm_val = INIT_PWM[i];

  // Zero-anchored mapping:
  // rad == 0.0  -> INIT_PWM[i]
  // JOINT_MAX   -> SERVO_MAX_US
  // JOINT_MIN   -> SERVO_MIN_US
  if (rad >= 0.0f) {
    float denom = JOINT_MAX[i] > 0.0f ? JOINT_MAX[i] : 1.0f;
    float gain_pos = (float)(SERVO_MAX_US - INIT_PWM[i]) / denom;
    pwm_val = INIT_PWM[i] + (int)(rad * gain_pos);
  } else {
    float denom = JOINT_MIN[i] < 0.0f ? -JOINT_MIN[i] : 1.0f;
    float gain_neg = (float)(INIT_PWM[i] - SERVO_MIN_US) / denom;
    pwm_val = INIT_PWM[i] + (int)(rad * gain_neg);
  }

  pwm_val = ((pwm_val + 2) / 4) * 4;
  return constrain(pwm_val, SERVO_MIN_US, SERVO_MAX_US);
}

// =========================== PWM INVERSE MAPPING ============================
// Convert PWM value back to radians (inverse of radians_to_pwm)
float pwm_to_radians(uint16_t pwm_val, int i) {
  int delta = (int)pwm_val - (int)INIT_PWM[i];
  float rad = 0.0f;

  // Inverse of zero-anchored mapping above.
  if (delta >= 0) {
    int up_range = SERVO_MAX_US - INIT_PWM[i];
    if (up_range <= 0) return 0.0f;
    rad = ((float)delta / (float)up_range) * JOINT_MAX[i];
  } else {
    int down_range = INIT_PWM[i] - SERVO_MIN_US;
    if (down_range <= 0) return 0.0f;
    rad = ((float)delta / (float)down_range) * (-JOINT_MIN[i]);
  }

  return constrain(rad, JOINT_MIN[i], JOINT_MAX[i]);
}

// Convert current PWM to ROS joint-space radians.
// NOTE: This is an estimated state from commanded PWM (no encoder feedback).
float joint_estimated_position_from_pwm(uint16_t pwm_val, int i) {
  float rad = pwm_to_radians(pwm_val, i);
  if (i == 1 || i == 3 || i == 4) {
    // These joints are inverted in command_callback when converting command->PWM.
    rad = -rad;
  }
  return rad;
}

// =========================== INTERPOLATION ==================================
uint16_t get_interpolated_pwm(int i) {
  MotionProfile &m = motion[i];
  if (!m.active) return joints[i].target_pwm;

  unsigned long elapsed = micros() - m.start_time_us;
  if (elapsed >= m.duration_us) {
    m.active = false;
    joints[i].velocity = 0.0;
    return m.target_pwm;
  }

  float t = (float)elapsed / (float)m.duration_us;
  float s = quintic_profile(t);
  if (t < 0.05f) s *= 1.4f;

  int delta = (int)m.target_pwm - (int)m.start_pwm;
  joints[i].velocity = delta / (m.duration_us * 1e-6);
  return m.start_pwm + (int)(s * delta);
}

// =========================== COMMAND CALLBACK ===============================
void command_callback(const void *msgin) {
  auto *msg = (const std_msgs__msg__Float64MultiArray *)msgin;

  rx_total++;
  if (msg->data.size < NUM_JOINTS) {
    drop_bad_size++;
    return;
  }

  // Backward compatible metadata extension:
  // [0..13] joint commands, [14] monotonically increasing sequence id.
  if (msg->data.size >= (NUM_JOINTS + 1)) {
    double seq_d = msg->data.data[NUM_JOINTS];
    if (!isfinite(seq_d) || seq_d < 0.0) {
      drop_invalid++;
      return;
    }
    uint32_t seq = (uint32_t)seq_d;
    if (seq_initialized && seq <= last_rx_seq) {
      drop_stale_seq++;
      return;
    }
    seq_initialized = true;
    last_rx_seq = seq;
  }

  for (int i = 0; i < NUM_JOINTS; i++) {
    if (!isfinite(msg->data.data[i])) {
      drop_invalid++;
      return;
    }
  }

  last_cmd_time = millis();
  command_stale_active = false;
  rx_accepted++;

  for (int i = 0; i < NUM_JOINTS; i++) {
    uint16_t target;
    joints[i].position = msg->data.data[i];

    if (i == 1 || i == 3 || i == 4)
      target = radians_to_pwm(-joints[i].position, i);
    else
      target = radians_to_pwm(joints[i].position, i);

    int hard_delta = (int)target - (int)joints[i].current_pwm;
    if (hard_delta > MAX_TARGET_DELTA_US) {
      target = joints[i].current_pwm + MAX_TARGET_DELTA_US;
      drop_invalid++;
    } else if (hard_delta < -MAX_TARGET_DELTA_US) {
      target = joints[i].current_pwm - MAX_TARGET_DELTA_US;
      drop_invalid++;
    }

    int delta = abs((int)target - (int)joints[i].current_pwm);

    if (delta <= BYPASS_THRESHOLD_US) {
      joints[i].current_pwm = target;
      joints[i].target_pwm = target;
      motion[i].active = false;
      continue;
    }

    if (delta > PWM_THRESHOLD_US) {
      motion[i].start_pwm = joints[i].current_pwm;
      motion[i].target_pwm = target;
      motion[i].start_time_us = micros();

      unsigned long dur_ms = ENABLE_DYNAMIC_SCALING
        ? max((unsigned long)MIN_MOTION_DURATION_MS,
              (unsigned long)(delta * 0.12f))
        : MOTION_DURATION_MS;

      dur_ms = min(dur_ms, (unsigned long)MOTION_DURATION_MS);
      motion[i].duration_us = dur_ms * 1000UL;
      motion[i].active = true;
    }

    joints[i].target_pwm = target;
  }
}

// =========================== SETUP ==========================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(LED_PIN, OUTPUT);
  
  // =========================================================================
  // WiFi SETUP
  // =========================================================================
  Serial.println("\n=== ESP32 Joint Executor (WiFi + OTA) ===");
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  // Wait for connection (with timeout)
  int wifi_attempts = 0;
  while (WiFi.status() != WL_CONNECTED && wifi_attempts < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));  // Blink LED
    wifi_attempts++;
  }
  
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n❌ WiFi connection FAILED!");
    Serial.println("Check SSID and password, then restart ESP32");
    while(1) {
      digitalWrite(LED_PIN, !digitalRead(LED_PIN));
      delay(200);  // Fast blink = error
    }
  }
  
  Serial.println("\n✓ WiFi connected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
  Serial.print("Agent IP: ");
  Serial.println(AGENT_IP);
  WiFi.setSleep(false);  // Keep UDP latency/jitter stable during control loops.
  digitalWrite(LED_PIN, HIGH);  // Solid LED = connected
  
  // =========================================================================
  // OTA SETUP (Over-The-Air Updates)
  // =========================================================================
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  
  ArduinoOTA.onStart([]() {
    String type = (ArduinoOTA.getCommand() == U_FLASH) ? "sketch" : "filesystem";
    Serial.println("OTA: Starting update - " + type);
  });
  
  ArduinoOTA.onEnd([]() {
    Serial.println("\nOTA: Update complete!");
  });
  
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    static unsigned long last_print = 0;
    if (millis() - last_print > 500) {  // Print every 500ms
      Serial.printf("OTA Progress: %u%%\r", (progress / (total / 100)));
      last_print = millis();
    }
  });
  
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("OTA Error[%u]: ", error);
    if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
    else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
    else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
    else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
    else if (error == OTA_END_ERROR) Serial.println("End Failed");
  });
  
  ArduinoOTA.begin();
  Serial.println("✓ OTA ready");
  
  // =========================================================================
  // HARDWARE INITIALIZATION
  // =========================================================================
  Wire.begin();
  Wire.setClock(I2C_CLOCK_HZ);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  pwm.begin();
  pwm.setPWMFreq(SERVO_FREQ);

  for (int i = 0; i < NUM_JOINTS; i++) {
    // Calculate actual position from INIT_PWM calibration
    joints[i].position = pwm_to_radians(INIT_PWM[i], i);
    joints[i].velocity = 0.0;
    joints[i].current_pwm = INIT_PWM[i];
    joints[i].target_pwm = INIT_PWM[i];
    motion[i].active = false;
    last_pwm[i] = INIT_PWM[i];
    pwm.writeMicroseconds(i, INIT_PWM[i]);
  }
  
  Serial.println("✓ Servos initialized to home position");
  Serial.println("\n=== INITIAL JOINT POSITIONS (from INIT_PWM calibration) ===");
  for (int i = 0; i < NUM_JOINTS; i++) {
    Serial.printf("Joint %2d: PWM=%4d µs  Position=%7.4f rad  (%5.1f°)\n", 
      i, INIT_PWM[i], joints[i].position, joints[i].position * 180.0f / 3.14159f);
  }
  Serial.println("============================================================\n");
  
  // =========================================================================
  // micro-ROS SETUP (WiFi Transport)
  // =========================================================================
  Serial.print("Connecting to micro-ROS agent at ");
  Serial.print(AGENT_IP);
  Serial.print(":");
  Serial.println(AGENT_PORT);
  
  // Set WiFi transport (UDP)
  set_microros_wifi_transports(WIFI_SSID, WIFI_PASSWORD, AGENT_IP, AGENT_PORT);
  Serial.println("Waiting for WiFi stabilization...");
  delay(2000);  // Give time for connection

  // Wait until the micro-ROS agent is reachable to avoid one-shot init failure.
  Serial.println("Waiting for micro-ROS agent...");
  while (rmw_uros_ping_agent(1000, 1) != RMW_RET_OK) {
    Serial.println("micro-ROS agent not reachable yet; retrying in 1s...");
    ArduinoOTA.handle();
    delay(1000);
  }
  Serial.println("✓ micro-ROS agent reachable");

  rcl_allocator_t allocator = rcl_get_default_allocator();
  rclc_support_init(&support, 0, NULL, &allocator);
  rclc_node_init_default(&node, "esp32_joint_executor", "", &support);

  // ===== FIX 2: REAL-TIME SAFE QoS =====
  rmw_qos_profile_t qos = rmw_qos_profile_sensor_data;
  qos.history = RMW_QOS_POLICY_HISTORY_KEEP_LAST;
  qos.depth = 1;
  qos.durability = RMW_QOS_POLICY_DURABILITY_VOLATILE;

  rclc_subscription_init(
    &command_sub, &node,
    ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Float64MultiArray),
    "/esp32/joint_commands", &qos);

  rclc_publisher_init(
    &state_pub, &node,
    ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Float64MultiArray),
    "/esp32/joint_states", &qos);

  rclc_publisher_init(
    &health_pub, &node,
    ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Float64MultiArray),
    "/esp32/link_health", &qos);

  rclc_executor_init(&executor, &support.context, 1, &allocator);
  rclc_executor_add_subscription(
    &executor, &command_sub,
    &command_msg, &command_callback, ON_NEW_DATA);

  state_msg.data.capacity = state_msg.data.size = NUM_JOINTS;
  state_msg.data.data = (double*)malloc(NUM_JOINTS * sizeof(double));

  health_msg.data.capacity = health_msg.data.size = 11;
  health_msg.data.data = (double*)malloc(11 * sizeof(double));

  command_msg.data.capacity = NUM_JOINTS;
  command_msg.data.data = (double*)malloc(NUM_JOINTS * sizeof(double));
}

// =========================== LOOP ===========================================
void loop() {
  // ===== OTA HANDLING =====
  ArduinoOTA.handle();  // Check for OTA updates
  
  // ===== WiFi RECONNECTION =====
  static unsigned long last_wifi_check = 0;
  if (millis() - last_wifi_check > 5000) {  // Check every 5 seconds
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi disconnected! Reconnecting...");
      WiFi.reconnect();
      digitalWrite(LED_PIN, LOW);  // LED off = disconnected
    } else {
      digitalWrite(LED_PIN, HIGH);  // LED on = connected
    }
    last_wifi_check = millis();
  }
  
  // ===== micro-ROS PROCESSING =====
  rclc_executor_spin_some(&executor, RCL_MS_TO_NS(EXECUTOR_SPIN_MS));

  // ===== TIMEOUT HANDLING =====
  if (millis() - last_cmd_time > COMMAND_TIMEOUT_MS) {
    if (!command_stale_active) {
      timeout_events++;
      command_stale_active = true;
    }
    for (int i = 0; i < NUM_JOINTS; i++) {
      motion[i].active = false;
      joints[i].target_pwm = joints[i].current_pwm;  // Freeze at current output on stale command
    }
  }

  for (int i = 0; i < NUM_JOINTS; i++) {
    joints[i].current_pwm = get_interpolated_pwm(i);
    if (joints[i].current_pwm != last_pwm[i]) {
      pwm.writeMicroseconds(i, joints[i].current_pwm);
      last_pwm[i] = joints[i].current_pwm;
    }
  }

  if (millis() - last_pub_time >= STATE_PUB_PERIOD_MS) {
    for (int i = 0; i < NUM_JOINTS; i++) {
      // Publish estimated joint state based on actively driven PWM, not last command.
      joints[i].position = joint_estimated_position_from_pwm(joints[i].current_pwm, i);
      state_msg.data.data[i] = joints[i].position;
    }
    rcl_publish(&state_pub, &state_msg, NULL);
    last_pub_time = millis();
  }

  if (millis() - last_health_pub_time >= HEALTH_PUB_PERIOD_MS) {
    health_msg.data.data[0] = millis() / 1000.0;                // uptime_s
    health_msg.data.data[1] = (double)(millis() - last_cmd_time); // cmd_age_ms
    health_msg.data.data[2] = (double)rx_total;
    health_msg.data.data[3] = (double)rx_accepted;
    health_msg.data.data[4] = (double)drop_bad_size;
    health_msg.data.data[5] = (double)drop_invalid;
    health_msg.data.data[6] = (double)drop_stale_seq;
    health_msg.data.data[7] = (double)timeout_events;
    health_msg.data.data[8] = (double)last_rx_seq;
    health_msg.data.data[9] = (double)WiFi.RSSI();
    health_msg.data.data[10] = (WiFi.status() == WL_CONNECTED) ? 1.0 : 0.0;
    rcl_publish(&health_pub, &health_msg, NULL);
    last_health_pub_time = millis();
  }

  delayMicroseconds(LOOP_PERIOD_US);
}