"""Deployment、WorkflowAppRuntime 与 ZeroMQ TriggerSource 持续负载入口。

该工具只使用公开 HTTP API 和 ZeroMQ REQ/REP 协议。运行前应先创建并启动真实
deployment、workflow runtime 和 TriggerSource；工具不隐式创建、重置或停止现场资源。
结果按固定 schema 持续写入 ``result.json``，可直接作为 release/full soak workload。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import platform
import sys
import time
import zlib
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Final
from uuid import uuid4

import httpx

from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)


PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_TOKEN: Final = "amvision-default-user-token"
DEFAULT_OUTPUT_ROOT: Final = PROJECT_ROOT / ".tmp" / "deployment-workflow-trigger-soak"
DEPLOYMENT_TASK_TYPES: Final = (
    "detection",
    "classification",
    "segmentation",
    "pose",
    "obb",
)
DEPLOYMENT_RUNTIME_MODES: Final = ("sync", "async")
TERMINAL_TASK_STATES: Final = {"succeeded", "failed", "cancelled", "timeout"}
MAX_ERROR_EXAMPLES: Final = 20
MAX_LATENCY_SAMPLES: Final = 100_000


@dataclass(frozen=True)
class RuntimeSoakConfig:
    """描述一轮持续负载配置。"""

    base_url: str
    token: str
    project_id: str
    duration_seconds: float
    concurrency_per_lane: int
    request_interval_seconds: float
    sample_interval_seconds: float
    http_timeout_seconds: float
    task_timeout_seconds: float
    async_poll_interval_seconds: float
    max_error_rate: float
    minimum_requests_per_lane: int
    output_dir: Path
    deployment_instance_id: str | None = None
    deployment_runtime_modes: tuple[str, ...] = DEPLOYMENT_RUNTIME_MODES
    deployment_task_type: str = "detection"
    deployment_model_type: str = "yolov8"
    deployment_image_path: Path | None = None
    workflow_runtime_id: str | None = None
    workflow_request: dict[str, object] = field(default_factory=dict)
    workflow_image_path: Path | None = None
    workflow_image_binding_id: str = "request_image_base64"
    trigger_source_id: str | None = None
    trigger_endpoint: str | None = None
    trigger_envelope: dict[str, object] = field(default_factory=dict)
    trigger_binary_path: Path | None = None
    trigger_reply_timeout_seconds: float = 120.0


@dataclass(frozen=True)
class SoakLane:
    """描述一个独立并发负载通道。"""

    name: str
    kind: str


@dataclass
class LaneMetrics:
    """以有界内存记录单条负载通道的计数和延迟。"""

    name: str
    lock: Lock = field(default_factory=Lock)
    started_count: int = 0
    success_count: int = 0
    error_count: int = 0
    inflight_count: int = 0
    max_inflight_count: int = 0
    first_started_at: str | None = None
    last_finished_at: str | None = None
    latency_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=MAX_LATENCY_SAMPLES)
    )
    error_examples: list[dict[str, object]] = field(default_factory=list)

    def begin(self) -> int:
        """登记一次请求开始并返回通道内序号。"""

        with self.lock:
            self.started_count += 1
            self.inflight_count += 1
            self.max_inflight_count = max(self.max_inflight_count, self.inflight_count)
            if self.first_started_at is None:
                self.first_started_at = _utc_now()
            return self.started_count

    def finish(self, *, latency_ms: float, error: Exception | None) -> None:
        """登记一次请求结束。"""

        with self.lock:
            self.inflight_count = max(0, self.inflight_count - 1)
            self.latency_ms.append(max(0.0, float(latency_ms)))
            self.last_finished_at = _utc_now()
            if error is None:
                self.success_count += 1
                return
            self.error_count += 1
            if len(self.error_examples) < MAX_ERROR_EXAMPLES:
                self.error_examples.append(
                    {
                        "occurred_at": self.last_finished_at,
                        "error_type": error.__class__.__name__,
                        "message": str(error),
                    }
                )

    def snapshot(self) -> dict[str, object]:
        """返回可序列化的指标快照。"""

        with self.lock:
            started_count = self.started_count
            success_count = self.success_count
            error_count = self.error_count
            latencies = sorted(self.latency_ms)
            return {
                "name": self.name,
                "started_count": started_count,
                "success_count": success_count,
                "error_count": error_count,
                "error_rate": (
                    round(error_count / started_count, 8) if started_count else 0.0
                ),
                "inflight_count": self.inflight_count,
                "max_inflight_count": self.max_inflight_count,
                "first_started_at": self.first_started_at,
                "last_finished_at": self.last_finished_at,
                "latency_sample_count": len(latencies),
                "latency_ms": {
                    "min": _round_or_none(latencies[0] if latencies else None),
                    "mean": _round_or_none(
                        sum(latencies) / len(latencies) if latencies else None
                    ),
                    "p50": _round_or_none(_percentile(latencies, 0.50)),
                    "p95": _round_or_none(_percentile(latencies, 0.95)),
                    "p99": _round_or_none(_percentile(latencies, 0.99)),
                    "max": _round_or_none(latencies[-1] if latencies else None),
                },
                "error_examples": list(self.error_examples),
            }


class SoakApiClient:
    """封装持续负载使用的公开 REST API。"""

    def __init__(self, config: RuntimeSoakConfig) -> None:
        self.client = httpx.Client(
            base_url=f"{config.base_url.rstrip('/')}/api/v1",
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=httpx.Timeout(config.http_timeout_seconds),
        )

    def close(self) -> None:
        """关闭 HTTP 连接池。"""

        self.client.close()

    def get(self, path: str, **kwargs: Any) -> dict[str, object]:
        """执行 GET 并读取 JSON object。"""

        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> dict[str, object]:
        """执行 POST 并读取 JSON object。"""

        return self._request("POST", path, **kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, object]:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"{method} {path} failed: {response.status_code} {response.text[:1000]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} 未返回 JSON object")
        return payload


class ZeroMqSoakClient:
    """维护一个可在请求失败后重建的 ZeroMQ REQ client。"""

    def __init__(self, *, endpoint: str, timeout_seconds: float) -> None:
        try:
            import zmq
        except ImportError as error:  # pragma: no cover - 由部署环境决定
            raise RuntimeError("TriggerSource soak 需要 pyzmq") from error
        self.zmq = zmq
        self.endpoint = endpoint
        self.timeout_ms = max(1, int(timeout_seconds * 1000))
        self.context = zmq.Context.instance()
        self.socket: Any = None
        self._open_socket()

    def close(self) -> None:
        """关闭当前 REQ socket。"""

        if self.socket is not None:
            self.socket.close(linger=0)
            self.socket = None

    def send(self, frames: list[bytes]) -> dict[str, object]:
        """发送 multipart 请求并严格校验统一 Result v1 reply。"""

        try:
            self.socket.send_multipart(frames)
            reply_frames = self.socket.recv_multipart()
            return _parse_zeromq_result_frames(reply_frames)
        except Exception:
            self.close()
            self._open_socket()
            raise

    def _open_socket(self) -> None:
        socket = self.context.socket(self.zmq.REQ)
        socket.linger = 0
        socket.rcvtimeo = self.timeout_ms
        socket.sndtimeo = self.timeout_ms
        socket.connect(self.endpoint)
        self.socket = socket


def _parse_zeromq_result_frames(reply_frames: list[bytes]) -> dict[str, object]:
    """校验统一 Result v1 manifest、逻辑 attachment 和去重后的物理帧。"""

    if not reply_frames:
        raise RuntimeError("ZeroMQ reply 不能为空")
    try:
        payload = json.loads(reply_frames[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("ZeroMQ reply Frame 0 不是合法 UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("ZeroMQ reply Frame 0 必须是 JSON object")
    if payload.get("format_id") != "amvision.workflow-trigger-result.v1":
        raise RuntimeError("ZeroMQ reply format_id 不正确")

    response_payload = payload.get("response_payload")
    if not isinstance(response_payload, dict):
        raise RuntimeError("ZeroMQ reply response_payload 必须是 JSON object")
    raw_attachments = response_payload.get("attachments", [])
    raw_payloads = response_payload.get("payloads", [])
    if not isinstance(raw_attachments, list) or not isinstance(raw_payloads, list):
        raise RuntimeError("ZeroMQ reply attachments/payloads 必须是 JSON array")

    physical_by_id: dict[str, dict[str, object]] = {}
    declared_indexes: set[int] = set()
    for raw_physical in raw_payloads:
        if not isinstance(raw_physical, dict):
            raise RuntimeError("ZeroMQ reply physical payload 必须是 JSON object")
        payload_id = str(raw_physical.get("payload_id") or "").strip()
        if not payload_id or payload_id in physical_by_id:
            raise RuntimeError("ZeroMQ reply payload_id 不能为空或重复")
        if raw_physical.get("delivery_kind") != "zeromq-frame":
            raise RuntimeError("ZeroMQ reply physical payload 必须使用 zeromq-frame")
        frame_index = raw_physical.get("frame_index")
        if (
            isinstance(frame_index, bool)
            or not isinstance(frame_index, int)
            or frame_index <= 0
            or frame_index >= len(reply_frames)
            or frame_index in declared_indexes
        ):
            raise RuntimeError("ZeroMQ reply frame_index 越界或重复")
        content = reply_frames[frame_index]
        content_length = raw_physical.get("content_length")
        if (
            isinstance(content_length, bool)
            or not isinstance(content_length, int)
            or content_length <= 0
            or content_length != len(content)
        ):
            raise RuntimeError("ZeroMQ reply frame content_length 不一致")
        _verify_zeromq_frame_checksum(raw_physical, content)
        declared_indexes.add(frame_index)
        physical_by_id[payload_id] = raw_physical

    expected_indexes = set(range(1, len(reply_frames)))
    if declared_indexes != expected_indexes:
        raise RuntimeError("ZeroMQ reply 存在缺失或未声明的二进制帧")
    if not physical_by_id and raw_attachments:
        raise RuntimeError("ZeroMQ reply attachment 没有对应 physical payload")
    if physical_by_id and not raw_attachments:
        raise RuntimeError("ZeroMQ reply physical payload 没有 logical attachment")

    attachment_ids: set[str] = set()
    referenced_payload_ids: set[str] = set()
    for raw_attachment in raw_attachments:
        if not isinstance(raw_attachment, dict):
            raise RuntimeError("ZeroMQ reply attachment 必须是 JSON object")
        attachment_id = str(raw_attachment.get("attachment_id") or "").strip()
        binding_id = str(raw_attachment.get("binding_id") or "").strip()
        payload_id = str(raw_attachment.get("payload_id") or "").strip()
        item_index = raw_attachment.get("item_index")
        if (
            not attachment_id
            or attachment_id in attachment_ids
            or not binding_id
            or isinstance(item_index, bool)
            or not isinstance(item_index, int)
            or item_index < 0
            or payload_id not in physical_by_id
        ):
            raise RuntimeError("ZeroMQ reply logical attachment 不完整或引用无效")
        attachment_ids.add(attachment_id)
        referenced_payload_ids.add(payload_id)
    if referenced_payload_ids != set(physical_by_id):
        raise RuntimeError("ZeroMQ reply 存在未引用的 physical payload")

    state = str(payload.get("state") or "").lower()
    if state in {"failed", "timed_out", "timeout", "cancelled"}:
        raise RuntimeError(
            "ZeroMQ trigger failed: "
            f"{payload.get('error_code') or payload.get('error_message') or state}"
        )
    return payload


def _verify_zeromq_frame_checksum(
    physical: dict[str, object],
    content: bytes,
) -> None:
    """按 manifest 声明验证单个物理图片帧的 checksum。"""

    algorithm = str(physical.get("checksum_algorithm") or "").lower()
    expected = str(physical.get("checksum") or "").lower()
    if algorithm == "crc32":
        actual = f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"
    elif algorithm == "sha256":
        actual = hashlib.sha256(content).hexdigest()
    else:
        raise RuntimeError("ZeroMQ reply 使用了不支持的 checksum_algorithm")
    if not expected or actual != expected:
        raise RuntimeError("ZeroMQ reply frame checksum 不一致")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析持续负载命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "AMVISION_RELEASE_FULL_BASE_URL", "http://127.0.0.1:5600"
        ),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AMVISION_RUNTIME_SOAK_TOKEN", DEFAULT_TOKEN),
    )
    parser.add_argument("--project-id", default="project-1")
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=float(os.environ.get("AMVISION_RUNTIME_SOAK_SECONDS", "3600")),
    )
    parser.add_argument("--concurrency-per-lane", type=int, default=1)
    parser.add_argument("--request-interval-ms", type=float, default=0.0)
    parser.add_argument("--sample-interval-seconds", type=float, default=10.0)
    parser.add_argument("--http-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--task-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--async-poll-interval-seconds", type=float, default=0.2)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--minimum-requests-per-lane", type=int, default=1)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", type=Path)

    parser.add_argument("--deployment-instance-id")
    parser.add_argument(
        "--deployment-runtime-modes",
        nargs="+",
        choices=DEPLOYMENT_RUNTIME_MODES,
        default=DEPLOYMENT_RUNTIME_MODES,
        help="要施加负载的 deployment runtime；默认同时覆盖 sync 和 async",
    )
    parser.add_argument(
        "--deployment-task-type", choices=DEPLOYMENT_TASK_TYPES, default="detection"
    )
    parser.add_argument("--deployment-model-type", default="yolov8")
    parser.add_argument("--deployment-image", type=Path)

    parser.add_argument("--workflow-runtime-id")
    parser.add_argument("--workflow-request-json", type=Path)
    parser.add_argument(
        "--workflow-image",
        type=Path,
        help="每次 HTTP Workflow 调用都编码为 image-base64.v1 的真实图片",
    )
    parser.add_argument(
        "--workflow-image-binding-id",
        default="request_image_base64",
        help="接收 image-base64.v1 的公开输入 id",
    )

    parser.add_argument("--trigger-source-id")
    parser.add_argument("--trigger-endpoint")
    parser.add_argument("--trigger-envelope-json", type=Path)
    parser.add_argument("--trigger-binary", type=Path)
    parser.add_argument("--trigger-reply-timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)

    if args.duration_seconds <= 0:
        parser.error("duration-seconds 必须大于 0")
    if args.concurrency_per_lane < 1:
        parser.error("concurrency-per-lane 必须大于 0")
    if args.request_interval_ms < 0:
        parser.error("request-interval-ms 不能小于 0")
    if args.sample_interval_seconds <= 0:
        parser.error("sample-interval-seconds 必须大于 0")
    if args.http_timeout_seconds <= 0 or args.task_timeout_seconds <= 0:
        parser.error("HTTP 和 task timeout 必须大于 0")
    if args.async_poll_interval_seconds <= 0:
        parser.error("async-poll-interval-seconds 必须大于 0")
    if args.trigger_reply_timeout_seconds <= 0:
        parser.error("trigger-reply-timeout-seconds 必须大于 0")
    if not 0.0 <= args.max_error_rate <= 1.0:
        parser.error("max-error-rate 必须位于 0 和 1 之间")
    if args.minimum_requests_per_lane < 1:
        parser.error("minimum-requests-per-lane 必须大于 0")
    if args.deployment_instance_id and args.deployment_image is None:
        parser.error("配置 deployment soak 时必须提供 --deployment-image")
    if args.deployment_image is not None and not args.deployment_instance_id:
        parser.error("--deployment-image 必须和 --deployment-instance-id 一起使用")
    if args.workflow_runtime_id and args.workflow_image is None:
        parser.error("配置 workflow runtime soak 时必须提供 --workflow-image")
    if args.workflow_image is not None and not args.workflow_runtime_id:
        parser.error("--workflow-image 必须和 --workflow-runtime-id 一起使用")
    if not str(args.workflow_image_binding_id).strip():
        parser.error("workflow-image-binding-id 不能为空")
    if args.trigger_endpoint and not args.trigger_source_id:
        parser.error("--trigger-endpoint 必须和 --trigger-source-id 一起使用")
    if not any(
        (
            args.deployment_instance_id,
            args.workflow_runtime_id,
            args.trigger_source_id,
        )
    ):
        parser.error("至少配置 deployment、workflow runtime 或 TriggerSource 之一")
    return args


def build_config(args: argparse.Namespace) -> RuntimeSoakConfig:
    """从已校验的 CLI 参数构造不可变配置。"""

    run_id = args.run_id or datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else (DEFAULT_OUTPUT_ROOT / run_id).resolve()
    )
    deployment_image_path = _resolve_existing_file(
        args.deployment_image, "deployment image"
    )
    trigger_binary_path = _resolve_existing_file(args.trigger_binary, "trigger binary")
    workflow_image_path = _resolve_existing_file(
        args.workflow_image, "workflow image"
    )
    return RuntimeSoakConfig(
        base_url=str(args.base_url).rstrip("/"),
        token=str(args.token),
        project_id=str(args.project_id),
        duration_seconds=float(args.duration_seconds),
        concurrency_per_lane=int(args.concurrency_per_lane),
        request_interval_seconds=float(args.request_interval_ms) / 1000.0,
        sample_interval_seconds=float(args.sample_interval_seconds),
        http_timeout_seconds=float(args.http_timeout_seconds),
        task_timeout_seconds=float(args.task_timeout_seconds),
        async_poll_interval_seconds=float(args.async_poll_interval_seconds),
        max_error_rate=float(args.max_error_rate),
        minimum_requests_per_lane=int(args.minimum_requests_per_lane),
        output_dir=output_dir,
        deployment_instance_id=_optional_text(args.deployment_instance_id),
        deployment_runtime_modes=tuple(dict.fromkeys(args.deployment_runtime_modes)),
        deployment_task_type=str(args.deployment_task_type),
        deployment_model_type=str(args.deployment_model_type),
        deployment_image_path=deployment_image_path,
        workflow_runtime_id=_optional_text(args.workflow_runtime_id),
        workflow_request=_load_json_object(
            args.workflow_request_json, label="workflow request"
        ),
        workflow_image_path=workflow_image_path,
        workflow_image_binding_id=str(args.workflow_image_binding_id).strip(),
        trigger_source_id=_optional_text(args.trigger_source_id),
        trigger_endpoint=_optional_text(args.trigger_endpoint),
        trigger_envelope=_load_json_object(
            args.trigger_envelope_json, label="trigger envelope"
        ),
        trigger_binary_path=trigger_binary_path,
        trigger_reply_timeout_seconds=float(args.trigger_reply_timeout_seconds),
    )


def build_lanes(config: RuntimeSoakConfig) -> tuple[SoakLane, ...]:
    """按已配置资源构造独立负载通道。"""

    lanes: list[SoakLane] = []
    if config.deployment_instance_id is not None:
        lanes.extend(
            SoakLane(
                name=f"deployment-{runtime_mode}",
                kind=f"deployment-{runtime_mode}",
            )
            for runtime_mode in config.deployment_runtime_modes
        )
    if config.workflow_runtime_id is not None:
        lanes.append(SoakLane(name="workflow-invoke", kind="workflow-invoke"))
    if config.trigger_source_id is not None:
        lanes.append(SoakLane(name="trigger-zeromq", kind="trigger-zeromq"))
    return tuple(lanes)


def run_soak(config: RuntimeSoakConfig) -> int:
    """执行一轮持续负载并返回进程退出码。"""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = config.output_dir / "result.json"
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    lanes = build_lanes(config)
    metrics = {lane.name: LaneMetrics(name=lane.name) for lane in lanes}
    health_samples: list[dict[str, object]] = []
    monitor_errors: list[dict[str, object]] = []
    stop_event = Event()
    futures: list[Future[None]] = []
    resolved_config = config
    status = "running"

    try:
        with _api_client(config) as api_client:
            resolved_config, preflight = run_preflight(config, api_client)
        _write_json_atomically(config.output_dir / "preflight.json", preflight)

        # 预检可能包含 runtime 恢复或较慢的控制面调用；持续时长只计算正式负载阶段。
        deadline = time.monotonic() + config.duration_seconds
        worker_count = max(1, len(lanes) * config.concurrency_per_lane)
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="runtime-soak",
        ) as executor:
            for lane in lanes:
                for worker_index in range(config.concurrency_per_lane):
                    futures.append(
                        executor.submit(
                            _run_lane_worker,
                            lane=lane,
                            worker_index=worker_index,
                            config=resolved_config,
                            metrics=metrics[lane.name],
                            stop_event=stop_event,
                            deadline=deadline,
                        )
                    )

            next_sample_at = time.monotonic()
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_sample_at:
                    health_samples.append(
                        _collect_health_sample(
                            config=resolved_config,
                            elapsed_seconds=now - started_monotonic,
                            monitor_errors=monitor_errors,
                        )
                    )
                    _write_json_atomically(
                        result_path,
                        _build_result(
                            config=resolved_config,
                            status="running",
                            started_at=started_at,
                            started_monotonic=started_monotonic,
                            metrics=metrics,
                            health_samples=health_samples,
                            monitor_errors=monitor_errors,
                        ),
                    )
                    next_sample_at = now + config.sample_interval_seconds
                stop_event.wait(min(0.2, max(0.0, deadline - now)))

            stop_event.set()
            for future in futures:
                future.result(timeout=max(5.0, config.http_timeout_seconds + 5.0))

        health_samples.append(
            _collect_health_sample(
                config=resolved_config,
                elapsed_seconds=time.monotonic() - started_monotonic,
                monitor_errors=monitor_errors,
            )
        )
        failures = _evaluate_result(
            config=resolved_config,
            metrics=metrics,
            monitor_errors=monitor_errors,
        )
        status = "succeeded" if not failures else "failed"
        result = _build_result(
            config=resolved_config,
            status=status,
            started_at=started_at,
            started_monotonic=started_monotonic,
            metrics=metrics,
            health_samples=health_samples,
            monitor_errors=monitor_errors,
            failures=failures,
        )
        _write_json_atomically(result_path, result)
        print(
            json.dumps(
                _build_console_summary(result=result, result_path=result_path),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if status == "succeeded" else 1
    except KeyboardInterrupt:
        status = "cancelled"
        stop_event.set()
        result = _build_result(
            config=resolved_config,
            status=status,
            started_at=started_at,
            started_monotonic=started_monotonic,
            metrics=metrics,
            health_samples=health_samples,
            monitor_errors=monitor_errors,
            failures=["用户中断持续负载"],
        )
        _write_json_atomically(result_path, result)
        return 130
    except Exception as error:
        stop_event.set()
        result = _build_result(
            config=resolved_config,
            status="failed",
            started_at=started_at,
            started_monotonic=started_monotonic,
            metrics=metrics,
            health_samples=health_samples,
            monitor_errors=monitor_errors,
            failures=[f"{error.__class__.__name__}: {error}"],
        )
        _write_json_atomically(result_path, result)
        print(
            json.dumps(
                _build_console_summary(result=result, result_path=result_path),
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


def _build_console_summary(
    *,
    result: dict[str, object],
    result_path: Path,
) -> dict[str, object]:
    """构建有界控制台摘要，完整健康样本只保留在结果文件中。"""

    lanes = result.get("lanes")
    lane_summary: dict[str, object] = {}
    if isinstance(lanes, dict):
        for lane_name, lane_payload in lanes.items():
            if not isinstance(lane_payload, dict):
                continue
            lane_summary[str(lane_name)] = {
                key: lane_payload.get(key)
                for key in (
                    "started_count",
                    "success_count",
                    "error_count",
                    "error_rate",
                    "max_inflight_count",
                    "latency_ms",
                )
            }
    health_samples = result.get("health_samples")
    monitor_errors = result.get("monitor_errors")
    return {
        "status": result.get("status"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "result_path": str(result_path),
        "lanes": lane_summary,
        "health_sample_count": (
            len(health_samples) if isinstance(health_samples, list) else 0
        ),
        "monitor_error_count": (
            len(monitor_errors) if isinstance(monitor_errors, list) else 0
        ),
        "failures": result.get("failures", []),
    }


def run_preflight(
    config: RuntimeSoakConfig,
    api_client: SoakApiClient,
) -> tuple[RuntimeSoakConfig, dict[str, object]]:
    """确认资源已具备稳定负载条件，并解析 TriggerSource endpoint。"""

    preflight: dict[str, object] = {
        "checked_at": _utc_now(),
        "system_health": api_client.get("/system/health"),
    }
    if config.deployment_instance_id is not None:
        deployment_status: dict[str, object] = {}
        for runtime_mode in config.deployment_runtime_modes:
            payload = api_client.get(
                _deployment_runtime_path(config, runtime_mode, "health")
            )
            _require_running_state(payload, f"deployment {runtime_mode}")
            _require_deployment_soak_ready(payload, f"deployment {runtime_mode}")
            deployment_status[runtime_mode] = payload
        preflight["deployment"] = deployment_status

    if config.workflow_runtime_id is not None:
        workflow_health = api_client.get(
            f"/workflows/app-runtimes/{config.workflow_runtime_id}/health"
        )
        _require_running_state(workflow_health, "workflow runtime")
        preflight["workflow_runtime"] = workflow_health

    resolved_config = config
    if config.trigger_source_id is not None:
        trigger_source = api_client.get(
            f"/workflows/trigger-sources/{config.trigger_source_id}"
        )
        if str(trigger_source.get("trigger_kind")) != "zeromq-topic":
            raise RuntimeError("持续 trigger 负载当前只支持 zeromq-topic")
        endpoint = config.trigger_endpoint or _read_trigger_endpoint(trigger_source)
        if endpoint.startswith("inproc://"):
            raise RuntimeError("外部 soak 进程不能连接 inproc:// TriggerSource")
        trigger_health = api_client.get(
            f"/workflows/trigger-sources/{config.trigger_source_id}/health"
        )
        _require_running_state(trigger_health, "TriggerSource")
        health_summary = trigger_health.get("health_summary")
        if isinstance(health_summary, dict) and not bool(
            health_summary.get("adapter_running")
        ):
            raise RuntimeError("TriggerSource adapter_running 不是 true")
        preflight["trigger_source"] = trigger_health
        preflight["trigger_endpoint"] = endpoint
        resolved_config = replace(config, trigger_endpoint=endpoint)
    return resolved_config, preflight


def _run_lane_worker(
    *,
    lane: SoakLane,
    worker_index: int,
    config: RuntimeSoakConfig,
    metrics: LaneMetrics,
    stop_event: Event,
    deadline: float,
) -> None:
    """持续执行一个通道，错误计入指标后继续下一次请求。"""

    if lane.kind == "trigger-zeromq":
        _run_trigger_lane(
            config=config,
            metrics=metrics,
            worker_index=worker_index,
            stop_event=stop_event,
            deadline=deadline,
        )
        return

    with _api_client(config) as api_client:
        image_bytes = (
            config.deployment_image_path.read_bytes()
            if config.deployment_image_path is not None
            else None
        )
        workflow_image_bytes = (
            config.workflow_image_path.read_bytes()
            if config.workflow_image_path is not None
            else None
        )

        def operation(sequence: int) -> None:
            if lane.kind == "deployment-sync":
                _execute_deployment_sync(
                    config=config,
                    api_client=api_client,
                    image_bytes=_require_bytes(image_bytes, lane.name),
                )
            elif lane.kind == "deployment-async":
                _execute_deployment_async(
                    config=config,
                    api_client=api_client,
                    image_bytes=_require_bytes(image_bytes, lane.name),
                )
            elif lane.kind == "workflow-invoke":
                _execute_workflow_invoke(
                    config=config,
                    api_client=api_client,
                    sequence=sequence,
                    worker_index=worker_index,
                    image_bytes=_require_bytes(workflow_image_bytes, lane.name),
                )
            else:  # pragma: no cover - build_lanes 保证 kind
                raise RuntimeError(f"未知 soak lane: {lane.kind}")

        _run_operation_loop(
            operation=operation,
            config=config,
            metrics=metrics,
            stop_event=stop_event,
            deadline=deadline,
        )


def _run_trigger_lane(
    *,
    config: RuntimeSoakConfig,
    metrics: LaneMetrics,
    worker_index: int,
    stop_event: Event,
    deadline: float,
) -> None:
    endpoint = config.trigger_endpoint
    if endpoint is None:
        raise RuntimeError("TriggerSource endpoint 未解析")
    client = ZeroMqSoakClient(
        endpoint=endpoint,
        timeout_seconds=config.trigger_reply_timeout_seconds,
    )
    binary_content = (
        config.trigger_binary_path.read_bytes()
        if config.trigger_binary_path is not None
        else None
    )
    try:

        def operation(sequence: int) -> None:
            envelope = dict(config.trigger_envelope)
            envelope["trigger_source_id"] = config.trigger_source_id
            envelope["event_id"] = f"soak-{worker_index}-{sequence}-{uuid4().hex[:12]}"
            envelope.setdefault("trace_id", f"soak-{uuid4().hex}")
            if binary_content is not None:
                envelope.setdefault(
                    "media_type", _resolve_media_type(config.trigger_binary_path)
                )
            frames = [json.dumps(envelope, ensure_ascii=False).encode()]
            if binary_content is not None:
                frames.append(binary_content)
            client.send(frames)

        _run_operation_loop(
            operation=operation,
            config=config,
            metrics=metrics,
            stop_event=stop_event,
            deadline=deadline,
        )
    finally:
        client.close()


def _run_operation_loop(
    *,
    operation: Callable[[int], None],
    config: RuntimeSoakConfig,
    metrics: LaneMetrics,
    stop_event: Event,
    deadline: float,
) -> None:
    """执行单通道循环并统一计时、记错和限速。"""

    while not stop_event.is_set() and time.monotonic() < deadline:
        sequence = metrics.begin()
        request_started_at = time.monotonic()
        error: Exception | None = None
        try:
            operation(sequence)
        except Exception as caught_error:  # noqa: BLE001 - soak 必须累计全部错误。
            error = caught_error
        metrics.finish(
            latency_ms=(time.monotonic() - request_started_at) * 1000.0,
            error=error,
        )
        if config.request_interval_seconds > 0:
            stop_event.wait(config.request_interval_seconds)


def _execute_deployment_sync(
    *,
    config: RuntimeSoakConfig,
    api_client: SoakApiClient,
    image_bytes: bytes,
) -> None:
    response = api_client.post(
        (
            f"/models/{config.deployment_task_type}/deployment-instances/"
            f"{config.deployment_instance_id}/infer"
        ),
        data=_build_inference_form(config=config, async_request=False),
        files={"input_image": _build_image_file(config, image_bytes)},
    )
    _reject_failed_payload(response, "deployment sync")


def _execute_deployment_async(
    *,
    config: RuntimeSoakConfig,
    api_client: SoakApiClient,
    image_bytes: bytes,
) -> None:
    submission = api_client.post(
        f"/models/{config.deployment_task_type}/inference-tasks",
        data={
            "project_id": config.project_id,
            "deployment_instance_id": config.deployment_instance_id,
            **_build_inference_form(config=config, async_request=True),
        },
        files={"input_image": _build_image_file(config, image_bytes)},
    )
    task_id = _require_payload_text(submission, "task_id")
    deadline = time.monotonic() + config.task_timeout_seconds
    while True:
        detail = api_client.get(
            f"/models/{config.deployment_task_type}/inference-tasks/{task_id}"
        )
        state = str(detail.get("state") or detail.get("status") or "").lower()
        if state == "succeeded":
            break
        if state in TERMINAL_TASK_STATES:
            raise RuntimeError(f"deployment async task {task_id} ended in {state}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"deployment async task {task_id} 等待超时")
        time.sleep(config.async_poll_interval_seconds)
    result = api_client.get(
        f"/models/{config.deployment_task_type}/inference-tasks/{task_id}/result"
    )
    _reject_failed_payload(result, "deployment async result")


def _execute_workflow_invoke(
    *,
    config: RuntimeSoakConfig,
    api_client: SoakApiClient,
    sequence: int,
    worker_index: int,
    image_bytes: bytes,
) -> None:
    request = json.loads(json.dumps(config.workflow_request))
    _inject_workflow_image_base64(
        request=request,
        binding_id=config.workflow_image_binding_id,
        image_bytes=image_bytes,
        media_type=_resolve_media_type(config.workflow_image_path),
    )
    execution_metadata = request.get("execution_metadata")
    if not isinstance(execution_metadata, dict):
        execution_metadata = {}
        request["execution_metadata"] = execution_metadata
    execution_metadata.update(
        {
            "scenario": "deployment-workflow-trigger-soak",
            "soak_sequence": sequence,
            "soak_worker_index": worker_index,
        }
    )
    response = api_client.post(
        f"/workflows/app-runtimes/{config.workflow_runtime_id}/invoke",
        params={"response_mode": "run"},
        json=request,
    )
    state = str(response.get("state") or "").lower()
    if state != "succeeded":
        error_message = response.get("error_message") or response.get("message")
        error_details = response.get("error_details")
        details_text = (
            json.dumps(error_details, ensure_ascii=False, sort_keys=True)[:2000]
            if error_details is not None
            else ""
        )
        raise RuntimeError(
            "workflow invoke 未成功: "
            f"state={state or 'missing'}, error={error_message or 'missing'}, "
            f"details={details_text or 'missing'}"
        )


def _collect_health_sample(
    *,
    config: RuntimeSoakConfig,
    elapsed_seconds: float,
    monitor_errors: list[dict[str, object]],
) -> dict[str, object]:
    """采集 system/deployment/workflow/trigger 控制面状态。"""

    sample: dict[str, object] = {
        "sampled_at": _utc_now(),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
    }
    try:
        with _api_client(config) as api_client:
            sample["system_health"] = api_client.get("/system/health")
            if config.deployment_instance_id is not None:
                deployment_health: dict[str, object] = {}
                for runtime_mode in config.deployment_runtime_modes:
                    payload = api_client.get(
                        _deployment_runtime_path(config, runtime_mode, "health")
                    )
                    _require_running_state(payload, f"deployment {runtime_mode}")
                    _require_deployment_soak_ready(
                        payload, f"deployment {runtime_mode}"
                    )
                    deployment_health[runtime_mode] = payload
                sample["deployment"] = deployment_health
            if config.workflow_runtime_id is not None:
                sample["workflow_runtime"] = api_client.get(
                    f"/workflows/app-runtimes/{config.workflow_runtime_id}/health"
                )
            if config.trigger_source_id is not None:
                sample["trigger_source"] = api_client.get(
                    f"/workflows/trigger-sources/{config.trigger_source_id}/health"
                )
    except Exception as error:  # noqa: BLE001 - 采样错误需要进入最终门禁。
        entry = {
            "occurred_at": _utc_now(),
            "error_type": error.__class__.__name__,
            "message": str(error),
        }
        sample["error"] = entry
        monitor_errors.append(entry)
    return sample


def _evaluate_result(
    *,
    config: RuntimeSoakConfig,
    metrics: dict[str, LaneMetrics],
    monitor_errors: list[dict[str, object]],
) -> list[str]:
    """按最小请求量、错误率和控制面采样生成失败原因。"""

    failures: list[str] = []
    for lane_name, lane_metrics in metrics.items():
        snapshot = lane_metrics.snapshot()
        started_count = int(snapshot["started_count"])
        error_rate = float(snapshot["error_rate"])
        if started_count < config.minimum_requests_per_lane:
            failures.append(
                f"{lane_name} 请求数不足: {started_count} < "
                f"{config.minimum_requests_per_lane}"
            )
        if error_rate > config.max_error_rate:
            failures.append(
                f"{lane_name} 错误率超限: {error_rate:.8f} > "
                f"{config.max_error_rate:.8f}"
            )
    if monitor_errors:
        failures.append(f"控制面健康采样失败 {len(monitor_errors)} 次")
    return failures


def _build_result(
    *,
    config: RuntimeSoakConfig,
    status: str,
    started_at: str,
    started_monotonic: float,
    metrics: dict[str, LaneMetrics],
    health_samples: list[dict[str, object]],
    monitor_errors: list[dict[str, object]],
    failures: list[str] | None = None,
) -> dict[str, object]:
    """构造持续负载结果文档。"""

    return {
        "contract_version": 1,
        "status": status,
        "started_at": started_at,
        "updated_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "configured_duration_seconds": config.duration_seconds,
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "process_id": os.getpid(),
        },
        "config": {
            "base_url": config.base_url,
            "project_id": config.project_id,
            "concurrency_per_lane": config.concurrency_per_lane,
            "request_interval_seconds": config.request_interval_seconds,
            "sample_interval_seconds": config.sample_interval_seconds,
            "max_error_rate": config.max_error_rate,
            "minimum_requests_per_lane": config.minimum_requests_per_lane,
            "deployment_instance_id": config.deployment_instance_id,
            "deployment_runtime_modes": list(config.deployment_runtime_modes),
            "deployment_task_type": config.deployment_task_type,
            "deployment_model_type": config.deployment_model_type,
            "deployment_image_path": (
                str(config.deployment_image_path)
                if config.deployment_image_path is not None
                else None
            ),
            "workflow_runtime_id": config.workflow_runtime_id,
            "workflow_input_transport": (
                "inline-base64" if config.workflow_runtime_id is not None else None
            ),
            "workflow_image_binding_id": config.workflow_image_binding_id,
            "workflow_image_path": (
                str(config.workflow_image_path)
                if config.workflow_image_path is not None
                else None
            ),
            "trigger_source_id": config.trigger_source_id,
            "trigger_endpoint": config.trigger_endpoint,
            "trigger_binary_path": (
                str(config.trigger_binary_path)
                if config.trigger_binary_path is not None
                else None
            ),
        },
        "lanes": {
            lane_name: lane_metrics.snapshot()
            for lane_name, lane_metrics in metrics.items()
        },
        "health_samples": health_samples,
        "monitor_errors": monitor_errors,
        "failures": failures or [],
    }


def _build_inference_form(
    *, config: RuntimeSoakConfig, async_request: bool
) -> dict[str, str]:
    payload = {
        "model_type": config.deployment_model_type,
        "input_transport_mode": "storage",
        "save_result_image": "false",
        "return_preview_image_base64": "false",
        "extra_options": "{}",
    }
    if async_request:
        payload["display_name"] = "runtime soak inference"
    if config.deployment_task_type == "classification":
        payload["top_k"] = "5"
    elif config.deployment_task_type == "segmentation":
        payload["score_threshold"] = "0.25"
        payload["mask_threshold"] = "0.5"
    else:
        payload["score_threshold"] = "0.25"
    return payload


def _build_image_file(
    config: RuntimeSoakConfig, image_bytes: bytes
) -> tuple[str, bytes, str]:
    path = config.deployment_image_path
    if path is None:
        raise RuntimeError("deployment image 未配置")
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return path.name, image_bytes, media_type


def _inject_workflow_image_base64(
    *,
    request: dict[str, object],
    binding_id: str,
    image_bytes: bytes,
    media_type: str,
) -> None:
    """把相机图片编码为公开 image-base64.v1 输入并移除默认路径引用。"""

    normalized_binding_id = binding_id.strip()
    if not normalized_binding_id:
        raise RuntimeError("workflow image binding id 不能为空")
    payload = {
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "media_type": media_type,
    }
    wrapped_bindings = request.get("input_bindings")
    if isinstance(wrapped_bindings, dict):
        wrapped_bindings.pop("request_image_ref", None)
        wrapped_bindings[normalized_binding_id] = payload
        return
    request.pop("request_image_ref", None)
    request[normalized_binding_id] = payload


def _deployment_runtime_path(
    config: RuntimeSoakConfig, runtime_mode: str, action: str
) -> str:
    return (
        f"/models/{config.deployment_task_type}/deployment-instances/"
        f"{config.deployment_instance_id}/{runtime_mode}/{action}"
    )


def _require_running_state(payload: dict[str, object], label: str) -> None:
    states = {
        str(payload.get("process_state") or "").lower(),
        str(payload.get("observed_state") or "").lower(),
        str(payload.get("state") or "").lower(),
    }
    if "running" not in states:
        raise RuntimeError(f"{label} 未运行: states={sorted(states)}")


def _require_deployment_soak_ready(
    payload: dict[str, object], label: str
) -> None:
    """要求 Deployment 全部实例健康且完成预热，避免把冷启动计入 soak。"""

    instance_count = _read_non_negative_int(payload, "instance_count", label)
    healthy_count = _read_non_negative_int(
        payload, "healthy_instance_count", label
    )
    warmed_count = _read_non_negative_int(payload, "warmed_instance_count", label)
    if (
        instance_count <= 0
        or healthy_count != instance_count
        or warmed_count != instance_count
    ):
        raise RuntimeError(
            f"{label} 尚未完成全部实例预热: "
            f"instance_count={instance_count}, "
            f"healthy_instance_count={healthy_count}, "
            f"warmed_instance_count={warmed_count}"
        )


def _read_non_negative_int(
    payload: dict[str, object], key: str, label: str
) -> int:
    """读取健康响应中的非负整数计数。"""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"{label} 缺少合法的 {key}: {value!r}")
    return value


def _reject_failed_payload(payload: dict[str, object], label: str) -> None:
    state = str(payload.get("state") or payload.get("status") or "").lower()
    if state in {"failed", "timed_out", "timeout", "cancelled"}:
        raise RuntimeError(f"{label} 返回失败状态: {state}")


def _read_trigger_endpoint(payload: dict[str, object]) -> str:
    transport_config = payload.get("transport_config")
    if not isinstance(transport_config, dict):
        raise RuntimeError("TriggerSource 缺少 transport_config")
    endpoint = transport_config.get("bind_endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise RuntimeError("TriggerSource 缺少 bind_endpoint")
    return endpoint.strip()


def _require_payload_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"响应缺少 {key}")
    return value.strip()


def _require_bytes(content: bytes | None, label: str) -> bytes:
    if content is None:
        raise RuntimeError(f"{label} 缺少输入图片")
    return content


def _resolve_existing_file(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} 不存在: {resolved}")
    return resolved


def _resolve_media_type(path: Path | None) -> str:
    """按图片文件扩展名推导常见 media type。"""

    suffix = path.suffix.lower() if path is not None else ""
    if suffix == ".png":
        return "image/png"
    if suffix == ".bmp":
        return "image/bmp"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


def _load_json_object(path: Path | None, *, label: str) -> dict[str, object]:
    if path is None:
        return {}
    resolved = _resolve_existing_file(path, label)
    assert resolved is not None
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 必须是 JSON object")
    return payload


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * ratio
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return values[lower_index]
    weight = position - lower_index
    return values[lower_index] * (1.0 - weight) + values[upper_index] * weight


def _round_or_none(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _write_json_atomically(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex[:12]}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        replace_path_with_retry(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


class _ApiClientContext:
    """让 SoakApiClient 支持局部 context manager。"""

    def __init__(self, config: RuntimeSoakConfig) -> None:
        self.api_client = SoakApiClient(config)

    def __enter__(self) -> SoakApiClient:
        return self.api_client

    def __exit__(self, *_args: object) -> None:
        self.api_client.close()


def _api_client(config: RuntimeSoakConfig) -> _ApiClientContext:
    return _ApiClientContext(config)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""

    return run_soak(build_config(parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
