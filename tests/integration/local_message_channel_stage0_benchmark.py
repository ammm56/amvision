"""LocalMessage Channel 阶段 0 可复现基线采集工具。

该工具只实例化当前已经投入使用的 Workflow Trigger、Inference、Training
Telemetry 和 ``multiprocessing.Queue`` 实现，并在 ``.tmp`` 隔离目录中采集结果。
它不会接入 composition root，不会修改正式配置，也不会创建候选业务 Channel。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mmap
import multiprocessing
import os
import platform
from queue import Empty
import random
import sqlite3
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

import psutil
from pydantic_core import from_json, to_json

# 允许从仓库根目录直接执行该测量脚本，同时保持 ``python -m`` 行为一致。
ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.ipc import (  # noqa: E402
    workflow_trigger_rpc_extension_v1 as trigger_contract,
)
from backend.contracts.ipc.local_message_profiles import (  # noqa: E402
    TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    WORKFLOW_TRIGGER_RPC_PROFILE_V1,
    EventRingChannelProfile,
)
from backend.service.application.message_channels.models import EventCursor  # noqa: E402
from backend.service.application.models.training.training_telemetry import (  # noqa: E402
    TrainingTelemetryBroker,
    TrainingTelemetryPoint,
)
from backend.service.application.models.training.training_telemetry_channel import (  # noqa: E402
    decode_training_telemetry_point,
    _serialize_transport_point,
)
from backend.service.application.events import InMemoryServiceEventBus  # noqa: E402
from backend.service.infrastructure.ipc.inference_rpc import (  # noqa: E402
    InferenceLocalMmapClient,
    InferenceLocalMmapServer,
)
from backend.service.infrastructure.ipc.mmap_primitives import (  # noqa: E402
    MmapGuardBusyError,
)
from backend.service.infrastructure.ipc.local_message.event_ring import (  # noqa: E402
    MmapEventRingReader,
)
from backend.service.infrastructure.ipc.local_message.common_layout import (  # noqa: E402
    rpc_layout,
)
from backend.service.infrastructure.ipc.local_message.paths import (  # noqa: E402
    LocalMessageChannelPaths,
)
from backend.service.infrastructure.ipc.training_telemetry import (  # noqa: E402
    TrainingTelemetryMmapPublisher,
    TrainingTelemetryMmapReceiver,
)
from backend.service.infrastructure.ipc.workflow_trigger_rpc import (  # noqa: E402
    WorkflowTriggerMailboxClient,
    WorkflowTriggerMailboxServer,
)

DEFAULT_OUTPUT: Final = (
    ROOT / ".tmp" / "local-message-channel-stage0" / "baseline.json"
)
REPORT_FORMAT_ID: Final = "amvision.local-message-channel-stage0-baseline.v1"
MIB: Final = 1024 * 1024
DEFAULT_RESPONSE_SIZES: Final = (1024, MIB, 8 * MIB, 16 * MIB, 32 * MIB)
DEFAULT_CONCURRENCY: Final = (1, 2, 8, 16)
PAGE_SIZE_CANDIDATES: Final = (64 * 1024, 128 * 1024, 256 * 1024, 512 * 1024)


@dataclass(frozen=True)
class BenchmarkSettings:
    """描述阶段 0 的固定测量矩阵。"""

    output_path: Path
    rounds: int = 5
    warmup_iterations: int = 10
    inline_iterations: int = 50
    large_iterations: int = 3
    telemetry_iterations: int = 40
    response_sizes: tuple[int, ...] = DEFAULT_RESPONSE_SIZES
    concurrency: tuple[int, ...] = DEFAULT_CONCURRENCY
    seed: int = 20260827

    def validate(self) -> None:
        """拒绝无法形成可比较结果的参数。"""

        if self.rounds < 5:
            raise ValueError("正式阶段 0 基线至少需要 5 轮")
        if self.warmup_iterations < 0:
            raise ValueError("warmup_iterations 不能小于 0")
        if min(self.inline_iterations, self.large_iterations) <= 0:
            raise ValueError("每轮 iterations 必须大于 0")
        if self.telemetry_iterations <= 0:
            raise ValueError("telemetry_iterations 必须大于 0")
        if not self.response_sizes or min(self.response_sizes) <= 0:
            raise ValueError("response_sizes 必须为正数")
        if not self.concurrency or min(self.concurrency) <= 0:
            raise ValueError("concurrency 必须为正数")
        if max(self.response_sizes) > 32 * MIB:
            raise ValueError("当前公开结构化响应上限为 32 MiB")


@dataclass(frozen=True)
class ProcessResourceSnapshot:
    """描述一组进程的可比较资源计数。"""

    cpu_seconds: float
    working_set_bytes: int
    peak_working_set_bytes: int
    page_faults: int
    context_switches: int
    thread_count: int
    handle_count: int | None


def _snapshot_process_resources(process_ids: Iterable[int]) -> ProcessResourceSnapshot:
    """汇总仍存活进程的资源快照。"""

    cpu_seconds = 0.0
    working_set_bytes = 0
    peak_working_set_bytes = 0
    page_faults = 0
    context_switches = 0
    thread_count = 0
    handle_count = 0
    handle_supported = True
    for process_id in tuple(dict.fromkeys(process_ids)):
        try:
            process = psutil.Process(process_id)
            cpu = process.cpu_times()
            memory = process.memory_info()
            switches = process.num_ctx_switches()
            cpu_seconds += float(cpu.user) + float(cpu.system)
            working_set_bytes += int(memory.rss)
            peak_working_set_bytes += int(
                getattr(memory, "peak_wset", memory.rss)
            )
            page_faults += int(getattr(memory, "num_page_faults", 0))
            context_switches += int(switches.voluntary) + int(switches.involuntary)
            thread_count += process.num_threads()
            if hasattr(process, "num_handles"):
                handle_count += int(process.num_handles())
            else:
                handle_supported = False
        except (psutil.Error, OSError):
            continue
    return ProcessResourceSnapshot(
        cpu_seconds=cpu_seconds,
        working_set_bytes=working_set_bytes,
        peak_working_set_bytes=peak_working_set_bytes,
        page_faults=page_faults,
        context_switches=context_switches,
        thread_count=thread_count,
        handle_count=handle_count if handle_supported else None,
    )


def _resource_delta(
    before: ProcessResourceSnapshot,
    after: ProcessResourceSnapshot,
) -> dict[str, int | float | None]:
    """生成累计指标差值和结束时 gauge。"""

    return {
        "cpu_seconds": round(max(0.0, after.cpu_seconds - before.cpu_seconds), 6),
        "working_set_bytes": after.working_set_bytes,
        "peak_working_set_bytes": after.peak_working_set_bytes,
        "page_faults": max(0, after.page_faults - before.page_faults),
        "context_switches": max(
            0,
            after.context_switches - before.context_switches,
        ),
        "thread_count": after.thread_count,
        "handle_count": after.handle_count,
        "handle_delta": (
            None
            if before.handle_count is None or after.handle_count is None
            else after.handle_count - before.handle_count
        ),
    }


def _percentile(ordered: list[float], quantile: float) -> float:
    """按线性插值计算分位数。"""

    if not ordered:
        raise ValueError("样本不能为空")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_samples(values: Iterable[float]) -> dict[str, float | int]:
    """返回稳定的样本数和延迟分布。"""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("样本不能为空")
    return {
        "sample_count": len(ordered),
        "min": round(ordered[0], 6),
        "mean": round(statistics.fmean(ordered), 6),
        "p50": round(_percentile(ordered, 0.50), 6),
        "p95": round(_percentile(ordered, 0.95), 6),
        "p99": round(_percentile(ordered, 0.99), 6),
        "max": round(ordered[-1], 6),
    }


def summarize_rounds(rounds: Iterable[dict[str, object]]) -> dict[str, object]:
    """使用各轮分位数的中位数形成正式比较值。"""

    rows = tuple(rounds)
    if len(rows) < 5:
        raise ValueError("正式汇总至少需要 5 轮")
    medians: dict[str, float] = {}
    for field in ("mean", "p50", "p95", "p99", "max"):
        medians[field] = round(
            statistics.median(float(row[field]) for row in rows),
            6,
        )
    return {
        "round_count": len(rows),
        "median_of_rounds_ms": medians,
        "rounds": list(rows),
    }


def _compact_json(payload: object) -> bytes:
    """使用阶段 0 冻结的 pydantic-core 紧凑 UTF-8 JSON 编码。"""

    return bytes(to_json(payload))


def _deterministic_text(size_bytes: int, *, seed: int) -> str:
    """生成不易被 zlib 压缩且可复现的 ASCII 正文。"""

    if size_bytes <= 0:
        return ""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    generator = random.Random(seed)
    return "".join(generator.choice(alphabet) for _ in range(size_bytes))


def _response_payload(target_size: int, *, seed: int) -> dict[str, object]:
    """生成接近目标序列化长度的结构化响应。"""

    shell = {"ok": True, "result": {"value": ""}}
    shell_size = len(_compact_json(shell))
    body_size = max(0, target_size - shell_size)
    payload = {
        "ok": True,
        "result": {"value": _deterministic_text(body_size, seed=seed)},
    }
    encoded_size = len(_compact_json(payload))
    if encoded_size > 32 * MIB:
        trim = encoded_size - 32 * MIB
        value = str(payload["result"]["value"])  # type: ignore[index]
        payload["result"]["value"] = value[:-trim]  # type: ignore[index]
    return payload


def build_payload_inventory() -> dict[str, object]:
    """使用当前公开 DTO 形成可审计的结构化消息样本。"""

    trigger_prepare = {
        "format_id": "amvision.workflow-trigger-prepare.v1",
        "trigger_source_id": "trigger-source-stage0",
        "event_id": "event-stage0",
        "image": {
            "content_length": 6_220_800,
            "media_type": "image/raw",
            "event_payload_key": "request_image_ref",
            "shape": [1080, 1920, 3],
            "dtype": "uint8",
            "layout": "HWC",
            "pixel_format": "BGR24",
        },
    }
    trigger_request = {
        "format_id": "amvision.workflow-trigger-request.v1",
        "trigger_source_id": "trigger-source-stage0",
        "event_id": "event-stage0",
        "payload": {
            "line_id": "line-01",
            "product_id": "product-000001",
            "request_image_ref": {
                "transport_kind": "buffer",
                "lease_id": "lease-stage0",
                "buffer_id": "local-buffer-main:1",
                "offset": 1_048_576,
                "content_length": 6_220_800,
            },
        },
        "metadata": {"source": "plc-gateway", "sequence": 1},
        "trace_id": "trace-stage0",
        "idempotency_key": "event-stage0",
    }
    inference_requests = {
        task_type: {
            "action": "infer",
            "task_type": task_type,
            "deployment_instance_id": "deployment-instance-stage0",
            "request": {
                "input_image_payload": {
                    "transport_kind": "buffer",
                    "lease_id": "lease-stage0",
                    "buffer_id": "local-buffer-main:1",
                    "offset": 1_048_576,
                    "content_length": 6_220_800,
                },
                "score_threshold": 0.25,
                "save_result_image": False,
            },
        }
        for task_type in ("classification", "detection", "segmentation", "pose", "obb")
    }
    telemetry_point = TrainingTelemetryPoint(
        task_id="training-task-stage0",
        attempt_no=1,
        task_type="segmentation",
        model_type="yolo11",
        stage="training",
        granularity="batch",
        epoch=12,
        max_epochs=100,
        step=25,
        steps_per_epoch=200,
        global_step=2_225,
        total_steps=20_000,
        progress_percent=11.125,
        learning_rate=0.001,
        metrics={
            "loss": 1.25,
            "box_loss": 0.5,
            "seg_loss": 0.4,
            "cls_loss": 0.35,
        },
        input_size=(1024, 1024),
        runtime={
            "cpu_percent": 42.5,
            "memory_rss_bytes": 1_234_567_890,
            "gpu_memory_used_bytes": 2_147_483_648,
        },
    )
    samples: dict[str, bytes] = {
        "trigger.prepare": _compact_json(trigger_prepare),
        "trigger.request": _compact_json(trigger_request),
        **{
            f"inference.{task_type}.request": _compact_json(payload)
            for task_type, payload in inference_requests.items()
        },
        "training.telemetry": _compact_json(
            _serialize_transport_point(telemetry_point)
        ),
        **{
            f"inference.{name}.response": _compact_json(payload)
            for name, payload in _representative_inference_responses().items()
        },
    }
    return {
        "codec": "pydantic-core-compact-utf8-json",
        "samples": {
            name: {
                "serialized_size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in samples.items()
        },
    }


def _representative_inference_responses() -> dict[str, dict[str, object]]:
    """按当前五类正式序列化字段构造 normal/dense 结果样本。"""

    runtime_session = {
        "backend_name": "onnxruntime",
        "model_uri": "models/runtime/model.onnx",
        "device_name": "cpu",
        "input_spec": {
            "name": "images",
            "shape": [1, 3, 1024, 1024],
            "dtype": "float32",
        },
        "output_specs": [
            {"name": "output0", "shape": [1, 300, 84], "dtype": "float32"}
        ],
        "metadata": {"precision": "fp32"},
    }
    common = {"latency_ms": 12.5, "image_width": 1920, "image_height": 1080}
    classification_categories = [
        {
            "class_id": index,
            "probability": round(1.0 / (index + 2), 8),
            "class_name": f"category-{index}",
            "logit": round(5.0 - index * 0.01, 6),
        }
        for index in range(1000)
    ]
    detections = [
        {
            "bbox_xyxy": [10.25, 20.5, 300.75, 400.125],
            "score": 0.912345,
            "class_id": index % 80,
            "class_name": f"class-{index % 80}",
        }
        for index in range(300)
    ]
    pose_instances = [
        {
            "bbox_xyxy": [10.25, 20.5, 300.75, 400.125],
            "score": 0.912345,
            "class_id": 0,
            "class_name": "person",
            "keypoints": [
                {
                    "x": 100.125 + keypoint,
                    "y": 200.25 + keypoint,
                    "confidence": 0.875,
                }
                for keypoint in range(17)
            ],
            "kpt_shape": [17, 3],
        }
        for _ in range(100)
    ]
    obb_instances = [
        {
            "bbox_xyxy": [10.25, 20.5, 300.75, 400.125],
            "bbox_xywhr": [155.5, 210.25, 290.5, 379.625, 0.785398],
            "score": 0.912345,
            "class_id": index % 20,
            "class_name": f"class-{index % 20}",
            "angle": 0.785398,
        }
        for index in range(300)
    ]

    def segmentation_instances(points_per_instance: int) -> list[dict[str, object]]:
        polygon = [
            [round(100.125 + point * 0.25, 3), round(200.25 + point * 0.125, 3)]
            for point in range(points_per_instance)
        ]
        return [
            {
                "bbox_xyxy": [10.25, 20.5, 300.75, 400.125],
                "score": 0.912345,
                "class_id": index % 20,
                "class_name": f"class-{index % 20}",
                "segments": [polygon],
                "mask_area": 12345.5,
            }
            for index in range(100)
        ]

    return {
        "classification-1000": {
            **common,
            "categories": classification_categories,
            "top_category": classification_categories[0],
            "runtime_session_info": runtime_session,
        },
        "detection-300": {
            **common,
            "detections": detections,
            "runtime_session_info": runtime_session,
        },
        "pose-100x17": {
            **common,
            "instances": pose_instances,
            "runtime_session_info": runtime_session,
        },
        "obb-300": {
            **common,
            "instances": obb_instances,
            "runtime_session_info": runtime_session,
        },
        "segmentation-normal-100x100": {
            **common,
            "instances": segmentation_instances(100),
            "runtime_session_info": runtime_session,
        },
        "segmentation-dense-100x1000": {
            **common,
            "instances": segmentation_instances(1000),
            "runtime_session_info": runtime_session,
        },
    }


def collect_observed_local_payload_sizes(
    *,
    database_path: Path = ROOT / "data" / "amvision.db",
    queue_root: Path = ROOT / "data" / "queue",
) -> dict[str, object]:
    """只读采集当前开发数据中的 JSON 长度，不复制任何业务内容。"""

    report: dict[str, object] = {
        "database_path": str(database_path),
        "queue_root": str(queue_root),
        "database": {"available": False, "sources": {}},
        "file_queue": {"available": False, "queues": {}},
    }
    if database_path.is_file():
        connection = sqlite3.connect(
            f"file:{database_path.resolve().as_posix()}?mode=ro",
            uri=True,
        )
        try:
            sources: dict[str, object] = {}
            queries = {
                "workflow_preview_runs.outputs_json": (
                    "SELECT length(outputs_json) FROM workflow_preview_runs "
                    "WHERE outputs_json IS NOT NULL"
                ),
                "workflow_runs.input_payload_json": (
                    "SELECT length(input_payload_json) FROM workflow_runs "
                    "WHERE input_payload_json IS NOT NULL"
                ),
                "workflow_runs.outputs_json": (
                    "SELECT length(outputs_json) FROM workflow_runs "
                    "WHERE outputs_json IS NOT NULL"
                ),
                "tasks.result_json": (
                    "SELECT length(result_json) FROM tasks WHERE result_json IS NOT NULL"
                ),
                "queue_outbox_messages.payload_json": (
                    "SELECT length(payload_json) FROM queue_outbox_messages "
                    "WHERE payload_json IS NOT NULL"
                ),
            }
            for source_name, query in queries.items():
                try:
                    sizes = [int(row[0]) for row in connection.execute(query) if row[0]]
                except sqlite3.DatabaseError as error:
                    sources[source_name] = {
                        "available": False,
                        "error": str(error),
                    }
                    continue
                sources[source_name] = (
                    {"available": True, **summarize_samples(sizes)}
                    if sizes
                    else {"available": True, "sample_count": 0}
                )
            report["database"] = {"available": True, "sources": sources}
        finally:
            connection.close()
    if queue_root.is_dir():
        sizes_by_queue: dict[str, list[int]] = {}
        for path in queue_root.rglob("*.json"):
            relative = path.relative_to(queue_root)
            if not relative.parts or relative.parts[0].startswith("_"):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            sizes_by_queue.setdefault(relative.parts[0], []).append(size)
        report["file_queue"] = {
            "available": True,
            "queues": {
                queue_name: summarize_samples(sizes)
                for queue_name, sizes in sorted(sizes_by_queue.items())
                if sizes
            },
        }
    return report


def collect_machine_metadata() -> dict[str, object]:
    """记录复现实验所需的机器、运行时和仓库信息。"""

    power_scheme = "unavailable"
    if os.name == "nt":
        completed = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        power_scheme = (completed.stdout or completed.stderr).strip()
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    ).stdout.strip()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "python_executable": sys.executable,
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "total_memory_bytes": psutil.virtual_memory().total,
        "power_scheme": power_scheme,
        "git_commit": git_commit,
        "process_start_method": "spawn",
    }


def _wait_until(
    operation: Callable[[], object | None],
    *,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.0005,
) -> tuple[object, int]:
    """在有界 deadline 内等待非空结果并返回轮询次数。"""

    deadline = time.monotonic() + timeout_seconds
    poll_count = 0
    while time.monotonic() < deadline:
        try:
            result = operation()
        except MmapGuardBusyError:
            result = None
        if result is not None:
            return result, poll_count
        poll_count += 1
        time.sleep(poll_seconds)
    raise TimeoutError("阶段 0 benchmark 等待响应超时")


def _measure_operation_ms(operation: Callable[[], object]) -> float:
    """执行一次操作并返回 wall-clock 毫秒数。"""

    started_ns = time.perf_counter_ns()
    operation()
    return (time.perf_counter_ns() - started_ns) / 1_000_000


def benchmark_cold_open(settings: BenchmarkSettings) -> dict[str, object]:
    """分别采集当前 Trigger/Inference/Telemetry 的 create 与 reopen 成本。"""

    reports: dict[str, object] = {}
    with TemporaryDirectory(
        prefix="local-message-stage0-cold-",
        dir=ROOT / ".tmp",
    ) as temporary_root:
        root = Path(temporary_root)
        trigger_create: list[float] = []
        trigger_reopen: list[float] = []
        inference_create: list[float] = []
        inference_reopen: list[float] = []
        telemetry_create: list[float] = []
        telemetry_reopen: list[float] = []
        for round_index in range(settings.rounds):
            trigger_root = root / f"trigger-{round_index}"
            trigger_create.append(
                _measure_operation_ms(
                    lambda: _open_and_close_trigger_server(trigger_root)
                )
            )
            trigger_reopen.append(
                _measure_operation_ms(
                    lambda: _open_and_close_trigger_server(trigger_root)
                )
            )

            inference_root = root / f"inference-{round_index}"
            inference_create.append(
                _measure_operation_ms(
                    lambda: _open_and_close_inference_server(inference_root)
                )
            )
            inference_reopen.append(
                _measure_operation_ms(
                    lambda: _open_and_close_inference_server(inference_root)
                )
            )

            telemetry_root = root / f"telemetry-{round_index}"
            telemetry_create.append(
                _measure_operation_ms(
                    lambda: _open_and_close_telemetry_publisher(telemetry_root)
                )
            )
            telemetry_existing_path = next(telemetry_root.glob("worker-*.mmap"))
            telemetry_reopen.append(
                _measure_operation_ms(
                    lambda: _open_and_close_telemetry_reader(
                        telemetry_existing_path
                    )
                )
            )
        reports["workflow_trigger"] = {
            "cold_create_ms": summarize_samples(trigger_create),
            "cold_reopen_ms": summarize_samples(trigger_reopen),
            "file_size_bytes": rpc_layout(
                WORKFLOW_TRIGGER_RPC_PROFILE_V1
            ).file_size_bytes,
        }
        reports["inference"] = {
            "cold_create_ms": summarize_samples(inference_create),
            "cold_reopen_ms": summarize_samples(inference_reopen),
            "profile": {
                "descriptor_count": 128,
                "inline_request_capacity_bytes": 64 * 1024,
                "inline_response_capacity_bytes": 256 * 1024,
                "overflow_page_count": 512,
                "overflow_page_capacity_bytes": 256 * 1024,
            },
        }
        reports["training_telemetry"] = {
            "cold_create_ms": summarize_samples(telemetry_create),
            "cold_reopen_ms": summarize_samples(telemetry_reopen),
            "profile": {
                "slot_count": 512,
                "payload_capacity_bytes": 16 * 1024,
            },
        }
    return reports


def _open_and_close_trigger_server(buffers_root: Path) -> None:
    """创建并立即关闭当前 Trigger owner。"""

    with WorkflowTriggerMailboxServer(buffers_root=buffers_root):
        pass


def _open_and_close_inference_server(buffers_root: Path) -> None:
    """创建并立即关闭当前 Inference owner。"""

    server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="stage0",
        request_handler=lambda item: item,
    )
    server.start()
    server.stop()


def _open_and_close_telemetry_publisher(root: Path) -> None:
    """创建并正常关闭当前 Telemetry producer。"""

    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=root,
        min_publish_interval_seconds=0,
    )
    publisher.start()
    publisher.close()


def _open_and_close_telemetry_reader(path: Path) -> None:
    """重新打开并关闭现有 Telemetry ring。"""

    paths = LocalMessageChannelPaths(
        mmap_path=path,
        owner_lock_path=path.with_name(f"{path.name}.owner.lock"),
        guard_path=path.with_name(f"{path.name}.guard"),
    )
    reader = MmapEventRingReader(
        paths=paths,
        profile=TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    )
    reader.close(deadline_ns=time.monotonic_ns())


def _trigger_client_process(
    *,
    buffers_root: str,
    worker_index: int,
    iterations: int,
    warmup_iterations: int,
    expected_response_size: int,
    start_event: object,
    result_queue: object,
) -> None:
    """在独立进程内完成当前 Trigger PREPARE 到 ACK 全链路。"""

    latencies: list[float] = []
    poll_count = 0
    success_count = 0
    capacity_reject_count = 0
    phase = "open"
    before = _snapshot_process_resources([os.getpid()])
    try:
        with WorkflowTriggerMailboxClient(buffers_root=buffers_root) as client:
            phase = "wait-start"
            start_event.wait(timeout=30.0)  # type: ignore[attr-defined]
            total = warmup_iterations + iterations
            for sequence in range(total):
                request = _compact_json(
                    {
                        "format_id": "amvision.workflow-trigger-request.v1",
                        "trigger_source_id": "stage0",
                        "event_id": f"{worker_index}-{sequence}",
                        "payload": {"sequence": sequence},
                        "metadata": {},
                    }
                )
                started_ns = time.perf_counter_ns()
                phase = f"claim:{sequence}"
                identity = client.claim(
                    timeout_ms=30_000,
                    route_generation=1,
                    prepare_payload=request,
                )
                phase = (
                    f"wait-allocation:{sequence}:d{identity.descriptor_index}:"
                    f"g{identity.generation}:t{identity.owner_token}"
                )
                allocation, allocation_polls = _wait_until(
                    lambda: client.read_writing_allocation(identity=identity)
                )
                poll_count += allocation_polls
                authoritative_identity = allocation.identity  # type: ignore[attr-defined]
                phase = f"publish-request:{sequence}"
                client.publish_request(
                    identity=authoritative_identity,
                    payload=request,
                )
                phase = f"wait-response:{sequence}"
                response, response_polls = _wait_until(
                    lambda: client.read_response(identity=authoritative_identity)
                )
                poll_count += response_polls
                error_code = int(response.error_code)  # type: ignore[attr-defined]
                if error_code == trigger_contract.ERROR_CODE_NONE:
                    if response.payload_size != expected_response_size:  # type: ignore[attr-defined]
                        raise AssertionError("Trigger response 大小不匹配")
                    success_count += 1
                elif (
                    error_code
                    == trigger_contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED
                ):
                    capacity_reject_count += 1
                else:
                    raise AssertionError(
                        f"Trigger benchmark 收到非容量错误：{error_code}"
                    )
                phase = f"acknowledge:{sequence}"
                client.acknowledge(identity=authoritative_identity)
                phase = f"record:{sequence}"
                if sequence >= warmup_iterations:
                    latencies.append(
                        (time.perf_counter_ns() - started_ns) / 1_000_000
                    )
        result_queue.put(  # type: ignore[attr-defined]
            {
                "worker_index": worker_index,
                "latencies_ms": latencies,
                "poll_wakeup_count": poll_count,
                "success_count": success_count,
                "capacity_reject_count": capacity_reject_count,
                "resources": _resource_delta(
                    before,
                    _snapshot_process_resources([os.getpid()]),
                ),
                "error": None,
            }
        )
    except BaseException as error:  # noqa: BLE001 - 子进程必须回传完整错误
        result_queue.put(  # type: ignore[attr-defined]
            {
                "worker_index": worker_index,
                "latencies_ms": latencies,
                "poll_wakeup_count": poll_count,
                "success_count": success_count,
                "capacity_reject_count": capacity_reject_count,
                "resources": None,
                "error": f"{error.__class__.__name__} at {phase}: {error}",
            }
        )


def _run_trigger_round(
    *,
    buffers_root: Path,
    response_payload: bytes,
    concurrency: int,
    iterations: int,
    warmup_iterations: int,
) -> dict[str, object]:
    """运行一轮真实跨进程 Trigger mailbox。"""

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    per_worker, remainder = divmod(iterations, concurrency)
    warmup_per_worker, warmup_remainder = divmod(warmup_iterations, concurrency)
    workers = tuple(
        context.Process(
            target=_trigger_client_process,
            kwargs={
                "buffers_root": str(buffers_root),
                "worker_index": index,
                "iterations": per_worker + (1 if index < remainder else 0),
                "warmup_iterations": warmup_per_worker
                + (1 if index < warmup_remainder else 0),
                "expected_response_size": len(response_payload),
                "start_event": start_event,
                "result_queue": result_queue,
            },
            name=f"stage0-trigger-client-{index}",
        )
        for index in range(concurrency)
    )
    with WorkflowTriggerMailboxServer(buffers_root=buffers_root) as server:
        for worker in workers:
            worker.start()
        process_ids = [os.getpid()]
        before = _snapshot_process_resources(process_ids)
        start_event.set()
        expected = iterations + warmup_iterations
        completed = 0
        reports: list[dict[str, object]] = []
        terminal_observations: list[dict[str, object]] = []
        started_ns = time.perf_counter_ns()
        round_deadline = time.monotonic() + 120.0
        try:
            while completed < expected:
                if time.monotonic() >= round_deadline:
                    raise TimeoutError("Trigger benchmark round 总 deadline 已到期")
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
                    server.publish_response(
                        identity=request.identity,
                        payload=response_payload,
                    )
                    completed += 1
                    made_progress = True
                sweep_result = server.sweep()
                if any(
                    int(sweep_result[name]) > 0
                    for name in (
                        "cancelled_count",
                        "deadline_exceeded_count",
                        "response_ack_timeout_count",
                        "released_count",
                    )
                ):
                    terminal_observations.append(sweep_result)
                    del terminal_observations[:-32]
                while True:
                    try:
                        report = result_queue.get_nowait()
                    except Empty:
                        break
                    reports.append(report)
                    if report.get("error"):
                        raise RuntimeError(
                            f"{report['error']}; terminal={terminal_observations}; "
                            f"status={server.build_status()}"
                        )
                if len(reports) == len(workers) and completed < expected:
                    raise RuntimeError(
                        "Trigger client 已全部终止，但 server 未收到预期请求"
                    )
                if any(worker.exitcode not in {None, 0} for worker in workers):
                    raise RuntimeError("Trigger client 子进程异常退出")
                if not made_progress:
                    time.sleep(0.0002)
            while len(reports) < len(workers):
                reports.append(result_queue.get(timeout=30.0))
            errors = [str(report["error"]) for report in reports if report["error"]]
            if errors:
                raise RuntimeError("; ".join(errors))
            for worker in workers:
                worker.join(timeout=30.0)
            after = _snapshot_process_resources(process_ids)
            latencies = [
                float(value)
                for report in reports
                for value in report["latencies_ms"]
            ]
            if len(latencies) != iterations:
                raise AssertionError("Trigger latency 样本数量不一致")
            status = server.build_status()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and (
                status["descriptor_state_counts"][0]
                != trigger_contract.DESCRIPTOR_COUNT
            ):
                server.sweep()
                time.sleep(0.0005)
                status = server.build_status()
            if status["used_page_count"] != 0:
                raise AssertionError("Trigger page 未完全回收")
            return {
                **summarize_samples(latencies),
                "elapsed_ms": round(
                    (time.perf_counter_ns() - started_ns) / 1_000_000,
                    6,
                ),
                "poll_wakeup_count": sum(
                    int(report["poll_wakeup_count"]) for report in reports
                ),
                "success_count": sum(
                    int(report["success_count"]) for report in reports
                ),
                "capacity_reject_count": sum(
                    int(report["capacity_reject_count"]) for report in reports
                ),
                "resources": {
                    "server_process": _resource_delta(before, after),
                    "client_processes": [report["resources"] for report in reports],
                },
            }
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=5.0)
            result_queue.close()


def benchmark_trigger(settings: BenchmarkSettings) -> dict[str, object]:
    """采集当前 Workflow Trigger mailbox 的稳态矩阵。"""

    cells: list[dict[str, object]] = []
    with TemporaryDirectory(
        prefix="local-message-stage0-trigger-",
        dir=ROOT / ".tmp",
    ) as temporary_root:
        root = Path(temporary_root)
        for response_size in settings.response_sizes:
            response = _compact_json(
                _response_payload(response_size, seed=settings.seed + response_size)
            )
            iterations = (
                settings.inline_iterations
                if response_size <= 64 * 1024
                else settings.large_iterations
            )
            for concurrency in settings.concurrency:
                rounds = [
                    _run_trigger_round(
                        buffers_root=root / f"{response_size}-{concurrency}-{round_index}",
                        response_payload=response,
                        concurrency=concurrency,
                        iterations=max(iterations, concurrency),
                        warmup_iterations=(
                            settings.warmup_iterations
                            if response_size <= 64 * 1024
                            else min(1, settings.warmup_iterations)
                        ),
                    )
                    for round_index in range(settings.rounds)
                ]
                cells.append(
                    {
                        "response_size_bytes": len(response),
                        "concurrency": concurrency,
                        "summary": summarize_rounds(rounds),
                    }
                )
    return {"transport": "current-workflow-trigger-mmap-v1", "cells": cells}


def _inference_client_process(
    *,
    buffers_root: str,
    worker_index: int,
    iterations: int,
    warmup_iterations: int,
    expected_value_size: int,
    start_event: object,
    result_queue: object,
) -> None:
    """在独立进程内调用当前 Inference mailbox。"""

    import backend.service.infrastructure.ipc.local_message.rpc_mailbox as module

    latencies: list[float] = []
    poll_count = 0
    success_count = 0
    capacity_reject_count = 0
    original_sleep = module.sleep
    before = _snapshot_process_resources([os.getpid()])

    def counted_sleep(seconds: float) -> None:
        nonlocal poll_count
        poll_count += 1
        original_sleep(seconds)

    module.sleep = counted_sleep
    client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="stage0",
        request_timeout_seconds=60.0,
    )
    try:
        start_event.wait(timeout=30.0)  # type: ignore[attr-defined]
        total = warmup_iterations + iterations
        for sequence in range(total):
            started_ns = time.perf_counter_ns()
            response = client.request(
                {
                    "action": "infer",
                    "task_type": "segmentation",
                    "worker_index": worker_index,
                    "sequence": sequence,
                }
            )
            if response.get("ok") is True:
                result = response.get("result")
                value = result.get("value") if isinstance(result, dict) else None
                if not isinstance(value, str) or len(value) != expected_value_size:
                    raise AssertionError("Inference response 正文大小不匹配")
                success_count += 1
            else:
                error = response.get("error")
                error_code = error.get("error_code") if isinstance(error, dict) else None
                if error_code != "mmap_response_capacity_exhausted":
                    raise AssertionError(
                        f"Inference benchmark 收到非容量错误：{error_code}"
                    )
                capacity_reject_count += 1
            if sequence >= warmup_iterations:
                latencies.append(
                    (time.perf_counter_ns() - started_ns) / 1_000_000
                )
        result_queue.put(  # type: ignore[attr-defined]
            {
                "worker_index": worker_index,
                "latencies_ms": latencies,
                "poll_wakeup_count": poll_count,
                "success_count": success_count,
                "capacity_reject_count": capacity_reject_count,
                "resources": _resource_delta(
                    before,
                    _snapshot_process_resources([os.getpid()]),
                ),
                "error": None,
            }
        )
    except BaseException as error:  # noqa: BLE001 - 子进程必须回传完整错误
        result_queue.put(  # type: ignore[attr-defined]
            {
                "worker_index": worker_index,
                "latencies_ms": latencies,
                "poll_wakeup_count": poll_count,
                "success_count": success_count,
                "capacity_reject_count": capacity_reject_count,
                "resources": None,
                "error": f"{error.__class__.__name__}: {error}",
            }
        )
    finally:
        client.close()
        module.sleep = original_sleep


def _run_inference_round(
    *,
    buffers_root: Path,
    result_value: str,
    concurrency: int,
    iterations: int,
    warmup_iterations: int,
) -> dict[str, object]:
    """运行一轮真实跨进程 Inference mailbox。"""

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    per_worker, remainder = divmod(iterations, concurrency)
    warmup_per_worker, warmup_remainder = divmod(warmup_iterations, concurrency)
    server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="stage0",
        request_handler=lambda _payload: {"value": result_value},
        max_concurrent_requests=16,
    )
    server.start()
    workers = tuple(
        context.Process(
            target=_inference_client_process,
            kwargs={
                "buffers_root": str(buffers_root),
                "worker_index": index,
                "iterations": per_worker + (1 if index < remainder else 0),
                "warmup_iterations": warmup_per_worker
                + (1 if index < warmup_remainder else 0),
                "expected_value_size": len(result_value),
                "start_event": start_event,
                "result_queue": result_queue,
            },
            name=f"stage0-inference-client-{index}",
        )
        for index in range(concurrency)
    )
    try:
        for worker in workers:
            worker.start()
        process_ids = [os.getpid()]
        before = _snapshot_process_resources(process_ids)
        started_ns = time.perf_counter_ns()
        start_event.set()
        reports = [result_queue.get(timeout=180.0) for _ in workers]
        for worker in workers:
            worker.join(timeout=30.0)
        errors = [str(report["error"]) for report in reports if report["error"]]
        if errors:
            raise RuntimeError("; ".join(errors))
        after = _snapshot_process_resources(process_ids)
        latencies = [
            float(value)
            for report in reports
            for value in report["latencies_ms"]
        ]
        if len(latencies) != iterations:
            raise AssertionError("Inference latency 样本数量不一致")
        return {
            **summarize_samples(latencies),
            "elapsed_ms": round(
                (time.perf_counter_ns() - started_ns) / 1_000_000,
                6,
            ),
            "poll_wakeup_count": sum(
                int(report["poll_wakeup_count"]) for report in reports
            ),
            "success_count": sum(
                int(report["success_count"]) for report in reports
            ),
            "capacity_reject_count": sum(
                int(report["capacity_reject_count"]) for report in reports
            ),
            "resources": {
                "server_process": _resource_delta(before, after),
                "client_processes": [report["resources"] for report in reports],
            },
            "server_health": server.get_health_summary(),
        }
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5.0)
        result_queue.close()
        server.stop()


def benchmark_inference(settings: BenchmarkSettings) -> dict[str, object]:
    """采集当前 Inference mailbox 的稳态矩阵。"""

    cells: list[dict[str, object]] = []
    with TemporaryDirectory(
        prefix="local-message-stage0-inference-",
        dir=ROOT / ".tmp",
    ) as temporary_root:
        root = Path(temporary_root)
        for response_size in settings.response_sizes:
            # Inference server 会增加 ok/result envelope，因此为 envelope 留出余量。
            value_size = max(1, min(response_size, 32 * MIB) - 1024)
            result_value = _deterministic_text(
                value_size,
                seed=settings.seed + response_size + 1,
            )
            iterations = (
                settings.inline_iterations
                if response_size <= 64 * 1024
                else settings.large_iterations
            )
            for concurrency in settings.concurrency:
                rounds = [
                    _run_inference_round(
                        buffers_root=root
                        / f"{response_size}-{concurrency}-{round_index}",
                        result_value=result_value,
                        concurrency=concurrency,
                        iterations=max(iterations, concurrency),
                        warmup_iterations=(
                            settings.warmup_iterations
                            if response_size <= 64 * 1024
                            else min(1, settings.warmup_iterations)
                        ),
                    )
                    for round_index in range(settings.rounds)
                ]
                cells.append(
                    {
                        "target_response_size_bytes": response_size,
                        "value_size_bytes": value_size,
                        "concurrency": concurrency,
                        "summary": summarize_rounds(rounds),
                    }
                )
    return {"transport": "local-message-inference-rpc.v1", "cells": cells}


def _telemetry_publisher_process(
    *,
    root_dir: str,
    iterations: int,
    publish_interval_seconds: float,
    ready_queue: object,
    start_event: object,
) -> None:
    """以真实 spawn producer 发布带 monotonic 时间戳的遥测点。"""

    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=root_dir,
        min_publish_interval_seconds=0,
    )
    before = _snapshot_process_resources([os.getpid()])
    try:
        publisher.start()
        ready_queue.put(str(publisher.path))  # type: ignore[attr-defined]
        start_event.wait(timeout=30.0)  # type: ignore[attr-defined]
        for sequence in range(1, iterations + 1):
            sent_ns = time.perf_counter_ns()
            published = publisher.publish(
                TrainingTelemetryPoint(
                    task_id="training-task-stage0",
                    attempt_no=1,
                    task_type="segmentation",
                    model_type="yolo11",
                    stage="training",
                    granularity="batch",
                    epoch=1,
                    max_epochs=10,
                    step=sequence,
                    steps_per_epoch=iterations,
                    global_step=sequence,
                    total_steps=iterations * 10,
                    progress_percent=sequence / iterations * 10.0,
                    learning_rate=0.001,
                    metrics={"loss": 1.0 / sequence},
                    input_size=(1024, 1024),
                    runtime={"stage0_sent_ns": sent_ns},
                )
            )
            if not published:
                raise AssertionError("Telemetry publisher 意外拒绝有效点")
            time.sleep(publish_interval_seconds)
        ready_queue.put(  # type: ignore[attr-defined]
            {
                "resources": _resource_delta(
                    before,
                    _snapshot_process_resources([os.getpid()]),
                )
            }
        )
    finally:
        publisher.close()


def _run_telemetry_round(
    *,
    root: Path,
    iterations: int,
    poll_interval_seconds: float,
) -> dict[str, object]:
    """采集单 producer EventRing 的端到端可见延迟。"""

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    start_event = context.Event()
    producer = context.Process(
        target=_telemetry_publisher_process,
        kwargs={
            "root_dir": str(root),
            "iterations": iterations,
            "publish_interval_seconds": 0.01,
            "ready_queue": ready_queue,
            "start_event": start_event,
        },
        name="stage0-training-telemetry-producer",
    )
    producer.start()
    path = Path(ready_queue.get(timeout=30.0))
    paths = LocalMessageChannelPaths(
        mmap_path=path,
        owner_lock_path=path.with_name(f"{path.name}.owner.lock"),
        guard_path=path.with_name(f"{path.name}.guard"),
    )
    reader = MmapEventRingReader(
        paths=paths,
        profile=TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    )
    latencies: list[float] = []
    poll_count = 0
    cursor: EventCursor | None = None
    process_ids = [os.getpid()]
    before = _snapshot_process_resources(process_ids)
    started_ns = time.perf_counter_ns()
    start_event.set()
    try:
        deadline = time.monotonic() + 60.0
        while len(latencies) < iterations and time.monotonic() < deadline:
            result = reader.read(
                cursor=cursor,
                deadline_ns=time.monotonic_ns(),
                limit=512,
            )
            cursor = result.next_cursor
            for wire_bytes in result.events:
                point = decode_training_telemetry_point(wire_bytes)
                runtime = point.runtime if point is not None else None
                sent_ns = runtime.get("stage0_sent_ns") if isinstance(runtime, dict) else None
                if isinstance(sent_ns, int):
                    latencies.append((time.perf_counter_ns() - sent_ns) / 1_000_000)
            if len(latencies) < iterations:
                poll_count += 1
                time.sleep(poll_interval_seconds)
        producer.join(timeout=10.0)
        if producer.exitcode != 0:
            raise RuntimeError(f"Telemetry producer 退出码异常：{producer.exitcode}")
        producer_report = ready_queue.get(timeout=5.0)
        if len(latencies) != iterations:
            raise TimeoutError("Telemetry latency 样本数量不足")
        after = _snapshot_process_resources(process_ids)
        return {
            **summarize_samples(latencies),
            "elapsed_ms": round(
                (time.perf_counter_ns() - started_ns) / 1_000_000,
                6,
            ),
            "poll_interval_seconds": poll_interval_seconds,
            "poll_wakeup_count": poll_count,
            "resources": {
                "reader_process": _resource_delta(before, after),
                "producer_process": producer_report["resources"],
            },
        }
    finally:
        reader.close(deadline_ns=time.monotonic_ns())
        if producer.is_alive():
            producer.terminate()
        producer.join(timeout=5.0)
        ready_queue.close()


def benchmark_telemetry(settings: BenchmarkSettings) -> dict[str, object]:
    """比较当前 Training telemetry 的可配置轮询策略。"""

    cells: list[dict[str, object]] = []
    with TemporaryDirectory(
        prefix="local-message-stage0-telemetry-",
        dir=ROOT / ".tmp",
    ) as temporary_root:
        root = Path(temporary_root)
        for poll_interval in (0.01, 0.05, 0.1):
            rounds = [
                _run_telemetry_round(
                    root=root / f"{poll_interval}-{round_index}",
                    iterations=settings.telemetry_iterations,
                    poll_interval_seconds=poll_interval,
                )
                for round_index in range(settings.rounds)
            ]
            cells.append(
                {
                    "poll_interval_seconds": poll_interval,
                    "summary": summarize_rounds(rounds),
                }
            )
    scan_cells = benchmark_telemetry_scan_policy(settings)
    return {
        "transport": "current-training-telemetry-mmap",
        "cells": cells,
        "scan_cells": scan_cells,
    }


def _run_telemetry_scan_round(
    *,
    root: Path,
    scan_interval_seconds: float,
) -> dict[str, object]:
    """测量 receiver 已运行后发现新 producer 的真实延迟。"""

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
    )
    profile = EventRingChannelProfile(
        profile_id=f"training-telemetry-stage0-scan-{scan_interval_seconds}",
        slot_count=TRAINING_TELEMETRY_EVENT_PROFILE_V1.slot_count,
        payload_capacity_bytes=(
            TRAINING_TELEMETRY_EVENT_PROFILE_V1.payload_capacity_bytes
        ),
        poll_interval_seconds=0.05,
        scan_interval_seconds=scan_interval_seconds,
    )
    receiver = TrainingTelemetryMmapReceiver(
        buffers_root=root,
        broker=broker,
        profile=profile,
    )
    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=root,
        min_publish_interval_seconds=0,
        profile=profile,
    )
    before = _snapshot_process_resources([os.getpid()])
    receiver.start()
    # 等待首次空目录 scan 完成，使新 producer 落入后续 scan 周期。
    time.sleep(0.075)
    publisher.start()
    started_ns = time.perf_counter_ns()
    publisher.publish(
        TrainingTelemetryPoint(
            task_id="training-task-stage0-scan",
            attempt_no=1,
            task_type="detection",
            model_type="yolo11",
            stage="training",
            granularity="batch",
            step=1,
            steps_per_epoch=1,
            global_step=1,
            total_steps=1,
            progress_percent=1.0,
            metrics={"loss": 1.0},
        )
    )
    try:
        deadline = time.monotonic() + max(5.0, scan_interval_seconds * 4)
        while time.monotonic() < deadline:
            replay = broker.replay(
                task_id="training-task-stage0-scan",
                after_cursor=None,
                limit=1,
            )
            if replay.events:
                latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
                after = _snapshot_process_resources([os.getpid()])
                return {
                    "mean": latency_ms,
                    "p50": latency_ms,
                    "p95": latency_ms,
                    "p99": latency_ms,
                    "max": latency_ms,
                    "resources": _resource_delta(before, after),
                }
            time.sleep(0.001)
        raise TimeoutError("Training telemetry producer discovery 超时")
    finally:
        publisher.close()
        receiver.stop()


def benchmark_telemetry_scan_policy(
    settings: BenchmarkSettings,
) -> list[dict[str, object]]:
    """比较新 producer 的 scan 发现策略。"""

    cells: list[dict[str, object]] = []
    with TemporaryDirectory(
        prefix="local-message-stage0-telemetry-scan-",
        dir=ROOT / ".tmp",
    ) as temporary_root:
        root = Path(temporary_root)
        for scan_interval in (0.1, 0.25, 0.5, 1.0):
            rounds = [
                _run_telemetry_scan_round(
                    root=root / f"{scan_interval}-{round_index}",
                    scan_interval_seconds=scan_interval,
                )
                for round_index in range(settings.rounds)
            ]
            cells.append(
                {
                    "scan_interval_seconds": scan_interval,
                    "poll_interval_seconds": 0.05,
                    "summary": summarize_rounds(rounds),
                }
            )
    return cells


def _queue_echo_process(
    *,
    request_queue: object,
    response_queue: object,
    mode: str,
) -> None:
    """按当前 object/pickle 或统一 bytes 语义执行 Queue echo。"""

    while True:
        message = request_queue.get()  # type: ignore[attr-defined]
        if message is None:
            return
        if mode == "python-object-pickle":
            request_id = str(message["request_id"])
            response = {
                "request_id": request_id,
                "ok": True,
                "result": {"value": message["payload"]["value"]},
            }
        elif mode == "compact-json-bytes":
            payload = from_json(bytes(message))
            response = _compact_json(
                {
                    "request_id": str(payload["request_id"]),
                    "ok": True,
                    "result": {"value": payload["payload"]["value"]},
                }
            )
        else:
            raise ValueError(f"不支持的 Queue benchmark mode：{mode}")
        response_queue.put(response)  # type: ignore[attr-defined]


def _run_queue_round(
    *,
    mode: str,
    value: str,
    concurrency: int,
    iterations: int,
    warmup_iterations: int,
) -> dict[str, object]:
    """采集 Queue 的 serialize 到 deserialize 完整端到端耗时。"""

    context = multiprocessing.get_context("spawn")
    request_queue = context.Queue()
    response_queue = context.Queue()
    worker = context.Process(
        target=_queue_echo_process,
        kwargs={
            "request_queue": request_queue,
            "response_queue": response_queue,
            "mode": mode,
        },
        name=f"stage0-queue-{mode}",
    )
    worker.start()
    process_ids = [os.getpid(), worker.pid] if worker.pid else [os.getpid()]
    before = _snapshot_process_resources(process_ids)
    started_by_request: dict[str, int] = {}
    latencies: list[float] = []
    total = warmup_iterations + iterations
    sent = 0
    received = 0
    started_ns = time.perf_counter_ns()
    try:
        while received < total:
            while sent < total and sent - received < concurrency:
                request_id = f"request-{sent}"
                request_started_ns = time.perf_counter_ns()
                payload = {
                    "request_id": request_id,
                    "payload": {"value": value},
                }
                message: object = (
                    payload if mode == "python-object-pickle" else _compact_json(payload)
                )
                request_queue.put(message)
                started_by_request[request_id] = request_started_ns
                sent += 1
            response = response_queue.get(timeout=60.0)
            if mode == "compact-json-bytes":
                response = from_json(bytes(response))
            request_id = str(response["request_id"])
            completed_ns = time.perf_counter_ns()
            sequence = int(request_id.rsplit("-", 1)[-1])
            if sequence >= warmup_iterations:
                latencies.append(
                    (completed_ns - started_by_request[request_id]) / 1_000_000
                )
            received += 1
        after = _snapshot_process_resources(process_ids)
        if len(latencies) != iterations:
            raise AssertionError("Queue latency 样本数量不一致")
        return {
            **summarize_samples(latencies),
            "elapsed_ms": round(
                (time.perf_counter_ns() - started_ns) / 1_000_000,
                6,
            ),
            "poll_wakeup_count": 0,
            "wakeup_kind": "multiprocessing.Queue blocking semaphore",
            "resources": _resource_delta(before, after),
        }
    finally:
        request_queue.put(None)
        worker.join(timeout=10.0)
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=5.0)
        request_queue.close()
        request_queue.join_thread()
        response_queue.close()
        response_queue.join_thread()


def benchmark_queue(settings: BenchmarkSettings) -> dict[str, object]:
    """形成当前 object/pickle 与统一 JSON bytes Queue 的两路基线。"""

    cells: list[dict[str, object]] = []
    for payload_size in (1024, 64 * 1024, MIB):
        value = _deterministic_text(
            max(1, payload_size - 256),
            seed=settings.seed + payload_size + 2,
        )
        iterations = (
            settings.inline_iterations if payload_size <= 64 * 1024 else settings.large_iterations
        )
        for concurrency in settings.concurrency:
            for mode in ("python-object-pickle", "compact-json-bytes"):
                rounds = [
                    _run_queue_round(
                        mode=mode,
                        value=value,
                        concurrency=concurrency,
                        iterations=max(iterations, concurrency),
                        warmup_iterations=(
                            settings.warmup_iterations
                            if payload_size <= 64 * 1024
                            else min(1, settings.warmup_iterations)
                        ),
                    )
                    for _round_index in range(settings.rounds)
                ]
                cells.append(
                    {
                        "mode": mode,
                        "payload_size_bytes": payload_size,
                        "concurrency": concurrency,
                        "summary": summarize_rounds(rounds),
                    }
                )
    return {"transport": "multiprocessing.Queue", "cells": cells}


def _benchmark_page_copy_round(
    *,
    path: Path,
    payload: bytes,
    page_size_bytes: int,
) -> dict[str, object]:
    """模拟候选 page-chain 的逐页写、逐页读和 CRC 成本。"""

    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w+b", buffering=0) as file:
        file.truncate(len(payload))
        with mmap.mmap(file.fileno(), len(payload), access=mmap.ACCESS_WRITE) as view:
            # Steady 只预触碰本场景实际访问的 page。
            for offset in range(0, len(payload), page_size_bytes):
                view[offset] = 0
            started_ns = time.perf_counter_ns()
            write_crc = 0
            for offset in range(0, len(payload), page_size_bytes):
                chunk = payload[offset : offset + page_size_bytes]
                view[offset : offset + len(chunk)] = chunk
                write_crc = zlib.crc32(chunk, write_crc)
            write_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            started_ns = time.perf_counter_ns()
            read_crc = 0
            for offset in range(0, len(payload), page_size_bytes):
                chunk = view[offset : offset + page_size_bytes]
                read_crc = zlib.crc32(chunk, read_crc)
            read_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            if write_crc != read_crc:
                raise AssertionError("page geometry benchmark CRC 不一致")
    return {
        "mean": write_ms + read_ms,
        "p50": write_ms + read_ms,
        "p95": write_ms + read_ms,
        "p99": write_ms + read_ms,
        "max": write_ms + read_ms,
        "write_ms": round(write_ms, 6),
        "read_ms": round(read_ms, 6),
        "page_count": math.ceil(len(payload) / page_size_bytes),
    }


def benchmark_page_geometry(settings: BenchmarkSettings) -> dict[str, object]:
    """比较候选固定 page 大小，不实现或接入新的 Channel engine。"""

    cells: list[dict[str, object]] = []
    with TemporaryDirectory(
        prefix="local-message-stage0-pages-",
        dir=ROOT / ".tmp",
    ) as temporary_root:
        root = Path(temporary_root)
        for payload_size in (MIB, 8 * MIB, 16 * MIB, 32 * MIB):
            payload = bytes(
                random.Random(settings.seed + payload_size + 3).randbytes(payload_size)
            )
            for page_size in PAGE_SIZE_CANDIDATES:
                rounds = [
                    _benchmark_page_copy_round(
                        path=root / f"{payload_size}-{page_size}-{round_index}.mmap",
                        payload=payload,
                        page_size_bytes=page_size,
                    )
                    for round_index in range(settings.rounds)
                ]
                cells.append(
                    {
                        "payload_size_bytes": payload_size,
                        "page_size_bytes": page_size,
                        "summary": summarize_rounds(rounds),
                    }
                )
    return {"kind": "candidate-page-geometry-copy-crc", "cells": cells}


def collect_current_contracts() -> dict[str, object]:
    """记录当前三条 mmap 实现的容量和运行策略。"""

    return {
        "workflow_trigger": {
            "contract_id": trigger_contract.CONTRACT_ID,
            "descriptor_count": trigger_contract.DESCRIPTOR_COUNT,
            "inline_request_capacity_bytes": (
                trigger_contract.INLINE_REQUEST_CAPACITY_BYTES
            ),
            "inline_response_capacity_bytes": (
                trigger_contract.INLINE_RESPONSE_CAPACITY_BYTES
            ),
            "overflow_page_count": trigger_contract.OVERFLOW_PAGE_COUNT,
            "overflow_page_capacity_bytes": (
                trigger_contract.OVERFLOW_PAGE_CAPACITY_BYTES
            ),
            "max_overflow_pages_per_response": (
                trigger_contract.MAX_OVERFLOW_PAGES_PER_RESPONSE
            ),
            "max_request_bytes": trigger_contract.MAX_REQUEST_BYTES,
            "max_response_bytes": trigger_contract.MAX_RESPONSE_BYTES,
        },
        "inference": {
            "descriptor_count": 128,
            "inline_request_capacity_bytes": 512 * 1024,
            "inline_response_capacity_bytes": 512 * 1024,
            "overflow_page_count": 256,
            "overflow_page_capacity_bytes": 512 * 1024,
            "max_overflow_pages_per_response": 64,
            "compression_threshold_bytes": 256 * 1024,
            "poll_interval_seconds": 0.001,
        },
        "training_telemetry": {
            "slot_count": 512,
            "payload_capacity_bytes": 16 * 1024,
            "min_publish_interval_seconds": 0.1,
            "poll_interval_seconds": 0.1,
            "scan_interval_seconds": 1.0,
        },
    }


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """通过同目录临时文件原子发布 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def run_benchmark(settings: BenchmarkSettings) -> dict[str, object]:
    """执行阶段 0 完整采集并原子写入 JSON 报告。"""

    settings.validate()
    settings.output_path.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / ".tmp").mkdir(parents=True, exist_ok=True)
    report = {
        "format_id": REPORT_FORMAT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings": {
            **asdict(settings),
            "output_path": str(settings.output_path),
        },
        "machine": collect_machine_metadata(),
        "current_contracts": collect_current_contracts(),
        "payload_inventory": build_payload_inventory(),
        "observed_local_payload_sizes": collect_observed_local_payload_sizes(),
    }
    partial_path = settings.output_path.with_suffix(".partial.json")
    suites: tuple[tuple[str, Callable[[BenchmarkSettings], dict[str, object]]], ...] = (
        ("cold", benchmark_cold_open),
        ("workflow_trigger", benchmark_trigger),
        ("inference", benchmark_inference),
        ("training_telemetry", benchmark_telemetry),
        ("queue", benchmark_queue),
        ("page_geometry", benchmark_page_geometry),
    )
    for suite_name, suite in suites:
        print(f"START suite={suite_name}", flush=True)
        report[suite_name] = suite(settings)
        _write_json_atomic(partial_path, report)
        print(f"DONE suite={suite_name}", flush=True)
    _write_json_atomic(settings.output_path, report)
    partial_path.unlink(missing_ok=True)
    return report


