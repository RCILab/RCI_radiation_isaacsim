# Radiation Isaac Sim Workspace

`radiation_isaacsim_ws` is an Isaac Sim workspace for radiation simulation with three main concepts:

- `source`: emits radiation with a configured intensity
- `obstacle`: attenuates radiation with a material-dependent coefficient
- `sensor`: measures detected intensity after distance and attenuation effects

The radiation logic lives in the custom Isaac Sim extension `radiation.simulator`. Scenario logic such as robot spawning, demo setup, logging, and monitoring stays in `scripts/`.

## Overview

This workspace is organized around two main use cases.

- `reactor_room`: a multi-robot Jackal scenario in a larger world
- `demo_world`: a compact validation scene for source, obstacle, and sensor behavior

In both cases, the radiation-related behavior is handled by the extension, while scripts are used to launch scenarios, move robots or objects, and display or forward results.

## Quick Start

### Run Directly on Ubuntu 22.04

**The first launch of Isaac Sim can take a while for each launcher or entry script because startup, extension loading, and cache initialization are slow on the first run. If the window does not appear immediately, wait a bit before assuming it failed.**

Main simulation with a separate monitor window:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation_multi.sh
```

Demo world with a separate monitor window:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world_multi.sh
```

### Run with Docker on Ubuntu 22.04

Build the image once:

```bash
cd /path/to/radiation_isaacsim_ws
docker compose build
```

Main simulation with GUI and a separate monitor terminal:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_simulation_multi.sh
```

Demo world with GUI and a separate monitor terminal:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_demo_world_multi.sh
```

`docker_run_simulation_multi.sh` accepts the same runtime arguments as `run_simulation.py`. For example, `./tools/docker_run_simulation_multi.sh --num 4` increases the robot count, and you can also scale the default spawn set by editing `config/<world>/spawn/jackal_spawns.csv`.

## Directory Layout

