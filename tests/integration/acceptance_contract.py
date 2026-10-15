"""工程验收的阶段、总体判定与尽力清理；不进入生产请求路径。"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from pathlib import Path

from tests.integration.acceptance_evidence import write_evidence


def positive_seconds(value: object, name: str, *, allow_zero: bool = False) -> float:
    """拒绝 NaN、无穷和负时长，避免循环未执行却登记通过。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不能是布尔值")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"{name} 必须是有限{'非负' if allow_zero else '正'}数")
    return number


class AcceptancePhases:
    """用原子文件向同机采样进程发布阶段；monotonic 时钟不受校时影响。"""

    def __init__(self, path: Path, *, minimum_measure_seconds: float) -> None:
        """path 属于独占验收目录；minimum_measure_seconds 是实际负载时长。"""
        self.path = path
        self.minimum_measure_seconds = positive_seconds(minimum_measure_seconds, "measure_seconds")
        self.events: list[dict] = []

    def enter(self, phase: str) -> None:
        """记录有界阶段变更；稳定负载只能开始一次，避免重试拼凑时长。"""
        if phase not in {"prepare", "fault", "recovery", "warmup", "measure", "drain", "cleanup", "completed", "failed"}:
            raise ValueError(f"未知验收阶段：{phase}")
        if len(self.events) >= 32 or (phase == "measure" and any(e["phase"] == phase for e in self.events)):
            raise ValueError("验收阶段数量超限或重复开始测量")
        self.events.append({"phase": phase, "monotonic": time.monotonic()})
        write_evidence(self.path, {"format_id": "amvision.acceptance-phases.v1",
                                  "minimum_measure_seconds": self.minimum_measure_seconds,
                                  "events": self.events})


def read_measurement(path: Path) -> dict:
    """读取测量区间；非测量阶段不能进入稳定资源统计。"""
    if not path.exists():
        return {"phase": "prepare", "started": None, "ended": None, "minimum_seconds": None}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format_id") != "amvision.acceptance-phases.v1":
        raise ValueError("验收阶段格式不匹配")
    events = payload["events"]
    starts = [i for i, event in enumerate(events) if event["phase"] == "measure"]
    if len(starts) > 1:
        raise ValueError("稳定负载测量不能由多次运行拼接")
    index = starts[0] if starts else None
    return {"phase": events[-1]["phase"] if events else "prepare",
            "started": events[index]["monotonic"] if index is not None else None,
            "ended": events[index + 1]["monotonic"] if index is not None and index + 1 < len(events) else None,
            "minimum_seconds": payload["minimum_measure_seconds"]}


def acceptance_result(gates: dict[str, str], required: tuple[str, ...]) -> dict:
    """必选门禁失败优先；未测、仅观测和不可用均不能成为整体通过。"""
    failures = [name for name in required if gates.get(name) == "failed"]
    incomplete = [name for name in required if gates.get(name) not in {"passed", "failed"}]
    status = "failed" if failures else "incomplete" if incomplete else "passed"
    return {"format_id": "amvision.engineering-acceptance.v2", "status": status,
            "passed": status == "passed", "required_gates": list(required),
            "gates": gates, "failures": failures, "incomplete": incomplete}


def cleanup_all(steps: list[tuple[str, Callable[[], object]]]) -> list[str]:
    """逐项尽力回收，前一步超时或失败不能阻止后续步骤。"""
    errors = []
    for name, action in steps:
        try:
            action()
        except Exception as error:
            errors.append(f"{name}: {type(error).__name__}: {error}")
    return errors
