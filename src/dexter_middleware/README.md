# Dexter Middleware (MVP)

Temporary middleware for flow validation before full architecture expansion.

## Run

```bash
cd /home/raj/Dexter_Robotics/src/dexter_middleware
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Core Endpoints

- `GET /health`
- `GET /status`
- `POST /connect`
- `POST /disconnect`
- `POST /enable`
- `POST /disable`
- `POST /jog/joint`
- `POST /trajectory/execute`
- `POST /trajectory/pause`
- `POST /trajectory/resume`
- `POST /trajectory/stop`
- `WS /ws/events`

## ROS Session Endpoints

- `GET /ros/rviz/status`
- `POST /ros/rviz/start`
- `POST /ros/rviz/stop`
- `GET /ros/moveit/status`
- `POST /ros/moveit/start`
- `POST /ros/moveit/stop`
- `GET /ros/gazebo/status`
- `POST /ros/gazebo/start`
- `POST /ros/gazebo/stop`
- `GET /ros/full-stack/status`
- `POST /ros/full-stack/start`
- `POST /ros/full-stack/stop`
- `GET /ros/hardware/status`
- `POST /ros/hardware/start`
- `POST /ros/hardware/stop`
