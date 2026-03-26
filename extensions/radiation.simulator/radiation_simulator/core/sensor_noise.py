from __future__ import annotations

from typing import Any


# Placeholder hook for future sensor noise models.
# 추정 모델 도입 및 실제 센서 환경을 고려했을 때 노이즈가 추가되어야 한다.
# 1차적으로 Gaussian Noise를 추가할 예정이며, (추정 모델에서 제곱오차 정규화 형태의 이차식으로)
# 추후에 더 물리적으로 타당한 Possion Noise로 전환할 예정임. (최적화 식에 log 항이 들어가 최적화 무거워져서 후순위로 미룸)
def apply_sensor_noise(detected: float, *, context: dict[str, Any] | None = None) -> float:
    return float(detected)
