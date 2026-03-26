from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any


def _bootstrap_sys_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


DEFAULT_THRESHOLD = 100.0

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
HOME = "\033[H"
CLEAR_TO_END = "\033[J"


def request_resize(cols: int, rows: int) -> str:
    return f"\033[8;{rows};{cols}t"


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


def short_usd_name(path_or_name: str) -> str:
    if not path_or_name:
        return ""
    s = str(path_or_name)
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    for pref in ("radiation_obstacle_", "radiation_source_", "radiation_sensor_"):
        if s.startswith(pref):
            s = s[len(pref):]
    return s


def clamp_source_name(s: str, max_len: int = 30) -> str:
    s = s or ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


_STOP = False


def _sig_handler(_signum, _frame):
    global _STOP
    _STOP = True


def main():
    _bootstrap_sys_path()

    from runtime.workspace_config import load_monitor_threshold, resolve_selected_world

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=50050)
    p.add_argument("--cfg-root", default="extensions/radiation.simulator/config")
    p.add_argument("--world", default=None, help="threshold를 읽을 world 이름 (비우면 current_world_name 사용)")
    p.add_argument("--topk", type=int, default=5, help="top-k obstacles to show per source")
    p.add_argument("--refresh_hz", type=float, default=5.0, help="screen refresh rate")
    p.add_argument("--threshold", type=float, default=None, help="override threshold; 비우면 worlds/<world>/sensors.toml [monitor].threshold 사용")
    args = p.parse_args()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    world_name = resolve_selected_world(args.world)
    threshold = float(args.threshold) if args.threshold is not None else load_monitor_threshold(args.cfg_root, world_name, default=DEFAULT_THRESHOLD)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.2)

    last_msg: dict[str, Any] | None = None
    last_rx_t = 0.0

    print(request_resize(104, 29) + "\033[2J\033[H" + HIDE_CURSOR, end="", flush=True)

    try:
        next_refresh = time.perf_counter()
        refresh_period = 1.0 / max(1e-6, float(args.refresh_hz))

        while not _STOP:
            try:
                data, _ = sock.recvfrom(65535)
                last_msg = json.loads(data.decode("utf-8"))
                last_rx_t = time.time()
            except socket.timeout:
                pass
            except Exception:
                pass

            now = time.perf_counter()
            if now < next_refresh:
                continue
            next_refresh += refresh_period

            print(HOME + CLEAR_TO_END, end="")

            if not last_msg:
                print(f"{DIM}[monitor] listening udp://{args.host}:{args.port} world={world_name} threshold={threshold:.2f} ...{RESET}")
                continue

            sensor = last_msg.get("sensor", "unknown")
            pos = last_msg.get("pos_m", [0.0, 0.0, 0.0])
            total = float(last_msg.get("total", 0.0))
            per = last_msg.get("per_source", None)
            if per is None:
                per = last_msg.get("sources", []) or []
            else:
                per = per or []

            thr = max(1e-12, float(threshold))
            ratio = total / thr
            ratio_for_color = min(1.0, max(0.0, ratio))
            c_total = gradient_color_by_ratio(ratio_for_color)

            print("=" * 100)
            print(
                f"{BOLD}Radiation Monitor{RESET}  {DIM}(last_rx {time.time()-last_rx_t:.2f}s ago){RESET}\n"
                f"sensor={sensor}   world={world_name}   threshold={threshold:.2f}   "
                f"sensor_pos(m)=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})   "
            )
            print("=" * 100)

            if not per:
                print(f"{DIM}no source data yet{RESET}")
                continue

            print(f"\n{BOLD}Sources{RESET}")
            print("-" * 100)
            print(f"{'source name':<30} | {'dist(m)':>7} | {'I0':>10} | {'trans':>8} | {'loss':>8} | {'I(final)':>12}")
            print("-" * 100)

            for s in per:
                src_name = clamp_source_name(short_usd_name(s.get("name", "")), 30)
                dist_m = float(s.get("dist_m", 0.0))
                intensity = float(s.get("intensity", 0.0))
                trans_factor = float(s.get("att_total", 1.0))
                trans_pct = max(0.0, min(100.0, trans_factor * 100.0))
                loss_pct = max(0.0, min(100.0, (1.0 - trans_factor) * 100.0))
                final = float(s.get("final", 0.0))

                r_s = final / thr
                c_s = gradient_color_by_ratio(min(1.0, max(0.0, r_s)))

                print(f"{src_name:<30} | {dist_m:>7.2f} | {intensity:>10.2f} | {trans_pct:>7.2f}% | {loss_pct:>7.2f}% | {c_s}{final:>12.2f}{RESET}")

                terms = s.get("obstacles", []) or []
                if terms:
                    def score(term: dict[str, Any]) -> float:
                        mu = float(term.get("mu", 0.0))
                        thick = float(term.get("thickness_m", 0.0))
                        return mu * thick

                    terms = sorted(terms, key=score, reverse=True)

                    for term in terms[: int(args.topk)]:
                        oname = short_usd_name(term.get("name", ""))
                        thick = float(term.get("thickness_m", 0.0))
                        mu = float(term.get("mu", 0.0))
                        trans = float(term.get("att", 1.0))
                        loss = max(0.0, min(1.0, 1.0 - trans))
                        print(
                            f"  {DIM}↳{RESET} {oname:<30}  "
                            f"t={thick:>6.2f}  μ={mu:>6.2f}  trans={max(0.0, min(100.0, trans*100.0)):>6.2f}%  loss={max(0.0, min(100.0, loss*100.0)):>6.2f}%{RESET}"
                        )

                print()

            print("-" * 100)
            print(f"\n{BOLD}Total:{RESET} {c_total}{total:.2f}{RESET}")
            print("=" * 100)
            print("", flush=True)

    finally:
        print(SHOW_CURSOR, end="", flush=True)
        print("\n[monitor] launcher stopped.")


if __name__ == "__main__":
    main()
