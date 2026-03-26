#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
import time
from typing import Dict, Optional, Tuple

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import Float32, Float32MultiArray


def _robot_id_from_sensor_label(sensor_label: str) -> str:
    # 예: "jackal_00/RadiationSensor" -> "jackal_00"
    s = (sensor_label or "").strip()
    if "/" in s:
        s = s.split("/", 1)[0]
    s = s.strip()
    if not s:
        return "unknown"
    # ROS topic 안전 문자만 남기기
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s)
    return s


class UdpToRos2Bridge(Node):
    def __init__(self, host: str, port: int, topic_ns: str, timeout_s: float):
        super().__init__("radiation_udp_to_ros2")

        self._host = host
        self._port = int(port)
        self._topic_ns = topic_ns.strip("/")
        self._timeout_s = float(timeout_s)

        # sensor data 용 QoS (best effort가 일반적이지만 echo 확인 목적이면 reliable도 OK)
        self._qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self._pubs: Dict[str, Tuple[rclpy.publisher.Publisher, float]] = {}  # robot_id -> (pub, last_seen_walltime)

        # robot_id -> latest total
        self._latest_total: Dict[str, float] = {}

        # 전체 totals 토픽 (Float32MultiArray)
        self._all_topic = self._topic_for_totals()
        self._pub_all = self.create_publisher(Float32MultiArray, self._all_topic, self._qos)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # 같은 포트에 monitor도 같이 붙이고 싶을 수 있어서(환경에 따라 다름)
        # 가능하면 reuse 옵션을 켜 둠. (그래도 충돌 나면 포트 분리해야 함)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass

        self._sock.bind((self._host, self._port))
        self._sock.settimeout(0.1)

        self.get_logger().info(f"listening udp://{self._host}:{self._port}")
        self.get_logger().info(f"publishing to /{self._topic_ns}/<robot_id>/total (std_msgs/Float32)")
        # 추가 처리
        self.get_logger().info(f"publishing to {self._all_topic} (std_msgs/Float32MultiArray, robot_id sorted)")

        # 주기적으로 오래된 퍼블리셔 정리(선택)
        self.create_timer(1.0, self._cleanup_old_publishers)

    def _topic_for(self, robot_id: str) -> str:
        # /radiation/jackal_00/total 형태
        if self._topic_ns:
            return f"/{self._topic_ns}/{robot_id}/total"
        return f"/{robot_id}/radiation/total"

    # 추가 처리
    def _topic_for_totals(self) -> str:
        # /radiation/totals 형태
        if self._topic_ns:
            return f"/{self._topic_ns}/totals"
        return "/radiation/totals"

    def _get_pub(self, robot_id: str):
        now = time.time()
        if robot_id in self._pubs:
            pub, _ = self._pubs[robot_id]
            self._pubs[robot_id] = (pub, now)
            return pub

        topic = self._topic_for(robot_id)
        pub = self.create_publisher(Float32, topic, self._qos)
        self._pubs[robot_id] = (pub, now)
        self.get_logger().info(f"created publisher: {topic}")
        return pub

    def _cleanup_old_publishers(self):
        if self._timeout_s <= 0:
            return
        now = time.time()
        dead = [rid for rid, (_, t) in self._pubs.items() if (now - t) > self._timeout_s]
        for rid in dead:
            # rclpy는 publisher destroy를 제공하지만, 굳이 안 해도 문제는 없어서 dict만 정리
            self._pubs.pop(rid, None)
            # 추가 처리: 최신값도 같이 정리
            self._latest_total.pop(rid, None)

    # 추가 처리
    def _publish_all_totals(self):
        """
        현재까지 수신된 최신 total들을 robot_id 사전순으로 정렬해 Float32MultiArray로 publish.
        """
        if not self._latest_total:
            return

        rids = sorted(self._latest_total.keys())
        arr = Float32MultiArray()
        arr.data = [float(self._latest_total[rid]) for rid in rids]
        self._pub_all.publish(arr)

    def spin_forever(self):
        while rclpy.ok():
            # ROS callback도 처리
            rclpy.spin_once(self, timeout_sec=0.0)

            # UDP 수신
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception as e:
                self.get_logger().warn(f"udp recv error: {type(e).__name__}: {e}")
                continue

            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue

            sensor = str(msg.get("sensor", ""))
            total = float(msg.get("total", 0.0))

            robot_id = _robot_id_from_sensor_label(sensor)
            pub = self._get_pub(robot_id)

            out = Float32()
            out.data = float(total)
            pub.publish(out)

            # 추가 처리: 최신값 저장 + 전체 배열 토픽 publish
            self._latest_total[robot_id] = float(total)
            self._publish_all_totals()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=50050)
    ap.add_argument("--topic-ns", default="radiation", help="ex) radiation -> /radiation/<robot>/total")
    ap.add_argument("--cleanup-timeout", type=float, default=0.0, help=">0이면 timeout 지난 robot pub 정리(초)")
    args = ap.parse_args()

    rclpy.init()
    node = UdpToRos2Bridge(args.host, args.port, args.topic_ns, args.cleanup_timeout)
    try:
        node.spin_forever()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