- `assets/`
  - World USD/USD[A] files and robot assets used by the scenarios.
  - **`reactor_room` assets are based on the environment described in Wright et al., "Simulating Ionising Radiation in Gazebo for Robotic Nuclear Inspection Challenges" (Robotics 2021, 10, 86, https://doi.org/10.3390/robotics10030086) and the public repository https://github.com/EEEManchester/gazebosim_world_generator.**
  - **Keep the original attribution when using these assets, and obtain permission from the original authors or rightsholders before redistributing the asset files.**
- `config/`
  - Workspace-level settings.
  - `current_world_name.txt` selects the default world when a script does not receive `--cfg-world`.
  - `config/<world>/spawn/` stores per-world spawn CSV files.
- `extensions/radiation.simulator/`
  - The radiation extension itself.
  - `config/worlds/<world>/` contains per-world radiation configuration:
    - `world.toml`
    - `sources.toml`
    - `obstacles.toml`
    - `sensors.toml`
- `scripts/`
  - `run_simulation.py`: main reactor-room style scenario runner
  - `demo/run_demo_world.py`: demo scene with moving shields and UI controls
  - `runtime/`: shared helpers for world loading, runtime setup, and workspace path resolution
  - `spawn/`: robot spawning and collision filtering helpers
  - `drive/`: simple differential drive and raycast-based avoidance
  - `monitor/`: UDP-based text monitors for sensor readings
  - `debug/`: debugging and validation scripts
  - `ros2/`: optional UDP-to-ROS2 bridge (demo ver.)
- `tools/`
  - Shell wrappers for common launch flows
- `docker/`
  - Docker assets for Isaac Sim container-based execution

## Radiation Configuration

Each world under `extensions/radiation.simulator/config/worlds/<world>/` is described by four TOML files.

- `world.toml`
  - Selects the USD file and root path for the world
- `sources.toml`
  - Defines radiation sources and source parameters
- `obstacles.toml`
  - Defines or overrides obstacle tagging and attenuation properties
- `sensors.toml`
  - Defines sensor defaults and monitor-related settings such as threshold values

`world.toml` now supports relative USD paths. A value such as `reactor_room_2.usd` is resolved against `assets/world/` by default.

## World Selection

The default world is stored in:

- `config/current_world_name.txt`

For example, if this file contains `reactor_room`, scripts that rely on the default world will load the reactor-room configuration unless you override it with a command-line argument.

## Main Entry Points

### 1. Main Simulation

Use this for the Jackal-based scenario.

- Script: `scripts/run_simulation.py`
- Wrapper: `tools/run_simulation.sh`
- Monitor wrapper: `tools/run_simulation_multi.sh`

Typical responsibilities:

- load the selected world
- spawn multiple Jackals from CSV
- attach radiation sensors through the extension runtime
- drive robots with simple reactive avoidance
- publish readings over UDP

### 2. Demo World

Use this for validating attenuation and distance behavior in a simple scene.

- Script: `scripts/demo/run_demo_world.py`
- Wrapper: `tools/run_demo_world.sh`
- Monitor wrapper: `tools/run_demo_world_multi.sh`

Typical responsibilities:

- load `demo_world`
- create a fixed source, a movable sensor, and moving shield walls
- expose simple GUI controls
- publish readings over UDP for monitor-based inspection

## Local Usage

### Prerequisites

You need a local Isaac Sim Python environment. The shell wrappers in `tools/` look for a conda environment in this order:

1. `radiation_isaacsim`
2. `radiation_isaaclab`

They also expect `conda.sh` under `${HOME}/miniconda3/etc/profile.d/conda.sh` unless you override `CONDA_ROOT`.

### Run the Main Simulation

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation.sh
```

Headless example:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation.sh --headless --steps 300
```

Launch with a separate multi-sensor monitor window(recommended):

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation_multi.sh
```

### Run the Demo World

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world.sh
```

Headless example:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world.sh --headless --steps 300
```

Launch with a separate single-sensor monitor window(recommended):

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world_multi.sh
```

### Run Scripts Directly

If you prefer not to use the wrappers:

```bash
cd /path/to/radiation_isaacsim_ws
source tools/_env.sh
python scripts/run_simulation.py 
python scripts/demo/run_demo_world.py
```

## Spawn Data

Robot spawn positions are stored outside the extension under:

- `config/<world>/spawn/jackal_spawns.csv`

This keeps scenario-specific robot placement separate from the radiation extension itself.

If you want more robots in the main simulation, you can either pass `--num` to `tools/run_simulation.sh`, `tools/run_simulation_multi.sh`, or `tools/docker_run_simulation_multi.sh`, or add more rows to `config/<world>/spawn/jackal_spawns.csv`.

## Monitoring and Output

Sensor readings are published over UDP.

- `scripts/monitor/radiation_monitor.py`
  - single-sensor oriented monitor
- `scripts/monitor/radiation_monitor_multi.py`
  - multi-sensor monitor
- `scripts/ros2/radiation_udp_to_ros2.py`
  - optional ROS2 bridge

Monitor threshold values are configured per world in `extensions/radiation.simulator/config/worlds/<world>/sensors.toml`.

## Docker Usage

Docker support is intended for a self-contained Isaac Sim deployment without relying on a local `IsaacLab` folder.

### What Docker Uses

- `docker/Dockerfile`
- `docker-compose.yml`
- `docker/entrypoint.sh`

The Docker image is based on:

- `nvcr.io/nvidia/isaac-sim:5.1.0`

### Docker Prerequisites

You need:

- Docker
- NVIDIA Container Toolkit
- an NVIDIA GPU with a working driver
- access to pull the Isaac Sim image from NGC
- `docker login nvcr.io` if your environment requires registry authentication

### Build the Image

```bash
cd /path/to/radiation_isaacsim_ws
docker compose build
```

### Run Headless Main Simulation

```bash
cd /path/to/radiation_isaacsim_ws
docker compose up radiation-headless
```

### Run an Interactive Shell Inside the Container

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless bash
```

### Run the Demo Headless

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless run-demo --headless --steps 300
```

### Run the Main Simulation Headless with Custom Args

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless run-simulation --headless --steps 300
```

### Run Arbitrary Workspace Scripts

You are not limited to the preset commands in `docker-compose.yml`. Those services are only convenience presets. You can still run arbitrary scripts inside the same image.

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless bash
docker compose run --rm radiation-headless python scripts/debug/run_sweep.py --headless
```

### GUI Containers

GUI-oriented containers are also defined in `docker-compose.yml`.

Main simulation:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_simulation_multi.sh
```

Demo world:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_demo_world_multi.sh
```

These launch a GUI container and a monitor in a separate terminal window, similar to the local shell wrappers. This is most natural on a Linux host with X11. If the new monitor terminal does not have Docker socket permission, it may prompt for `sudo`. If you have just added your user to the `docker` group, logging out and back in is still recommended.

## Recommended Workflow

If you are actively developing the radiation logic:

1. validate behavior locally with `run_demo_world`
2. verify the larger scenario with `run_simulation`
3. use the monitors to inspect UDP output
4. package and test the same workspace with Docker

## Notes

- The extension is designed to keep radiation behavior inside `extensions/radiation.simulator`.
- Scenario orchestration stays in `scripts/`.
- World configuration is per-world and data-driven.
- The workspace is meant to run independently from an external `IsaacLab` project folder when used with Isaac Sim directly or with Isaac Sim Docker.

## Contact

Maintainer: jth8090 ([jth8090@khu.ac.kr](mailto:jth8090@khu.ac.kr))  
Lab: [RCI Lab @ Kyung Hee University](https://rcilab.khu.ac.kr)
