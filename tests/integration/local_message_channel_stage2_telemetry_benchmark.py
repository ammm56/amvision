"""阶段 2 Training Telemetry EventRing 与冻结阶段 0 基线的同机比较。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from tests.integration.local_message_channel_stage0_benchmark import (
    _run_telemetry_round,
    summarize_rounds,
)


DEFAULT_BASELINE: Final = Path(".tmp/local-message-channel-stage0/baseline.json")
DEFAULT_OUTPUT: Final = Path(
    ".tmp/local-message-channel-stage2/telemetry-benchmark.json"
)
POLL_INTERVAL_SECONDS: Final = 0.05
ROUND_COUNT: Final = 5
ITERATIONS_PER_ROUND: Final = 30


def evaluate_latency_gate(
    *,
    baseline: dict[str, float],
    current: dict[str, float],
) -> dict[str, object]:
    """按阶段 7 规则判定 P95/P99 是否超过 max(1 ms, 10%) 回退。"""

    limits = {
        percentile: max(value + 1.0, value * 1.10)
        for percentile, value in baseline.items()
    }
    checks = {
        percentile: current[percentile] <= limits[percentile]
        for percentile in ("p95", "p99")
    }
    return {
        "baseline_ms": baseline,
        "current_ms": current,
        "limits_ms": limits,
        "checks": checks,
        "passed": all(checks.values()),
    }


def load_stage0_telemetry_baseline(path: Path) -> tuple[dict[str, float], str]:
    """读取 50 ms poll 的冻结阶段 0 P95/P99 与报告 SHA-256。"""

    raw = path.read_bytes()
    report = json.loads(raw)
    telemetry = report.get("training_telemetry")
    if not isinstance(telemetry, dict):
        raise ValueError("阶段 0 报告缺少 training_telemetry")
    cells = telemetry.get("cells")
    if not isinstance(cells, list):
        raise ValueError("阶段 0 报告缺少 telemetry cells")
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if float(cell.get("poll_interval_seconds", -1)) != POLL_INTERVAL_SECONDS:
            continue
        summary = cell.get("summary")
        if not isinstance(summary, dict):
            break
        median = summary.get("median_of_rounds_ms")
        if not isinstance(median, dict):
            break
        return (
            {"p95": float(median["p95"]), "p99": float(median["p99"])},
            hashlib.sha256(raw).hexdigest(),
        )
    raise ValueError("阶段 0 报告缺少 50 ms telemetry cell")


def run_benchmark(*, baseline_path: Path, output_path: Path) -> dict[str, object]:
    """执行固定预热条件下的 5 轮跨进程 EventRing 延迟测量。"""

    baseline, baseline_sha256 = load_stage0_telemetry_baseline(baseline_path)
    Path(".tmp").mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=".tmp", prefix="local-message-stage2-") as root:
        rounds = [
            _run_telemetry_round(
                root=Path(root) / str(index),
                iterations=ITERATIONS_PER_ROUND,
                poll_interval_seconds=POLL_INTERVAL_SECONDS,
            )
            for index in range(ROUND_COUNT)
        ]
    summary = summarize_rounds(rounds)
    median = summary["median_of_rounds_ms"]
    gate = evaluate_latency_gate(
        baseline=baseline,
        current={"p95": float(median["p95"]), "p99": float(median["p99"])},
    )
    report: dict[str, object] = {
        "schema_id": "amvision.local-message-stage2-telemetry-benchmark.v1",
        "baseline_path": baseline_path.as_posix(),
        "baseline_sha256": baseline_sha256,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "round_count": ROUND_COUNT,
        "iterations_per_round": ITERATIONS_PER_ROUND,
        "summary": summary,
        "gate": gate,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    """解析参数、执行基准并以退出码表达门禁结果。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_benchmark(
        baseline_path=args.baseline.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(report["gate"], ensure_ascii=False, indent=2))
    return 0 if bool(report["gate"]["passed"]) else 1  # type: ignore[index]


if __name__ == "__main__":
    raise SystemExit(main())
