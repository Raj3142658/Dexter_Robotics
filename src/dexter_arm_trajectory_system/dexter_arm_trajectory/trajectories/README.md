# Trajectory Storage Directory

This directory contains saved trajectory files in YAML format.

## Usage

Trajectories are automatically saved here when using the GUI's "Save" function.

## File Format

Each trajectory file contains:

- `name`: Trajectory identifier
- `description`: Human-readable description
- `timestamp`: Creation time
- `joint_names`: List of joint names
- `duration`: Total trajectory duration (seconds)
- `waypoint_count`: Number of waypoints
- `points`: List of waypoint data with positions, velocities, and timestamps

## Example

See `example_pick_place.yaml` for reference.
