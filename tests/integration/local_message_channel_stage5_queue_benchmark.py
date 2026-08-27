"""阶段 5：以相同 MailboxPort/envelope 比较 Queue 与候选 Mailbox。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import random
import statistics
import sys
from time import monotonic_ns, perf_counter_ns, sleep
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.ipc.local_message_profiles import (  # noqa: E402
    INFERENCE_MAILBOX_PROFILE_V1,
)
from backend.service.application.message_channels.codec import (  # noqa: E402
    WireEnvelope,
    encode_wire_envelope,
)
from backend.service.infrastructure.ipc.local_message.paths import (  # noqa: E402
    build_local_message_channel_paths,
)
from backend.service.infrastructure.ipc.local_message.mailbox import (  # noqa: E402
    MmapMailboxClient,
    MmapMailboxServer,
)
from backend.service.infrastructure.ipc.multiprocessing_queue_channel import (  # noqa: E402
    MultiprocessingQueueMailboxClient,
    MultiprocessingQueueMailboxServer,
)
from backend.service.infrastructure.ipc.mmap_primitives import (  # noqa: E402
    new_nonzero_u64_token,
)
from tests.integration.local_message_channel_stage0_benchmark import (  # noqa: E402
    _resource_delta,
    _snapshot_process_resources,
    summarize_rounds,
    summarize_samples,
)


KIB = 1024
DEFAULT_PAYLOAD_SIZES = (1024, 6 * KIB, 64 * KIB)


@dataclass(frozen=True, slots=True)
class BenchmarkSettings:
    """冻结阶段 5 的同拓扑采样参数。"""

    output_path: str
    rounds: int = 5
    warmup_iterations: int = 10
    inline_iterations: int = 50
    payload_sizes: tuple[int, ...] = DEFAULT_PAYLOAD_SIZES
    seed: int = 20260827

    def __post_init__(self) -> None:
        """拒绝不能形成正式多轮中位数的设置。"""

        if self.rounds < 5:
            raise ValueError("阶段 5 benchmark rounds 不能小于 5")
        if min(
            self.warmup_iterations,
            self.inline_iterations,
        ) <= 0:
            raise ValueError("阶段 5 benchmark iterations 必须大于 0")
        if not self.payload_sizes or min(self.payload_sizes) <= 0:
            raise ValueError("阶段 5 payload_sizes 必须为正数")
        if max(self.payload_sizes) > INFERENCE_MAILBOX_PROFILE_V1.max_request_bytes:
            raise ValueError("阶段 5 request 不能超过冻结 Mailbox request 上限")


def _payload(target_size: int, *, seed: int) -> bytes:
    """生成不可有效压缩且使用统一 codec 的 request bytes。"""

    generator = random.Random(seed)
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    # envelope 自身有固定开销，迭代一次即可取得精确目标附近的正文。
    body = "".join(generator.choice(alphabet) for _ in range(target_size))
    wire = encode_wire_envelope(
        WireEnvelope(
            schema_id="amvision.stage5.mailbox-benchmark.v1",
            payload={"value": body},
        )
    )
    if len(wire) <= target_size:
        return wire
    trim = len(wire) - target_size
    return encode_wire_envelope(
        WireEnvelope(
            schema_id="amvision.stage5.mailbox-benchmark.v1",
            payload={"value": body[:-trim]},
        )
    )


def _queue_server_process(
    *,
    request_queue: object,
    response_queue: object,
    owner_epoch: int,
    expected: int,
    ready: object,
    result: object,
) -> None:
    """使用 Queue MailboxServerPort 完成固定次数 echo。"""

    try:
        before = _snapshot_process_resources([os.getpid()])
        server = MultiprocessingQueueMailboxServer(
            request_queue=request_queue,  # type: ignore[arg-type]
            response_queue=response_queue,  # type: ignore[arg-type]
            owner_epoch=owner_epoch,
        )
        ready.set()  # type: ignore[attr-defined]
        for _ in range(expected):
            request = server.receive(deadline_ns=monotonic_ns() + 60_000_000_000)
            if request is None:
                raise TimeoutError("Queue MailboxServer 未收到预期 request")
            server.publish_response(request, wire_bytes=request.wire_bytes)
        server.close(deadline_ns=monotonic_ns() + 1_000_000_000)
        result.put(  # type: ignore[attr-defined]
            {
                "error": "",
                "resources": _resource_delta(
                    before,
                    _snapshot_process_resources([os.getpid()]),
                ),
            }
        )
    except BaseException as error:  # noqa: BLE001
        result.put(  # type: ignore[attr-defined]
            {"error": f"{type(error).__name__}: {error}", "resources": None}
        )


def _mmap_server_process(
    *,
    buffers_root: str,
    expected: int,
    ready: object,
    result: object,
) -> None:
    """使用候选 Mailbox MailboxServerPort 完成固定次数 echo。"""

    try:
        before = _snapshot_process_resources([os.getpid()])
        paths = build_local_message_channel_paths(
            buffers_root=buffers_root,
            channel_name="stage5-queue-candidate",
            channel_kind="mailbox",
        )
        server = MmapMailboxServer(
            paths=paths,
            profile=INFERENCE_MAILBOX_PROFILE_V1,
        )
        ready.set()  # type: ignore[attr-defined]
        for _ in range(expected):
            request = server.receive(deadline_ns=monotonic_ns() + 60_000_000_000)
            if request is None:
                raise TimeoutError("Mmap MailboxServer 未收到预期 request")
            server.publish_response(request, wire_bytes=request.wire_bytes)
            server.sweep()
        cleanup_deadline_ns = monotonic_ns() + 5_000_000_000
        while monotonic_ns() < cleanup_deadline_ns:
            server.sweep()
            health = server.health()
            if (
                health.free_descriptors
                == INFERENCE_MAILBOX_PROFILE_V1.descriptor_count
                and health.free_pages
                == INFERENCE_MAILBOX_PROFILE_V1.overflow_page_count
            ):
                break
            sleep(INFERENCE_MAILBOX_PROFILE_V1.poll_interval_seconds)
        server.close(deadline_ns=monotonic_ns() + 5_000_000_000)
        result.put(  # type: ignore[attr-defined]
            {
                "error": "",
                "resources": _resource_delta(
                    before,
                    _snapshot_process_resources([os.getpid()]),
                ),
            }
        )
    except BaseException as error:  # noqa: BLE001
        result.put(  # type: ignore[attr-defined]
            {"error": f"{type(error).__name__}: {error}", "resources": None}
        )


def _run_round(
    *,
    transport: str,
    buffers_root: Path,
    wire_bytes: bytes,
    warmup_iterations: int,
    iterations: int,
) -> dict[str, object]:
    """用同一 client/server Port 语义采集单并发跨进程往返。"""

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    result = context.Queue()
    request_queue = context.Queue() if transport == "queue" else None
    response_queue = context.Queue() if transport == "queue" else None
    owner_epoch = new_nonzero_u64_token()
    expected = warmup_iterations + iterations
    process = context.Process(
        target=(
            _queue_server_process if transport == "queue" else _mmap_server_process
        ),
        kwargs=(
            {
                "request_queue": request_queue,
                "response_queue": response_queue,
                "owner_epoch": owner_epoch,
                "expected": expected,
                "ready": ready,
                "result": result,
            }
            if transport == "queue"
            else {
                "buffers_root": str(buffers_root),
                "expected": expected,
                "ready": ready,
                "result": result,
            }
        ),
        name=f"stage5-{transport}-mailbox-server",
    )
    process.start()
    if not ready.wait(timeout=60.0):
        process.terminate()
        process.join(timeout=5.0)
        raise TimeoutError(f"阶段 5 {transport} server ready 超时")
    before = _snapshot_process_resources([os.getpid()])
    if transport == "queue":
        client = MultiprocessingQueueMailboxClient(
            request_queue=request_queue,  # type: ignore[arg-type]
            response_queue=response_queue,  # type: ignore[arg-type]
            owner_epoch=owner_epoch,
        )
    else:
        client = MmapMailboxClient(
            paths=build_local_message_channel_paths(
                buffers_root=buffers_root,
                channel_name="stage5-queue-candidate",
                channel_kind="mailbox",
            ),
            profile=INFERENCE_MAILBOX_PROFILE_V1,
        )
    latencies: list[float] = []
    try:
        for sequence in range(expected):
            started_ns = perf_counter_ns()
            handle = client.call(
                request_id=uuid4(),
                wire_bytes=wire_bytes,
                deadline_ns=monotonic_ns() + 60_000_000_000,
            )
            if handle.wire_bytes != wire_bytes:
                raise AssertionError("阶段 5 Mailbox response bytes 不一致")
            handle.close()
            if sequence >= warmup_iterations:
                latencies.append((perf_counter_ns() - started_ns) / 1_000_000)
        server_report = result.get(timeout=60.0)
        if not isinstance(server_report, dict):
            raise AssertionError("阶段 5 server report 格式不合法")
        if server_report.get("error"):
            raise AssertionError(str(server_report["error"]))
        process.join(timeout=60.0)
        if process.exitcode != 0:
            raise AssertionError(f"阶段 5 {transport} server exit={process.exitcode}")
        parent_resources = _resource_delta(
            before,
            _snapshot_process_resources([os.getpid()]),
        )
        server_resources = server_report.get("resources")
        if not isinstance(server_resources, dict):
            raise AssertionError("阶段 5 server resources 缺失")
        return {
            **summarize_samples(latencies),
            "resources": _sum_resources(parent_resources, server_resources),
        }
    finally:
        client.close(deadline_ns=monotonic_ns() + 1_000_000_000)
        if process.is_alive():
            process.terminate()
        process.join(timeout=5.0)
        if request_queue is not None:
            request_queue.close()
            request_queue.join_thread()
        if response_queue is not None:
            response_queue.close()
            response_queue.join_thread()
        result.close()


def _sum_resources(
    parent: dict[str, int | float | None],
    server: dict[str, object],
) -> dict[str, int | float | None]:
    """合并 client 父进程和 server 子进程的可比资源。"""

    values: dict[str, int | float | None] = {}
    for metric in (
        "cpu_seconds",
        "working_set_bytes",
        "peak_working_set_bytes",
        "page_faults",
        "context_switches",
        "thread_count",
        "handle_count",
        "handle_delta",
    ):
        parent_value = parent.get(metric)
        server_value = server.get(metric)
        if parent_value is None or server_value is None:
            values[metric] = None
        else:
            values[metric] = float(parent_value) + float(server_value)
    return values


def _resource_median(
    rounds: list[dict[str, object]],
    metric: str,
) -> float:
    """返回五轮 server 资源指标中位数。"""

    return round(
        statistics.median(
            float(item["resources"][metric])  # type: ignore[index]
            for item in rounds
        ),
        6,
    )


def run(settings: BenchmarkSettings) -> dict[str, object]:
    """采集两种 transport 并按阶段 5 迁移阈值裁决。"""

    output = Path(settings.output_path).resolve()
    cells: list[dict[str, object]] = []
    for payload_size in settings.payload_sizes:
        wire_bytes = _payload(
            payload_size,
            seed=settings.seed + payload_size,
        )
        iterations = settings.inline_iterations
        transport_rows: dict[str, dict[str, object]] = {}
        for transport in ("queue", "mmap"):
            rounds = [
                _run_round(
                    transport=transport,
                    buffers_root=(
                        output.parent
                        / "work"
                        / f"{payload_size}-{transport}-{round_index}"
                    ),
                    wire_bytes=wire_bytes,
                    warmup_iterations=settings.warmup_iterations,
                    iterations=iterations,
                )
                for round_index in range(settings.rounds)
            ]
            transport_rows[transport] = {
                "summary": summarize_rounds(rounds),
                "resource_medians": {
                    metric: _resource_median(rounds, metric)
                    for metric in (
                        "cpu_seconds",
                        "working_set_bytes",
                        "page_faults",
                        "thread_count",
                        "handle_count",
                    )
                },
            }
        queue_medians = transport_rows["queue"]["summary"][  # type: ignore[index]
            "median_of_rounds_ms"
        ]
        mmap_medians = transport_rows["mmap"]["summary"][  # type: ignore[index]
            "median_of_rounds_ms"
        ]
        p95_improvement = float(queue_medians["p95"]) - float(  # type: ignore[index]
            mmap_medians["p95"]  # type: ignore[index]
        )
        p99_improvement = float(queue_medians["p99"]) - float(  # type: ignore[index]
            mmap_medians["p99"]  # type: ignore[index]
        )
        performance_gate = (
            p95_improvement >= float(queue_medians["p95"]) * 0.10  # type: ignore[index]
            and p99_improvement >= float(queue_medians["p99"]) * 0.10  # type: ignore[index]
            and max(p95_improvement, p99_improvement) >= 1.0
        )
        cells.append(
            {
                "payload_size_bytes": len(wire_bytes),
                "concurrency": 1,
                "transports": transport_rows,
                "mmap_improvement_ms": {
                    "p95": round(p95_improvement, 6),
                    "p99": round(p99_improvement, 6),
                },
                "performance_gate_passed": performance_gate,
            }
        )
    result = {
        "format_id": "amvision.local-message-channel-stage5-queue-benchmark.v1",
        "settings": asdict(settings),
        "cells": cells,
        "migration_decision": (
            "migrate" if all(cell["performance_gate_passed"] for cell in cells) else "retain-queue"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    output.write_text(encoded, encoding="utf-8")
    result["report_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return result


def main() -> int:
    """解析 CLI 并输出阶段 5 裁决。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=".tmp/local-message-channel-stage5/queue-benchmark.json",
    )
    arguments = parser.parse_args()
    result = run(BenchmarkSettings(output_path=arguments.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
