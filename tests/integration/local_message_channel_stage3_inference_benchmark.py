"""阶段 3 Inference adapter 对阶段 0 正式链路的同机回归基准。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import statistics
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.ipc.local_message_profiles import (  # noqa: E402
    INFERENCE_RPC_PROFILE_V1,
)
from tests.integration.local_message_channel_stage0_benchmark import (  # noqa: E402
    _deterministic_text,
    _run_inference_round,
)


@dataclass(frozen=True, slots=True)
class BenchmarkSettings:
    """冻结阶段 3 小响应回归的采样参数。"""

    output_path: str
    stage0_report_path: str
    rounds: int = 5
    warmup_iterations: int = 10
    iterations: int = 30
    seed: int = 20260827

    def __post_init__(self) -> None:
        """要求足够的多轮和 steady-state 样本。"""

        if self.rounds < 5:
            raise ValueError("阶段 3 benchmark rounds 不能小于 5")
        if self.warmup_iterations <= 0 or self.iterations <= 0:
            raise ValueError("阶段 3 benchmark iterations 必须大于 0")


def _read_stage0_metric(report: dict[str, object], metric: str) -> float:
    """读取阶段 0 Inference 1 KiB、单并发的多轮中位指标。"""

    inference = report.get("inference")
    cells = inference.get("cells") if isinstance(inference, dict) else None
    if not isinstance(cells, list):
        raise ValueError("阶段 0 report 缺少 inference.cells")
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if (
            int(cell.get("target_response_size_bytes", -1)) == 1024
            and int(cell.get("concurrency", -1)) == 1
        ):
            summary = cell.get("summary")
            medians = (
                summary.get("median_of_rounds_ms")
                if isinstance(summary, dict)
                else None
            )
            if isinstance(medians, dict) and metric in medians:
                return float(medians[metric])
    raise ValueError(f"阶段 0 report 缺少 Inference 1 KiB c1 {metric}")


def _median_metric(rounds: list[dict[str, object]], metric: str) -> float:
    """返回各轮同名 latency 指标的中位数。"""

    return round(statistics.median(float(item[metric]) for item in rounds), 6)


def run(settings: BenchmarkSettings) -> dict[str, object]:
    """运行新 Inference adapter 并执行 P95/P99 回退门禁。"""

    stage0 = json.loads(Path(settings.stage0_report_path).read_text(encoding="utf-8"))
    output_path = Path(settings.output_path).resolve()
    work_root = output_path.parent / "work"
    result_value = _deterministic_text(1, seed=settings.seed)
    rounds = [
        _run_inference_round(
            buffers_root=work_root / f"round-{round_index}",
            result_value=result_value,
            concurrency=1,
            iterations=settings.iterations,
            warmup_iterations=settings.warmup_iterations,
        )
        for round_index in range(settings.rounds)
    ]
    current = {metric: _median_metric(rounds, metric) for metric in ("p95", "p99")}
    baseline = {metric: _read_stage0_metric(stage0, metric) for metric in current}
    allowed = {
        metric: round(max(value * 1.10, value + 0.5), 6)
        for metric, value in baseline.items()
    }
    gates = {metric: current[metric] <= allowed[metric] for metric in current}
    result = {
        "format_id": "amvision.local-message-channel-stage3-inference-benchmark.v1",
        "settings": asdict(settings),
        "transport": "local-message-inference-rpc.v1",
        "profile_id": INFERENCE_RPC_PROFILE_V1.profile_id,
        "response_size_class": "1-kib",
        "concurrency": 1,
        "summary": {
            "round_count": settings.rounds,
            "median_of_rounds_ms": current,
            "rounds": rounds,
        },
        "stage0_ms": baseline,
        "allowed_ms": allowed,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    encoded_bytes = encoded.encode("utf-8")
    output_path.write_bytes(encoded_bytes)
    result["report_sha256"] = hashlib.sha256(encoded_bytes).hexdigest()
    return result


def main() -> int:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / ".tmp/local-message-channel-stage3/inference-benchmark.json"),
    )
    parser.add_argument(
        "--stage0-report",
        default=str(ROOT / ".tmp/local-message-channel-stage0/baseline.json"),
    )
    arguments = parser.parse_args()
    result = run(
        BenchmarkSettings(
            output_path=arguments.output,
            stage0_report_path=arguments.stage0_report,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
