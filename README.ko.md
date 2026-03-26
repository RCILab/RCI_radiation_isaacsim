# Radiation Isaac Sim Workspace

`radiation_isaacsim_ws`는 방사선 시뮬레이션을 위한 Isaac Sim 워크스페이스입니다. 핵심 개념은 세 가지입니다.

- `source`: 설정된 세기로 방사선을 방출하는 요소
- `obstacle`: 재질별 감쇠 계수에 따라 방사선을 감쇠시키는 요소
- `sensor`: 거리 감쇠와 차폐 감쇠가 반영된 최종 intensity를 측정하는 요소

방사선 관련 핵심 로직은 Isaac Sim extension인 `radiation.simulator` 안에 들어 있고, 로봇 스폰, 데모 구성, 로깅, 모니터링 같은 시나리오 로직은 `scripts/` 아래에 분리되어 있습니다.

## 개요

이 워크스페이스는 크게 두 가지 사용 시나리오를 중심으로 구성되어 있습니다.

- `reactor_room`: 여러 대의 Jackal 로봇이 등장하는 메인 시나리오
- `demo_world`: source, obstacle, sensor 동작을 빠르게 검증하기 위한 소형 데모 시나리오

두 경우 모두 방사선과 직접 관련된 기능은 extension이 담당하고, 스크립트는 월드 실행, 객체 이동, 모니터링, 시나리오 제어를 담당합니다.

## Quick Start

### Ubuntu 22.04에서 바로 실행

**Isaac Sim은 launcher나 entry script마다 첫 실행 시 startup, extension 로딩, cache 초기화 때문에 꽤 오래 걸릴 수 있습니다. 창이 바로 뜨지 않아도 조금 기다려 주세요.**

메인 시뮬레이션을 별도 monitor 창과 함께 실행:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation_multi.sh
```

데모 월드를 별도 monitor 창과 함께 실행:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world_multi.sh
```

### Ubuntu 22.04에서 Docker로 실행

이미지는 한 번만 빌드하면 됩니다.

```bash
cd /path/to/radiation_isaacsim_ws
docker compose build
```

메인 시뮬레이션을 GUI + 별도 monitor 터미널로 실행:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_simulation_multi.sh
```

데모 월드를 GUI + 별도 monitor 터미널로 실행:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_demo_world_multi.sh
```

`docker_run_simulation_multi.sh`는 `run_simulation.py`와 같은 실행 인자를 받을 수 있습니다. 예를 들어 `./tools/docker_run_simulation_multi.sh --num 4`처럼 실행하면 로봇 대수를 늘릴 수 있고, 기본 스폰 배치는 `config/<world>/spawn/jackal_spawns.csv`를 늘려서 확장할 수도 있습니다.

## 폴더 구조

