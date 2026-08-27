"""对 legacy/current Workflow Trigger 执行相同稳态进程拓扑比较。"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
from pathlib import Path
from queue import Empty
import random
import statistics
import sys
import time
from typing import Callable

from pydantic_core import to_json


ROOT = Path.cwd().resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (  # type: ignore[import-not-found]  # noqa: E402
        WorkflowTriggerMailboxClient,
        WorkflowTriggerMailboxServer,
    )
except ModuleNotFoundError:
    from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (  # type: ignore[assignment,no-redef]  # noqa: E402
        WorkflowTriggerMailboxClient,
        WorkflowTriggerMailboxServer,
    )


MIB = 1024 * 1024


def _compact_json(payload: object) -> bytes:
    """使用相同 compact JSON 编码。"""

    return bytes(to_json(payload))


def _response_payload(target_size: int, *, seed: int) -> bytes:
    """生成和阶段 0 相同的不可有效压缩响应。"""

    shell = {"ok": True, "result": {"value": ""}}
    body_size = max(0, target_size - len(_compact_json(shell)))
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    generator = random.Random(seed)
    value = "".join(generator.choice(alphabet) for _ in range(body_size))
    return _compact_json({"ok": True, "result": {"value": value}})


def _percentile(ordered: list[float], quantile: float) -> float:
    """按线性插值计算分位数。"""

    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summarize(values: list[float]) -> dict[str, float]:
    """汇总单轮稳态延迟。"""

    ordered = sorted(values)
    return {
        "p50": round(_percentile(ordered, 0.50), 6),
        "p95": round(_percentile(ordered, 0.95), 6),
        "p99": round(_percentile(ordered, 0.99), 6),
        "max": round(ordered[-1], 6),
    }


def _wait_until(
    operation: Callable[[], object | None],
    *,
    timeout_seconds: float = 60.0,
) -> object:
    """有界等待非阻塞 mailbox 操作。"""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = operation()
        except Exception as error:
            if type(error).__name__ != "MmapGuardBusyError":
                raise
            result = None
        if result is not None:
            return result
        time.sleep(0.0005)
    raise TimeoutError("Trigger A/B client 等待超时")


def _client_process(
    *,
    buffers_root: str,
    worker_index: int,
    iterations: int,
    warmup_iterations: int,
    expected_response_size: int,
    ready_queue: object,
    start_event: object,
    result_queue: object,
) -> None:
    """完成已同步启动的 PREPARE 到 ACK 全链路。"""

    try:
        latencies: list[float] = []
        with WorkflowTriggerMailboxClient(buffers_root=buffers_root) as client:
            ready_queue.put(worker_index)  # type: ignore[attr-defined]
            if not start_event.wait(timeout=60.0):  # type: ignore[attr-defined]
                raise TimeoutError("Trigger A/B start barrier 超时")
            for sequence in range(warmup_iterations + iterations):
                request = _compact_json(
                    {
                        "format_id": "amvision.workflow-trigger-request.v1",
                        "trigger_source_id": "ab",
                        "event_id": f"{worker_index}-{sequence}",
                        "payload": {"sequence": sequence},
                        "metadata": {},
                    }
                )
                started_ns = time.perf_counter_ns()
                identity = client.claim(
                    timeout_ms=60_000,
                    route_generation=1,
                    prepare_payload=request,
                )
                allocation = _wait_until(
                    lambda: client.read_writing_allocation(identity=identity)
                )
                authoritative_identity = allocation.identity  # type: ignore[attr-defined]
                client.publish_request(
                    identity=authoritative_identity,
                    payload=request,
                )
                response = _wait_until(
                    lambda: client.read_response(identity=authoritative_identity)
                )
                payload_size = getattr(response, "payload_size", None)
                if payload_size is None:
                    payload_size = len(response.payload)  # type: ignore[attr-defined]
                if int(payload_size) != expected_response_size:
                    raise AssertionError("Trigger A/B response 大小不一致")
                client.acknowledge(identity=authoritative_identity)
                if sequence >= warmup_iterations:
                    latencies.append(
                        (time.perf_counter_ns() - started_ns) / 1_000_000
                    )
        result_queue.put({"latencies": latencies, "error": None})  # type: ignore[attr-defined]
    except BaseException as error:  # noqa: BLE001
        result_queue.put(  # type: ignore[attr-defined]
            {"latencies": [], "error": f"{type(error).__name__}: {error}"}
        )


def _run_round(
    *,
    buffers_root: Path,
    response_payload: bytes,
    concurrency: int,
    per_worker_iterations: int,
    warmup_per_worker: int,
) -> dict[str, float]:
    """等待全部 client ready 后采集一轮稳态结果。"""

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    result_queue = context.Queue()
    start_event = context.Event()
    workers = tuple(
        context.Process(
            target=_client_process,
            kwargs={
                "buffers_root": str(buffers_root),
                "worker_index": index,
                "iterations": per_worker_iterations,
                "warmup_iterations": warmup_per_worker,
                "expected_response_size": len(response_payload),
                "ready_queue": ready_queue,
                "start_event": start_event,
                "result_queue": result_queue,
            },
        )
        for index in range(concurrency)
    )
    with WorkflowTriggerMailboxServer(buffers_root=buffers_root) as server:
        for worker in workers:
            worker.start()
        for _ in workers:
            ready_queue.get(timeout=60.0)
        start_event.set()
        expected = concurrency * (warmup_per_worker + per_worker_iterations)
        completed = 0
        reports: list[dict[str, object]] = []
        deadline = time.monotonic() + 180.0
        try:
            while completed < expected:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Trigger A/B round deadline 已到期")
                progressed = False
                while (prepare := server.poll_prepare()) is not None:
                    server.publish_writing(
                        identity=prepare.identity,
                        allocation_payload=b"{}",
                    )
                    progressed = True
                while (request := server.poll_request()) is not None:
                    server.publish_response(
                        identity=request.identity,
                        payload=response_payload,
                    )
                    completed += 1
                    progressed = True
                server.sweep()
                while True:
                    try:
                        report = result_queue.get_nowait()
                    except Empty:
                        break
                    reports.append(report)
                    if report["error"]:
                        raise RuntimeError(str(report["error"]))
                if not progressed:
                    time.sleep(0.0002)
            while len(reports) < len(workers):
                reports.append(result_queue.get(timeout=60.0))
            errors = [str(item["error"]) for item in reports if item["error"]]
            if errors:
                raise RuntimeError("; ".join(errors))
            latencies = [
                float(value)
                for item in reports
                for value in item["latencies"]  # type: ignore[union-attr]
            ]
            return _summarize(latencies)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=5.0)
            ready_queue.close()
            result_queue.close()


def main() -> int:
    """运行指定矩阵并输出适合 legacy/current 对照的 JSON。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--response-size", type=int, action="append", required=True)
    parser.add_argument("--concurrency", type=int, action="append", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    arguments = parser.parse_args()
    cells: list[dict[str, object]] = []
    for response_size in arguments.response_size:
        response_payload = _response_payload(
            response_size,
            seed=20260827 + response_size,
        )
        for concurrency in arguments.concurrency:
            rounds = [
                _run_round(
                    buffers_root=(
                        Path(arguments.output).resolve().parent
                        / "work"
                        / f"{response_size}-{concurrency}-{round_index}"
                    ),
                    response_payload=response_payload,
                    concurrency=concurrency,
                    per_worker_iterations=(10 if response_size <= 64 * 1024 else 2),
                    warmup_per_worker=2,
                )
                for round_index in range(arguments.rounds)
            ]
            cells.append(
                {
                    "response_size_bytes": len(response_payload),
                    "concurrency": concurrency,
                    "median_of_rounds_ms": {
                        metric: round(
                            statistics.median(item[metric] for item in rounds),
                            6,
                        )
                        for metric in ("p50", "p95", "p99", "max")
                    },
                    "rounds": rounds,
                }
            )
    result = {
        "format_id": "amvision.local-message-trigger-ab-benchmark.v1",
        "implementation": arguments.implementation,
        "rounds": arguments.rounds,
        "warmup_per_worker": 2,
        "cells": cells,
    }
    output = Path(arguments.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
