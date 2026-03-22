/**
 * ============================================================================
 * ESP32 Joint Executor - FAST + ZERO CALIBRATION (FINAL v2.3)
 * ============================================================================
 */

#include <micro_ros_arduino.h>
#include <rcl/rcl.h>
#include <rclc/rclc.h>
#include <rclc/executor.h>
#include <std_msgs/msg/float64_multi_array.h>
#include <rmw_microros/rmw_microros.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// =========================== FAST TUNING ====================================
#define MOTION_DURATION_MS      220
#define MIN_MOTION_DURATION_MS  20
#define PWM_THRESHOLD_US        60
#define BYPASS_THRESHOLD_US     90
#define LOOP_PERIOD_US          2000      // 500 Hz
#define SERVO_FREQ              50
#define COMMAND_TIMEOUT_MS      200
#define STATE_PUB_PERIOD_MS     10        // 100 Hz
#define ENABLE_DYNAMIC_SCALING  true

// =========================== HARDWARE =======================================
#define NUM_JOINTS      14
#define SERVO_MIN_US    500
#define SERVO_MAX_US    2500
#define LED_PIN         2
#define SERIAL_BAUD     115600

// =========================== JOINT LIMITS ===================================
const float JOINT_MIN[NUM_JOINTS] = {-1.57,-1.57,-1.57,-1.57,-1.57,-1.57, 0.0, -1.57,-1.57,-1.57,-1.57,-1.57,-1.57, 0.0};
const float JOINT_MAX[NUM_JOINTS] = { 1.57, 1.57, 1.57, 1.57, 1.57, 1.57, 3.14159, 1.57, 1.57, 1.57, 1.57, 1.57, 1.57, 3.14159};

// ====================== 🏠 INIT PWM (Home Position + Calibration) ==========
const uint16_t INIT_PWM[NUM_JOINTS] = {
  1545, 1775, 750, 1775, 1475, 1610, 500,   // Left arm + gripper (Index 6 = 180° closed)
  1675, 1600, 1675, 1550, 1500, 1500, 500,  // Right arm + gripper (Index 13 = 0° open)
};



// 1545, 1775, 750, 1775, 1475, 1610, 2500,   // Left arm + gripper (Index 6 = 180° closed)
// 1675, 1600, 1675, 1550, 1500, 1500, 500,  // Right arm + gripper (Index 13 = 0° open)


// =========================== ROS / PWM ======================================
Adafruit_PWMServoDriver pwm(0x40);
rcl_node_t node;
rclc_support_t support;
rclc_executor_t executor;
rcl_subscription_t command_sub;
rcl_publisher_t state_pub;
std_msgs__msg__Float64MultiArray command_msg;
std_msgs__msg__Float64MultiArray state_msg;

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

// =========================== QUINTIC PROFILE ================================
inline float quintic_profile(float t) {
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  return t*t*t*(10.0f + t*(-15.0f + 6.0f*t));
}

// =========================== PWM MAPPING ====================================
uint16_t radians_to_pwm(float rad, int i) {
  rad = constrain(rad, JOINT_MIN[i], JOINT_MAX[i]);
  float norm = (rad - JOINT_MIN[i]) / (JOINT_MAX[i] - JOINT_MIN[i]);
  int pwm_val = SERVO_MIN_US + norm * (SERVO_MAX_US - SERVO_MIN_US);
  
  // Apply trim ONLY for arm joints, not gripper
  if (i != 6 && i != 13) {
    pwm_val += (INIT_PWM[i] - 1500);
  }
  
  pwm_val = ((pwm_val + 2) / 4) * 4;
  return constrain(pwm_val, SERVO_MIN_US, SERVO_MAX_US);
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
  if (msg->data.size != NUM_JOINTS) return;

  last_cmd_time = millis();

  for (int i = 0; i < NUM_JOINTS; i++) {
    uint16_t target;
    joints[i].position = msg->data.data[i];

    if (i == 1 || i == 3 || i == 4)
      target = radians_to_pwm(-joints[i].position, i);
    else
      target = radians_to_pwm(joints[i].position, i);

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

  Wire.begin();
  pwm.begin();
  pwm.setPWMFreq(SERVO_FREQ);

  for (int i = 0; i < NUM_JOINTS; i++) {
    joints[i].position = 0.0;
    joints[i].velocity = 0.0;
    joints[i].current_pwm = INIT_PWM[i];
    joints[i].target_pwm = INIT_PWM[i];
    motion[i].active = false;
    last_pwm[i] = INIT_PWM[i];
    pwm.writeMicroseconds(i, INIT_PWM[i]);
  }

  set_microros_transports();
  delay(1500);

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

  rclc_executor_init(&executor, &support.context, 1, &allocator);
  rclc_executor_add_subscription(
    &executor, &command_sub,
    &command_msg, &command_callback, ON_NEW_DATA);

  state_msg.data.capacity = state_msg.data.size = NUM_JOINTS;
  state_msg.data.data = (double*)malloc(NUM_JOINTS * sizeof(double));
  command_msg.data.capacity = NUM_JOINTS;
  command_msg.data.data = (double*)malloc(NUM_JOINTS * sizeof(double));
}

// =========================== LOOP ===========================================
void loop() {
  // ===== FIX 3: PREVENT EXECUTOR STARVATION =====
  rclc_executor_spin_some(&executor, RCL_MS_TO_NS(10));

  if (millis() - last_cmd_time > COMMAND_TIMEOUT_MS) {
    for (int i = 0; i < NUM_JOINTS; i++)
      motion[i].active = false;
  }

  for (int i = 0; i < NUM_JOINTS; i++) {
    joints[i].current_pwm = get_interpolated_pwm(i);
    if (joints[i].current_pwm != last_pwm[i]) {
      pwm.writeMicroseconds(i, joints[i].current_pwm);
      last_pwm[i] = joints[i].current_pwm;
    }
  }

  if (millis() - last_pub_time >= STATE_PUB_PERIOD_MS) {
    for (int i = 0; i < NUM_JOINTS; i++)
      state_msg.data.data[i] = joints[i].position;
    rcl_publish(&state_pub, &state_msg, NULL);
    last_pub_time = millis();
  }

  delayMicroseconds(LOOP_PERIOD_US);
}