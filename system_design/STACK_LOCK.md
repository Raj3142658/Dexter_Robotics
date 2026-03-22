# Dexter Robotics Stack Lock (v1)

This file freezes the technology choices for the new architecture baseline.

## Locked Stack

- ROS Core: ROS 2 native packages (`rclcpp` / `rclpy`) remain the source of truth.
- Middleware API: Python 3.11, FastAPI, Uvicorn, Pydantic v2.
- Middleware transport: REST for commands + WebSocket for live events.
- Frontend target stack: React + TypeScript + Vite (temporary UI remains vanilla for rapid tests).
- Contract strategy: OpenAPI from FastAPI, typed TS client generated from OpenAPI.
- Observability baseline: structured logs in middleware.

## Architecture Rules

- UI must never call ROS nodes directly.
- All robot intents pass through middleware adapters.
- ROS package internals are not modified for UI concerns.
- Keep middleware modular: adapters/services should be separable.

## Delivery Phases

1. Phase 1: RViz model viewing only (no MoveIt, controllers, gazebo, or hardware control).
2. Phase 2: Read-only ROS state through middleware.
3. Phase 3: Command writes with safety checks.
