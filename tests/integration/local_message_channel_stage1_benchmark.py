"""LocalMessage 阶段 1 独立 engine 的同机回归基准。

脚本只使用 ``.tmp`` 隔离目录，不接 composition root，也不创建正式 Channel。
阶段 0 的 current Inference mailbox 是单次 request/response 的可比基线；Workflow
Trigger 还包含 PREPARE/WRITING 扩展，因此不拿它与通用 RPC engine 直接比较。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import statistics
import sys
from threading import Event, Thread
from time import monotonic_ns, perf_counter_ns, sleep
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.ipc.local_message_profiles import (  # noqa: E402
    INFERENCE_RPC_PROFILE_V1,
)
from backend.service.infrastructure.ipc.local_message.paths import (  # noqa: E402
    build_local_message_channel_paths,
)
from backend.service.infrastructure.ipc.local_message.rpc_mailbox import (  # noqa: E402
    MmapRpcMailboxClient,
    MmapRpcMailboxServer,
)
from tests.integration.local_message_channel_stage0_benchmark import (  # noqa: E402
    MIB,
    _compact_json,
    _response_payload,
)


DEFAULT_RESPONSE_SIZES = (1024, MIB, 8 * MIB, 32 * MIB)


@dataclass(frozen=True, slots=True)
class BenchmarkSettings:
    """阶段 1 基准的固定采样参数。"""

    output_path: str
    stage0_report_path: str
    rounds: int = 5
    warmup_iterations: int = 10
    inline_iterations: int = 30
    large_iterations: int = 3
    seed: int = 20260827

    def __post_init__(self) -> None:
        """拒绝不足以形成多轮中位数的配置。"""

        if self.rounds < 5:
            raise ValueError("阶段 1 benchmark rounds 不能小于 5")
        if min(
            self.warmup_iterations,
            self.inline_iterations,
            self.large_iterations,
        ) <= 0:
            raise ValueError("阶段 1 benchmark iterations 必须大于 0")


def _percentile(values: list[float], percentile: float) -> float:
    """使用线性插值计算 percentile。"""

    if not values:
        raise ValueError("percentile 样本不能为空")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summary(values: list[float]) -> dict[str, float | int]:
    """返回一轮 latency 摘要。"""

    return {
        "sample_count": len(values),
        "mean": round(statistics.fmean(values), 6),
        "p50": round(_percentile(values, 0.50), 6),
        "p95": round(_percentile(values, 0.95), 6),
        "p99": round(_percentile(values, 0.99), 6),
        "max": round(max(values), 6),
    }


def _median_rounds(rounds: list[dict[str, float | int]]) -> dict[str, float]:
    """按阶段 0 相同规则返回各轮指标中位数。"""

    return {
        metric: round(
            statistics.median(float(round_row[metric]) for round_row in rounds),
            6,
        )
        for metric in ("mean", "p50", "p95", "p99", "max")
    }


def _run_rpc_round(
    *,
    root: Path,
    response: bytes,
    warmup_iterations: int,
    iterations: int,
) -> dict[str, object]:
    """使用冻结 Inference profile 完成一轮单并发 transport 往返。"""

    paths = build_local_message_channel_paths(
        buffers_root=root,
        channel_name="stage1-inference",
        channel_kind="rpc",
    )
    server = MmapRpcMailboxServer(paths=paths, profile=INFERENCE_RPC_PROFILE_V1)
    client = MmapRpcMailboxClient(paths=paths, profile=INFERENCE_RPC_PROFILE_V1)
    expected = warmup_iterations + iterations
    completed = 0
    failures: list[str] = []
    stop = Event()

    def serve() -> None:
        nonlocal completed
        try:
            while completed < expected and not stop.is_set():
                request = server.receive(deadline_ns=monotonic_ns() + 100_000_000)
                if request is None:
                    continue
                server.publish_response(request, wire_bytes=response)
                completed += 1
                server.sweep()
        except BaseException as error:  # noqa: BLE001 - 转交主线程
            failures.append(f"{error.__class__.__name__}: {error}")

    worker = Thread(target=serve, name="stage1-rpc-owner")
    worker.start()
    latencies: list[float] = []
    try:
        for index in range(expected):
            started_ns = perf_counter_ns()
            handle = client.call(
                request_id=uuid4(),
                wire_bytes=b'{"schema_id":"stage1.request.v1","payload":{}}',
                deadline_ns=monotonic_ns() + 60_000_000_000,
            )
            if handle.wire_bytes != response:
                raise AssertionError("阶段 1 RPC response bytes 不一致")
            handle.close()
            if index >= warmup_iterations:
                latencies.append((perf_counter_ns() - started_ns) / 1_000_000)
        deadline_ns = monotonic_ns() + 5_000_000_000
        while monotonic_ns() < deadline_ns:
            server.sweep()
            health = server.health()
            if (
                health.free_descriptors == INFERENCE_RPC_PROFILE_V1.descriptor_count
                and health.free_pages
                == INFERENCE_RPC_PROFILE_V1.overflow_page_count
            ):
                break
            sleep(INFERENCE_RPC_PROFILE_V1.poll_interval_seconds)
        else:
            raise AssertionError("阶段 1 RPC 资源未在 deadline 内恢复")
    finally:
        stop.set()
        worker.join(timeout=5)
        client.close(deadline_ns=monotonic_ns() + 1_000_000_000)
        server.close(deadline_ns=monotonic_ns() + 1_000_000_000)
    if worker.is_alive() or failures:
        raise AssertionError(f"阶段 1 RPC owner 失败: {failures}")
    return {
        **_summary(latencies),
        "response_size_bytes": len(response),
        "resource_conserved": True,
    }


def _stage0_inference_p99(
    report: dict[str, object], *, response_size: int
) -> float:
    """读取同 response size、concurrency=1 的阶段 0 current Inference P99。"""

    inference = report.get("inference")
    if not isinstance(inference, dict):
        raise ValueError("阶段 0 report 缺少 inference")
    cells = inference.get("cells")
    if not isinstance(cells, list):
        raise ValueError("阶段 0 report inference.cells 不合法")
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if (
            int(cell.get("target_response_size_bytes", -1)) == response_size
            and int(cell.get("concurrency", -1)) == 1
        ):
            summary = cell.get("summary")
            if isinstance(summary, dict):
                medians = summary.get("median_of_rounds_ms")
                if isinstance(medians, dict):
                    return float(medians["p99"])
    raise ValueError(f"阶段 0 report 缺少 response_size={response_size} 的 c1 cell")


def run(settings: BenchmarkSettings) -> dict[str, object]:
    """执行 5 轮基准并按阶段 0 性能门禁裁决。"""

    stage0 = json.loads(Path(settings.stage0_report_path).read_text(encoding="utf-8"))
    output = Path(settings.output_path).resolve()
    work_root = output.parent / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    cells: list[dict[str, object]] = []
    for response_size in DEFAULT_RESPONSE_SIZES:
        response = _compact_json(
            _response_payload(response_size, seed=settings.seed + response_size)
        )
        iterations = (
            settings.inline_iterations
            if response_size <= 64 * 1024
            else settings.large_iterations
        )
        round_rows = [
            _run_rpc_round(
                root=work_root,
                response=response,
                warmup_iterations=settings.warmup_iterations,
                iterations=iterations,
            )
            for _ in range(settings.rounds)
        ]
        medians = _median_rounds(round_rows)
        baseline_p99 = _stage0_inference_p99(stage0, response_size=len(response))
        allowed_p99 = max(baseline_p99 * 1.10, baseline_p99 + 0.5)
        cells.append(
            {
                "response_size_bytes": len(response),
                "concurrency": 1,
                "summary": {
                    "round_count": settings.rounds,
                    "median_of_rounds_ms": medians,
                    "rounds": round_rows,
                },
                "stage0_current_inference_p99_ms": baseline_p99,
                "allowed_p99_ms": round(allowed_p99, 6),
                "p99_gate_passed": medians["p99"] <= allowed_p99,
            }
        )
    result = {
        "format_id": "amvision.local-message-channel-stage1-benchmark.v1",
        "settings": asdict(settings),
        "transport": "local-message-rpc.v1-unconnected",
        "profile_id": INFERENCE_RPC_PROFILE_V1.profile_id,
        "cells": cells,
        "all_gates_passed": all(bool(cell["p99_gate_passed"]) for cell in cells),
    }
    if not result["all_gates_passed"]:
        raise AssertionError("阶段 1 RPC P99 超过阶段 0 current Inference 门禁")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(output)
    return result


def main() -> int:
    """解析 CLI 并执行隔离基准。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=".tmp/local-message-channel-stage1/benchmark.json",
    )
    parser.add_argument(
        "--stage0-report",
        default=".tmp/local-message-channel-stage0/baseline.json",
    )
    args = parser.parse_args()
    result = run(
        BenchmarkSettings(
            output_path=args.output,
            stage0_report_path=args.stage0_report,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