- `assets/`
  - 월드 USD/USD[A] 파일과 로봇 assets가 들어 있습니다.
  - **`reactor_room` 의 assets는 Wright et al., "Simulating Ionising Radiation in Gazebo for Robotic Nuclear Inspection Challenges" (Robotics 2021, 10, 86, https://doi.org/10.3390/robotics10030086) 논문과 공개 저장소 https://github.com/EEEManchester/gazebosim_world_generator 를 기반으로 사용합니다.**
  - **이 assets을 사용할 때는 원 출처 표기를 유지하고, 자산 파일 자체를 재배포할 경우 원 저작자 또는 권리 보유자의 허락을 받는 것을 권장합니다.**
- `config/`
  - 워크스페이스 수준 설정이 들어 있습니다.
  - `current_world_name.txt`는 기본 월드 이름을 정합니다.
  - `config/<world>/spawn/`에는 월드별 스폰 CSV가 들어 있습니다.
- `extensions/radiation.simulator/`
  - 방사선 extension 본체입니다.
  - `config/worlds/<world>/` 아래에 월드별 방사선 설정이 들어 있습니다.
    - `world.toml`
    - `sources.toml`
    - `obstacles.toml`
    - `sensors.toml`
- `scripts/`
  - `run_simulation.py`: reactor_room 계열 메인 시나리오 실행기
  - `demo/run_demo_world.py`: moving shield와 UI가 포함된 데모 실행기
  - `runtime/`: 월드 로딩, runtime 부착, 경로 해석용 공용 helper
  - `spawn/`: 로봇 스폰 및 충돌 필터링 helper
  - `drive/`: 간단한 차동 구동과 raycast 기반 회피 주행
  - `monitor/`: UDP 기반 텍스트 모니터
  - `debug/`: 디버깅 및 검증용 스크립트
  - `ros2/`: 선택적으로 사용할 UDP-to-ROS2 bridge (demo 버전)
- `tools/`
  - 자주 쓰는 실행 흐름을 감싼 shell wrapper
- `docker/`
  - Isaac Sim 컨테이너 실행을 위한 Docker 자산

## 방사선 설정 구조

각 월드는 `extensions/radiation.simulator/config/worlds/<world>/` 아래의 네 개 TOML 파일로 구성됩니다.

- `world.toml`
  - 사용할 USD 파일과 root path를 정의합니다.
- `sources.toml`
  - radiation source와 source 파라미터를 정의합니다.
- `obstacles.toml`
  - obstacle 태깅과 감쇠 관련 속성을 정의하거나 override합니다.
- `sensors.toml`
  - sensor 기본값과 monitor threshold 같은 표시 관련 설정을 정의합니다.

`world.toml`의 `usd`는 상대경로를 지원합니다. 예를 들어 `reactor_room_2.usd`처럼 적으면 기본적으로 `assets/world/` 아래에서 찾습니다.

## 월드 선택 방식

기본 월드 이름은 아래 파일에 저장됩니다.

- `config/current_world_name.txt`

예를 들어 이 파일에 `reactor_room`이 적혀 있으면, 별도로 `--cfg-world`를 주지 않는 스크립트는 기본적으로 reactor_room 설정을 사용합니다.

## 주요 실행 진입점

### 1. 메인 시뮬레이션

Jackal 기반 메인 시나리오를 실행할 때 사용합니다.

- 스크립트: `scripts/run_simulation.py`
- wrapper: `tools/run_simulation.sh`
- monitor wrapper: `tools/run_simulation_multi.sh`

이 경로는 주로 다음 일을 합니다.

- 선택된 월드 로드
- CSV 기반으로 Jackal 여러 대 스폰
- extension runtime을 통해 radiation sensor 부착
- 간단한 reactive avoidance로 로봇 주행
- 센서 값을 UDP로 송신

### 2. 데모 월드

거리 감쇠와 차폐 감쇠를 간단한 장면에서 검증할 때 사용합니다.

- 스크립트: `scripts/demo/run_demo_world.py`
- wrapper: `tools/run_demo_world.sh`
- monitor wrapper: `tools/run_demo_world_multi.sh`

이 경로는 주로 다음 일을 합니다.

- `demo_world` 로드
- 고정 source, 이동 가능한 sensor, moving shield wall 구성
- 간단한 GUI 제공
- 모니터 확인을 위한 UDP 송신

## 로컬 실행 방법

### 준비 사항

로컬에서 실행하려면 Isaac Sim Python 환경이 필요합니다. `tools/` 아래 shell wrapper는 conda 환경을 아래 순서로 찾습니다.

1. `radiation_isaacsim`
2. `radiation_isaaclab`

또한 기본적으로 `${HOME}/miniconda3/etc/profile.d/conda.sh`를 기대하며, 필요하면 `CONDA_ROOT`로 바꿀 수 있습니다.

### 메인 시뮬레이션 실행

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation.sh
```

headless 예시:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation.sh --headless --steps 300
```

별도 sensor monitor 창과 함께 실행(추천):

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_simulation_multi.sh
```

### 데모 월드 실행

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world.sh
```

headless 예시:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world.sh --headless --steps 300
```

별도 sensor monitor 창과 함께 실행(추천):

```bash
cd /path/to/radiation_isaacsim_ws
./tools/run_demo_world_multi.sh
```

### 스크립트를 직접 실행하는 방법

wrapper를 사용하지 않고 직접 실행하고 싶다면:

```bash
cd /path/to/radiation_isaacsim_ws
source tools/_env.sh
python scripts/run_simulation.py --headless --steps 300
python scripts/demo/run_demo_world.py
```

## 스폰 데이터

로봇 스폰 위치는 extension 바깥의 아래 경로에 저장됩니다.

- `config/<world>/spawn/jackal_spawns.csv`

이렇게 분리해두면 로봇 배치 같은 시나리오 데이터와 방사선 extension 자체를 깔끔하게 나눠집니다.

메인 시뮬레이션에서 로봇 수를 늘리고 싶다면 `tools/run_simulation.sh`, `tools/run_simulation_multi.sh`, `tools/docker_run_simulation_multi.sh`에 `--num` 인자를 넘기거나, `config/<world>/spawn/jackal_spawns.csv`에 행을 더 추가하면 됩니다.

## 모니터링과 출력

sensor reading은 UDP로 송신됩니다.

- `scripts/monitor/radiation_monitor.py`
  - 단일 sensor 중심 monitor
- `scripts/monitor/radiation_monitor_multi.py`
  - 다중 sensor monitor
- `scripts/ros2/radiation_udp_to_ros2.py`
  - 선택적으로 사용할 ROS2 bridge

monitor의 threshold 값은 각 월드의 `extensions/radiation.simulator/config/worlds/<world>/sensors.toml`에서 설정합니다.

## Docker 사용 방법

Docker 지원은 외부 `IsaacLab` 폴더 없이, Isaac Sim 기반으로 워크스페이스를 독립 실행하기 위한 목적입니다.

### Docker에서 사용하는 파일

- `docker/Dockerfile`
- `docker-compose.yml`
- `docker/entrypoint.sh`

Docker 베이스 이미지는 다음을 사용합니다.

- `nvcr.io/nvidia/isaac-sim:5.1.0`

### Docker 실행 전 준비 사항

다음이 필요합니다.

- Docker
- NVIDIA Container Toolkit
- 정상 동작하는 NVIDIA GPU 드라이버
- NGC에서 Isaac Sim 이미지를 pull할 수 있는 권한
- 필요하면 `docker login nvcr.io`

### 이미지 빌드

```bash
cd /path/to/radiation_isaacsim_ws
docker compose build
```

### headless 메인 시뮬레이션 실행

```bash
cd /path/to/radiation_isaacsim_ws
docker compose up radiation-headless
```

### 컨테이너 안으로 들어가기

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless bash
```

### 데모를 headless로 실행

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless run-demo --headless --steps 300
```

### 메인 시뮬레이션을 headless로 인자와 함께 실행

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless run-simulation --headless --steps 300
```

### 워크스페이스의 다른 스크립트 직접 실행

`docker-compose.yml`에 들어 있는 command는 편의용 preset일 뿐이고, 그 안에 적힌 것만 실행할 수 있는 것은 아닙니다. 같은 이미지 안에서 원하는 스크립트를 직접 실행할 수 있습니다.

```bash
cd /path/to/radiation_isaacsim_ws
docker compose run --rm radiation-headless bash
docker compose run --rm radiation-headless python scripts/debug/run_sweep.py --headless
```

### GUI 컨테이너

`docker-compose.yml`에는 GUI용 컨테이너가 들어 있습니다.

메인 시뮬레이션:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_simulation_multi.sh
```

데모 월드:

```bash
cd /path/to/radiation_isaacsim_ws
./tools/docker_run_demo_world_multi.sh
```

이 wrapper는 로컬 shell wrapper와 비슷하게 GUI 컨테이너와 monitor를 각각 다른 터미널에 띄웁니다. 이 방식은 Linux host + X11 환경에서 가장 자연스럽습니다. 새 monitor 터미널에 Docker 소켓 권한이 없으면 `sudo` 비밀번호를 물을 수 있습니다. 또 사용자를 `docker` 그룹에 막 추가한 직후라면 로그아웃 후 다시 로그인하는 것을 권장합니다.

## 권장 사용 흐름

방사선 로직을 개발하거나 검증할 때는 보통 아래 순서가 자연스럽습니다.

1. `run_demo_world`로 감쇠와 거리 효과를 먼저 검증
2. `run_simulation`으로 큰 시나리오를 확인
3. monitor로 UDP 출력을 점검
4. 마지막으로 같은 워크스페이스를 Docker로 패키징해서 재현성 확인

## 참고

- 방사선 기능은 가능한 한 `extensions/radiation.simulator` 안에 유지하는 것을 목표로 합니다.
- 시나리오 orchestration은 `scripts/`에 둡니다.
- 월드 설정은 per-world 데이터 중심 구조입니다.
- 이 워크스페이스는 Isaac Sim 직접 실행 또는 Isaac Sim Docker 기준으로 외부 `IsaacLab` 프로젝트 폴더 없이 독립적으로 사용하는 것을 목표로 합니다.

## Contact

Maintainer: jth8090 ([jth8090@khu.ac.kr](mailto:jth8090@khu.ac.kr))  
Lab: [RCI Lab @ Kyung Hee University](https://rcilab.khu.ac.kr)