def enrich_existing_report(
    path: Path,
    *,
    measure_telemetry_scan: bool = False,
) -> dict[str, object]:
    """只更新确定性 payload corpus 与只读本地长度观测，不重跑性能矩阵。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format_id") != REPORT_FORMAT_ID:
        raise ValueError("只允许补充同版本阶段 0 baseline")
    payload["payload_inventory"] = build_payload_inventory()
    payload["observed_local_payload_sizes"] = collect_observed_local_payload_sizes()
    if measure_telemetry_scan:
        settings_payload = payload.get("settings")
        round_count = (
            int(settings_payload.get("rounds") or 5)
            if isinstance(settings_payload, dict)
            else 5
        )
        telemetry_payload = payload.get("training_telemetry")
        if not isinstance(telemetry_payload, dict):
            raise ValueError("现有 baseline 缺少 training_telemetry suite")
        telemetry_payload["scan_cells"] = benchmark_telemetry_scan_policy(
            BenchmarkSettings(output_path=path, rounds=round_count)
        )
    payload["enriched_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(path, payload)
    return payload


def refresh_existing_suite(path: Path, suite_name: str) -> dict[str, object]:
    """按原始 settings 重跑单个 suite，并保留其他已完成结果。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format_id") != REPORT_FORMAT_ID:
        raise ValueError("只允许刷新同版本阶段 0 baseline")
    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict):
        raise ValueError("现有 baseline 缺少 settings")
    settings = BenchmarkSettings(
        output_path=path,
        rounds=int(raw_settings.get("rounds") or 5),
        warmup_iterations=int(raw_settings.get("warmup_iterations") or 0),
        inline_iterations=int(raw_settings.get("inline_iterations") or 1),
        large_iterations=int(raw_settings.get("large_iterations") or 1),
        telemetry_iterations=int(raw_settings.get("telemetry_iterations") or 1),
        response_sizes=tuple(
            int(value)
            for value in raw_settings.get("response_sizes", DEFAULT_RESPONSE_SIZES)
        ),
        concurrency=tuple(
            int(value)
            for value in raw_settings.get("concurrency", DEFAULT_CONCURRENCY)
        ),
        seed=int(raw_settings.get("seed") or 20260827),
    )
    suites: dict[str, Callable[[BenchmarkSettings], dict[str, object]]] = {
        "cold": benchmark_cold_open,
        "workflow_trigger": benchmark_trigger,
        "inference": benchmark_inference,
        "training_telemetry": benchmark_telemetry,
        "queue": benchmark_queue,
        "page_geometry": benchmark_page_geometry,
    }
    suite = suites.get(suite_name)
    if suite is None:
        raise ValueError(f"不支持刷新 suite：{suite_name}")
    print(f"START suite={suite_name}", flush=True)
    payload[suite_name] = suite(settings)
    payload["payload_inventory"] = build_payload_inventory()
    payload["observed_local_payload_sizes"] = collect_observed_local_payload_sizes()
    payload["refreshed_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(path, payload)
    print(f"DONE suite={suite_name}", flush=True)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析独立 benchmark 参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup-iterations", type=int, default=10)
    parser.add_argument("--inline-iterations", type=int, default=50)
    parser.add_argument("--large-iterations", type=int, default=3)
    parser.add_argument("--telemetry-iterations", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument(
        "--enrich-existing",
        action="store_true",
        help="只补充已完成报告的 payload corpus 和只读本地长度观测",
    )
    parser.add_argument(
        "--measure-telemetry-scan",
        action="store_true",
        help="补充既有报告时同时运行新 producer scan 延迟矩阵",
    )
    parser.add_argument(
        "--refresh-suite",
        choices=(
            "cold",
            "workflow_trigger",
            "inference",
            "training_telemetry",
            "queue",
            "page_geometry",
        ),
        help="按报告原始 settings 重跑并原子替换指定 suite",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行完整阶段 0 基线并输出摘要。"""

    args = parse_args(argv)
    output_path = args.output.resolve()
    if args.refresh_suite:
        report = refresh_existing_suite(output_path, args.refresh_suite)
        print(
            json.dumps(
                {
                    "format_id": report["format_id"],
                    "output_path": str(output_path),
                    "status": "refreshed",
                    "suite": args.refresh_suite,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.enrich_existing:
        report = enrich_existing_report(
            output_path,
            measure_telemetry_scan=args.measure_telemetry_scan,
        )
        print(
            json.dumps(
                {
                    "format_id": report["format_id"],
                    "output_path": str(output_path),
                    "status": "enriched",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    settings = BenchmarkSettings(
        output_path=output_path,
        rounds=args.rounds,
        warmup_iterations=args.warmup_iterations,
        inline_iterations=args.inline_iterations,
        large_iterations=args.large_iterations,
        telemetry_iterations=args.telemetry_iterations,
        seed=args.seed,
    )
    report = run_benchmark(settings)
    print(
        json.dumps(
            {
                "format_id": report["format_id"],
                "output_path": str(settings.output_path),
                "status": "succeeded",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
