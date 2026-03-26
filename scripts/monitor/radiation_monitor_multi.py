from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Dict, Tuple


def _bootstrap_sys_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


DEFAULT_THRESHOLD = 100.0

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
WHITE = "\033[1;37m"

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
HOME = "\033[H"
CLEAR_TO_END = "\033[J"


def rgb_fg(r: int, g: int, b: int) -> str:
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f"\033[38;2;{r};{g};{b}m"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def gradient_color_by_ratio(ratio: float) -> str:
    x = max(0.0, min(1.0, float(ratio)))
    stops = [
        (0.00, (0, 120, 255)),
        (0.33, (0, 255, 255)),
        (0.55, (0, 255, 0)),
        (0.78, (255, 255, 0)),
        (1.00, (255, 0, 0)),
    ]
    for i in range(len(stops) - 1):
        x0, c0 = stops[i]
        x1, c1 = stops[i + 1]
        if x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            r = lerp(c0[0], c1[0], t)
            g = lerp(c0[1], c1[1], t)
            b = lerp(c0[2], c1[2], t)
            return rgb_fg(r, g, b)
    return rgb_fg(255, 0, 0)


def main():
    _bootstrap_sys_path()

    from runtime.workspace_config import load_monitor_threshold, resolve_selected_world

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=50050)
    p.add_argument("--cfg-root", default="extensions/radiation.simulator/config")
    p.add_argument("--world", default=None, help="threshold를 읽을 world 이름 (비우면 current_world_name 사용)")
    p.add_argument("--refresh_hz", type=float, default=5.0)
    p.add_argument("--threshold", type=float, default=None, help="override threshold; 비우면 worlds/<world>/sensors.toml [monitor].threshold 사용")
    args = p.parse_args()

    world_name = resolve_selected_world(args.world)
    threshold = float(args.threshold) if args.threshold is not None else load_monitor_threshold(args.cfg_root, world_name, default=DEFAULT_THRESHOLD)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.2)

    latest: Dict[str, Tuple[float, Tuple[float, float, float], float]] = {}

    print("\033[2J\033[H" + HIDE_CURSOR, end="", flush=True)

    try:
        next_refresh = time.perf_counter()
        refresh_period = 1.0 / max(1e-6, float(args.refresh_hz))

        while True:
            try:
                data, _ = sock.recvfrom(65535)
                msg = json.loads(data.decode("utf-8"))
                sensor = str(msg.get("sensor", "unknown"))
                total = float(msg.get("total", 0.0))
                pos = msg.get("pos_m", [0.0, 0.0, 0.0])
                pos_t = (float(pos[0]), float(pos[1]), float(pos[2]))
                latest[sensor] = (total, pos_t, time.time())
            except socket.timeout:
                pass

            now = time.perf_counter()
            if now < next_refresh:
                continue
            next_refresh += refresh_period

            print(HOME + CLEAR_TO_END, end="")

            if not latest:
                print(f"{DIM}[monitor] listening udp://{args.host}:{args.port} world={world_name} threshold={threshold:.2f} ...{RESET}")
                continue

            items = sorted(latest.items(), key=lambda kv: kv[0])

            print("=" * 90)
            print(
                f"{BOLD}Radiation Monitor (Multi Summary){RESET}    "
                f"listening udp://{args.host}:{args.port}\nworld={world_name}   threshold={threshold:.2f}   "
                f"sensors={WHITE}{len(items)}{RESET}"
            )
            print("=" * 90)

            print(f"{'sensor':<35} | {'pos(m)':<24} | {'total':>12} | {'age(s)':>6}")
            print("-" * 90)

            now_wall = time.time()
            for sensor, (total, pos, rx_t) in items:
                thr = max(1e-12, float(threshold))
                ratio_for_color = max(0.0, min(1.0, float(total) / thr))
                c_total = gradient_color_by_ratio(ratio_for_color)
                age = now_wall - rx_t
                pos_s = f"({pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f})"
                print(f"{sensor:<35} | {pos_s:<24} | {c_total}{total:>12.2f}{RESET} | {age:>6.2f}")

            print("-" * 90)
            print("", flush=True)

    except KeyboardInterrupt:
        pass
    finally:
        print(SHOW_CURSOR, end="", flush=True)
        print("\n[monitor] launcher stopped.")


if __name__ == "__main__":
    main()
