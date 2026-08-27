"""Workflow Trigger mailbox 阶段 1 的四进程并发压力门禁。"""

from __future__ import annotations

import argparse
import base64
import json
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.ipc.mmap_primitives import MmapGuardBusyError
from backend.service.infrastructure.ipc.workflow_trigger_rpc import (
    WorkflowTriggerMailboxClient,
    WorkflowTriggerMailboxServer,
)


_LARGE_RESPONSE_INTERVAL = 17
_LARGE_RESPONSE_BODY_SIZE = 600 * 1024


def _client_worker(
    *,
    buffers_root: str,
    worker_index: int,
    iterations: int,
    result_queue: multiprocessing.Queue,
) -> None:
    """在独立进程内完成 claim 到 ACK 的连续调用。"""

    try:
        with WorkflowTriggerMailboxClient(buffers_root=buffers_root) as client:
            for sequence in range(iterations):
                request_payload = json.dumps(
                    {"worker_index": worker_index, "sequence": sequence},
                    separators=(",", ":"),
                ).encode("utf-8")
                identity = _claim_until_available(
                    client=client,
                    prepare_payload=request_payload,
                )
                allocation = _wait_for_allocation(
                    client=client,
                    identity=identity,
                )
                _publish_request_until_available(
                    client=client,
                    identity=allocation.identity,
                    payload=request_payload,
                )
                response = _wait_for_response(
                    client=client,
                    identity=allocation.identity,
                )
                response_value = json.loads(response.payload)
                if (
                    response_value.get("worker_index") != worker_index
                    or response_value.get("sequence") != sequence
                ):
                    raise AssertionError("response identity payload 串包")
                expected_blob_size = (
                    len(base64.b64encode(b"X" * _LARGE_RESPONSE_BODY_SIZE))
                    if sequence % _LARGE_RESPONSE_INTERVAL == 0
                    else 0
                )
                if len(response_value.get("blob", "")) != expected_blob_size:
                    raise AssertionError("response blob 大小不匹配")
                _acknowledge_until_available(
                    client=client,
                    identity=allocation.identity,
                )
        result_queue.put((worker_index, iterations, ""))
    except BaseException as error:  # noqa: BLE001 - 子进程必须把完整失败传回父进程
        result_queue.put((worker_index, 0, repr(error)))


def _claim_until_available(
    *,
    client: WorkflowTriggerMailboxClient,
    prepare_payload: bytes,
):
    """在本地测试 deadline 内等待一个空 descriptor。"""

    deadline = monotonic() + 15.0
    while True:
        try:
            return client.claim(
                timeout_ms=10_000,
                route_generation=1,
                prepare_payload=prepare_payload,
            )
        except InvalidRequestError:
            if monotonic() >= deadline:
                raise
            sleep(0.0005)


def _wait_for_allocation(*, client: WorkflowTriggerMailboxClient, identity):
    """等待 server 发布 WRITING allocation。"""

    deadline = monotonic() + 15.0
    while monotonic() < deadline:
        try:
            allocation = client.read_writing_allocation(identity=identity)
        except MmapGuardBusyError:
            sleep(0.0005)
            continue
        if allocation is not None:
            return allocation
        sleep(0.0005)
    raise TimeoutError("等待 Workflow Trigger allocation 超时")


def _wait_for_response(*, client: WorkflowTriggerMailboxClient, identity):
    """等待并校验 server RESPONSE。"""

    deadline = monotonic() + 15.0
    while monotonic() < deadline:
        try:
            response = client.read_response(identity=identity)
        except MmapGuardBusyError:
            sleep(0.0005)
            continue
        if response is not None:
            return response
        sleep(0.0005)
    raise TimeoutError("等待 Workflow Trigger response 超时")


def _publish_request_until_available(
    *,
    client: WorkflowTriggerMailboxClient,
    identity,
    payload: bytes,
) -> None:
    """只在 guard 忙时重试尚未发布的 REQUEST。"""

    deadline = monotonic() + 15.0
    while True:
        try:
            client.publish_request(identity=identity, payload=payload)
            return
        except MmapGuardBusyError:
            if monotonic() >= deadline:
                raise
            sleep(0.0005)


def _acknowledge_until_available(
    *,
    client: WorkflowTriggerMailboxClient,
    identity,
) -> None:
    """只在 guard 忙时重试 ACK publication。"""

    deadline = monotonic() + 15.0
    while True:
        try:
            client.acknowledge(identity=identity)
            return
        except MmapGuardBusyError:
            if monotonic() >= deadline:
                raise
            sleep(0.0005)


def run_stress(*, worker_count: int, iterations_per_worker: int) -> None:
    """运行单 server、四 client 进程的固定次数压力验证。"""

    expected_count = worker_count * iterations_per_worker
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    # 只生成一次不可压缩 body，确保压力确实进入 overflow page path。
    large_body = os.urandom(_LARGE_RESPONSE_BODY_SIZE)
    temp_root = Path(".tmp")
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="workflow-trigger-mailbox-stage1-",
        dir=temp_root,
    ) as buffers_root:
        with WorkflowTriggerMailboxServer(buffers_root=buffers_root) as server:
            processes = tuple(
                context.Process(
                    target=_client_worker,
                    kwargs={
                        "buffers_root": buffers_root,
                        "worker_index": worker_index,
                        "iterations": iterations_per_worker,
                        "result_queue": result_queue,
                    },
                    name=f"workflow-trigger-mailbox-client-{worker_index}",
                )
                for worker_index in range(worker_count)
            )
            started_at = monotonic()
            for process in processes:
                process.start()
            completed = 0
            try:
                while completed < expected_count:
                    made_progress = False
                    while True:
                        prepare = server.poll_prepare()
                        if prepare is None:
                            break
                        server.publish_writing(
                            identity=prepare.identity,
                            allocation_payload=b"{}",
                        )
                        made_progress = True
                    while True:
                        request = server.poll_request()
                        if request is None:
                            break
                        request_value = json.loads(request.payload)
                        worker_index = int(request_value["worker_index"])
                        sequence = int(request_value["sequence"])
                        response_value = {
                            "worker_index": worker_index,
                            "sequence": sequence,
                            "blob": "",
                        }
                        if sequence % _LARGE_RESPONSE_INTERVAL == 0:
                            response_value["blob"] = base64.b64encode(
                                large_body
                            ).decode("ascii")
                        server.publish_response(
                            identity=request.identity,
                            payload=json.dumps(
                                response_value,
                                separators=(",", ":"),
                            ).encode("utf-8"),
                        )
                        completed += 1
                        made_progress = True
                    server.sweep()
                    failed = tuple(
                        process
                        for process in processes
                        if process.exitcode not in {None, 0}
                    )
                    if failed:
                        raise RuntimeError(
                            "client 子进程异常退出："
                            + ", ".join(
                                f"{process.name}={process.exitcode}"
                                for process in failed
                            )
                        )
                    if not made_progress:
                        sleep(0.0002)
                for process in processes:
                    process.join(timeout=30.0)
                results = tuple(result_queue.get(timeout=5.0) for _ in processes)
                errors = tuple(error for _, _, error in results if error)
                if errors:
                    raise AssertionError("; ".join(errors))
                if sum(count for _, count, _ in results) != expected_count:
                    raise AssertionError("client 完成请求数不匹配")
                deadline = monotonic() + 5.0
                while monotonic() < deadline:
                    status = server.build_status()
                    if status["descriptor_state_counts"][0] == 128:
                        break
                    server.sweep()
                    sleep(0.0005)
                status = server.build_status()
                if status["descriptor_state_counts"][0] != 128:
                    raise AssertionError(f"descriptor 未全部回收：{status}")
                if status["used_page_count"] != 0:
                    raise AssertionError(f"overflow page 泄漏：{status}")
                elapsed = monotonic() - started_at
                print(
                    f"PASS requests={expected_count} workers={worker_count} "
                    f"elapsed_seconds={elapsed:.3f}"
                )
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=5.0)
                result_queue.close()


def main() -> None:
    """解析参数并执行压力门禁。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--iterations-per-worker", type=int, default=500)
    args = parser.parse_args()
    if args.workers <= 0 or args.iterations_per_worker <= 0:
        raise ValueError("workers 和 iterations-per-worker 必须大于 0")
    run_stress(
        worker_count=args.workers,
        iterations_per_worker=args.iterations_per_worker,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
