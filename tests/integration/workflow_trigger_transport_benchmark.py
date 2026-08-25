"""ZeroMQ 与 local-shared-memory Workflow Trigger 真实性能验收工具。

工具只读取已启动的 TriggerSource/Runtime，并由仓库内 net472 SDK 在长期复用的
client 中执行调用；不会隐式创建、切版、启动、停止或删除业务资源。配置中的两组
TriggerSource 按索引成对绑定同一个 Workflow Runtime，从而保持图、模型和数据一致。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import httpx

from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)


ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_TOKEN: Final = "amvision-default-user-token"
DOTNET_PROJECT: Final = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "Amvar.Vision.ContractTests.vs2019.net472.csproj"
)
DOTNET_PROBE: Final = (
    DOTNET_PROJECT.parent / "bin" / "Release" / "net472" / "Amvar.Vision.ContractTests.exe"
)
SUPPORTED_MODES: Final = {
    "bgr24",
    "bgr24-direct",
    "encoded-bytes",
    "encoded-file",
    "base64",
}
LIFECYCLE_GAUGE_KEYS: Final = {
    "active_count",
    "active_forward_thread_count",
    "active_source_permit_count",
    "active_task_count",
    "active_client_channel_count",
    "entry_count",
    "frame_active_count",
    "frame_reserved_count",
    "frame_writing_count",
    "inflight_count",
    "pending_count",
    "pending_request_count",
    "pending_response_route_count",
    "quarantined_count",
    "request_queue_size",
    "reserved_count",
    "response_queue_size",
    "revoking_count",
    "startup_queue_size",
    "transport_registry_active_count",
    "transport_registry_quarantined_count",
    "transport_registry_reserved_count",
    "used_count",
    "used_page_count",
    "writing_count",
}


@dataclass(frozen=True)
class BenchmarkImageCase:
    """一组保持输入内容一致的 baseline/candidate 表示。"""

    name: str
    size_class: str
    path: Path
    baseline_mode: str
    candidate_mode: str
    media_type: str
    width: int
    height: int


@dataclass(frozen=True)
class BenchmarkSettings:
    """完整性能矩阵和公开资源配置。"""

    base_url: str
    token: str
    buffers_root: Path
    output_dir: Path
    zeromq_source_ids: tuple[str, ...]
    shared_source_ids: tuple[str, ...]
    image_cases: tuple[BenchmarkImageCase, ...]
    concurrency: tuple[int, ...]
    rounds: int
    warmup_iterations: int
    iterations_per_round: int
    soak_iterations: int
    timeout_seconds: float
    enable_timings: bool


@dataclass(frozen=True)
class ResolvedSourcePair:
    """绑定同一个 Workflow Runtime 的两个 transport 入口。"""

    runtime_id: str
    zeromq_source_id: str
    zeromq_endpoint: str
    shared_source_id: str
    shared_route_generation: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-dotnet-build", action="store_true")
    return parser.parse_args(argv)


def load_settings(config_path: Path, output_override: Path | None) -> BenchmarkSettings:
    """读取并严格校验性能矩阵配置。"""

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark config 必须是 JSON object")
    cases_payload = payload.get("image_cases")
    if not isinstance(cases_payload, list) or not cases_payload:
        raise ValueError("image_cases 不能为空")
    image_cases: list[BenchmarkImageCase] = []
    for index, raw_case in enumerate(cases_payload):
        if not isinstance(raw_case, dict):
            raise ValueError(f"image_cases[{index}] 必须是 JSON object")
        path = Path(str(raw_case.get("path") or ""))
        if not path.is_absolute():
            path = (config_path.parent / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"性能图片不存在：{path}")
        baseline_mode = _required_text(raw_case, "baseline_mode")
        candidate_mode = _required_text(raw_case, "candidate_mode")
        if baseline_mode not in SUPPORTED_MODES - {"bgr24-direct"}:
            raise ValueError(f"不支持的 ZeroMQ mode：{baseline_mode}")
        if candidate_mode not in SUPPORTED_MODES:
            raise ValueError(f"不支持的共享内存 mode：{candidate_mode}")
        width = int(raw_case.get("width") or 0)
        height = int(raw_case.get("height") or 0)
        if ("bgr24" in baseline_mode or "bgr24" in candidate_mode) and (
            width <= 0 or height <= 0 or path.stat().st_size != width * height * 3
        ):
            raise ValueError(
                f"{raw_case.get('name')} raw BGR24 必须满足 size=width*height*3"
            )
        image_cases.append(
            BenchmarkImageCase(
                name=_required_text(raw_case, "name"),
                size_class=_required_text(raw_case, "size_class").lower(),
                path=path,
                baseline_mode=baseline_mode,
                candidate_mode=candidate_mode,
                media_type=str(raw_case.get("media_type") or "application/octet-stream"),
                width=width,
                height=height,
            )
        )

    zeromq_sources = _text_tuple(payload.get("zeromq_trigger_source_ids"))
    shared_sources = _text_tuple(payload.get("shared_memory_trigger_source_ids"))
    concurrency = tuple(dict.fromkeys(int(item) for item in payload.get("concurrency", [1])))
    if not zeromq_sources or len(zeromq_sources) != len(shared_sources):
        raise ValueError("两组 TriggerSource 必须非空、等长并按 Runtime 成对排序")
    if not concurrency or min(concurrency) <= 0 or max(concurrency) > len(shared_sources):
        raise ValueError("concurrency 必须为正数且不能超过 source pair 数量")
    rounds = int(payload.get("rounds", 3))
    warmup = int(payload.get("warmup_iterations", 20))
    iterations = int(payload.get("iterations_per_round", 1_000))
    soak_iterations = int(payload.get("soak_iterations", 10_000))
    if rounds <= 0 or warmup < 0 or iterations <= 0 or soak_iterations < 0:
        raise ValueError("rounds/iterations 必须大于 0，warmup 不能小于 0")
    if soak_iterations > 0 and (len(shared_sources) < 2 or len(image_cases) < 2):
        raise ValueError("10,000 次混合 soak 至少需要两个 Runtime/source pair 和两个图片 case")
    output_dir = (
        output_override.resolve()
        if output_override is not None
        else (
            config_path.parent
            / str(payload.get("output_dir") or "workflow-trigger-transport-benchmark")
        ).resolve()
    )
    buffers_root = Path(str(payload.get("buffers_root") or ROOT / "data" / "buffers"))
    if not buffers_root.is_absolute():
        buffers_root = (ROOT / buffers_root).resolve()
    return BenchmarkSettings(
        base_url=str(payload.get("base_url") or "http://127.0.0.1:5600").rstrip("/"),
        token=str(payload.get("token") or DEFAULT_TOKEN),
        buffers_root=buffers_root,
        output_dir=output_dir,
        zeromq_source_ids=zeromq_sources,
        shared_source_ids=shared_sources,
        image_cases=tuple(image_cases),
        concurrency=concurrency,
        rounds=rounds,
        warmup_iterations=warmup,
        iterations_per_round=iterations,
        soak_iterations=soak_iterations,
        timeout_seconds=float(payload.get("timeout_seconds", 120.0)),
        enable_timings=bool(payload.get("enable_timings", False)),
    )


def run_benchmark(settings: BenchmarkSettings, *, build_dotnet: bool = True) -> int:
    """执行完整矩阵并写入可审计报告。"""

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    if build_dotnet:
        _build_dotnet_probe()
    pairs, preflight = _resolve_source_pairs(settings)
    _warmup_persistent_shared_clients(settings=settings, pairs=pairs)
    before_health = _capture_health(settings, pairs)
    _write_json(settings.output_dir / "preflight.json", preflight)
    cell_reports: list[dict[str, object]] = []
    failures: list[str] = []
    soak_report: dict[str, object] | None = None
    try:
        for image_case in settings.image_cases:
            for concurrency in settings.concurrency:
                for round_index in range(1, settings.rounds + 1):
                    baseline = _run_transport_round(
                        settings=settings,
                        pairs=pairs[:concurrency],
                        image_case=image_case,
                        transport="zeromq-topic",
                        round_index=round_index,
                    )
                    candidate = _run_transport_round(
                        settings=settings,
                        pairs=pairs[:concurrency],
                        image_case=image_case,
                        transport="local-shared-memory",
                        round_index=round_index,
                    )
                    cell = {
                        "case": image_case.name,
                        "size_class": image_case.size_class,
                        "concurrency": concurrency,
                        "round": round_index,
                        "baseline": baseline,
                        "candidate": candidate,
                    }
                    cell_failures = evaluate_cell(cell)
                    cell["failures"] = cell_failures
                    failures.extend(cell_failures)
                    cell_reports.append(cell)
                    _write_partial_result(settings, cell_reports, failures, before_health)
        if settings.soak_iterations > 0:
            soak_report = _run_shared_memory_soak(settings=settings, pairs=pairs)
    finally:
        after_health = _capture_health(settings, pairs)
    health_failures = evaluate_health_recovery(before_health, after_health)
    failures.extend(health_failures)
    result = {
        "format_id": "amvision.workflow-trigger-performance-matrix.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded" if not failures else "failed",
        "settings": _public_settings(settings),
        "before_health": before_health,
        "after_health": after_health,
        "cells": cell_reports,
        "soak": soak_report,
        "failures": failures,
    }
    _write_json(settings.output_dir / "result.json", result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "cell_count": len(cell_reports),
                "failure_count": len(failures),
                "result_path": str(settings.output_dir / "result.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


def evaluate_cell(cell: dict[str, object]) -> list[str]:
    """按固定工业性能阈值裁决一轮成对数据。"""

    baseline = _latency(cell, "baseline")
    candidate = _latency(cell, "candidate")
    label = f"{cell['case']} concurrency={cell['concurrency']} round={cell['round']}"
    failures: list[str] = []
    if candidate["p99"] > baseline["p99"] + max(5.0, baseline["p99"] * 0.10):
        failures.append(f"{label} candidate P99 超过阈值")
    baseline_tail = baseline["p99"] - baseline["p95"]
    candidate_tail = candidate["p99"] - candidate["p95"]
    if candidate_tail > baseline_tail + max(5.0, baseline["p95"] * 0.10):
        failures.append(f"{label} candidate P99-P95 长尾超过阈值")
    if str(cell.get("size_class")) == "20mp":
        baseline_transport = _optional_distribution(
            cell, "baseline", "transport_overhead_ms"
        )
        candidate_transport = _optional_distribution(
            cell, "candidate", "transport_overhead_ms"
        )
        if baseline_transport is None or candidate_transport is None:
            failures.append(f"{label} 20MP 数据面门禁缺少逐请求 Workflow timing")
        else:
            if candidate_transport["p50"] > baseline_transport["p50"] * 0.60:
                failures.append(f"{label} 20MP 数据面 P50 未降低至少 40%")
            if candidate_transport["p95"] > baseline_transport["p95"] * 0.60:
                failures.append(f"{label} 20MP 数据面 P95 未降低至少 40%")
        if candidate["p99"] > baseline["p99"]:
            failures.append(f"{label} 20MP candidate P99 高于 ZeroMQ")
    if str(cell.get("size_class")) == "1080p" and candidate["p95"] > baseline["p95"] * 1.10:
        failures.append(f"{label} 1080p candidate P95 回退超过 10%")
    return failures


def evaluate_health_recovery(
    before: dict[str, object],
    after: dict[str, object],
) -> list[str]:
    """确认测试结束后图片数据面和 Trigger 在途计数回到基线。"""

    before_counts = _collect_lifecycle_counts(before)
    after_counts = _collect_lifecycle_counts(after)
    failures: list[str] = []
    for key in sorted(set(before_counts) | set(after_counts)):
        before_value = before_counts.get(key, 0)
        after_value = after_counts.get(key, 0)
        if after_value > before_value:
            failures.append(f"health 生命周期计数未恢复：{key} {before_value} -> {after_value}")
    return failures


def _split_iterations(total: int, worker_count: int) -> tuple[int, ...]:
    """把固定总请求数均匀分配给 worker，不丢弃任何尾延迟样本。"""

    if total <= 0:
        raise ValueError("total 必须大于 0")
    if worker_count <= 0:
        raise ValueError("worker_count 必须大于 0")
    base, remainder = divmod(total, worker_count)
    return tuple(base + (1 if index < remainder else 0) for index in range(worker_count))


def _run_transport_round(
    *,
    settings: BenchmarkSettings,
    pairs: tuple[ResolvedSourcePair, ...],
    image_case: BenchmarkImageCase,
    transport: str,
    round_index: int,
) -> dict[str, object]:
    """以多个独立 SDK 进程并发执行一轮，并合并原始 latency samples。"""

    worker_iterations = _split_iterations(settings.iterations_per_round, len(pairs))
    round_root = (
        settings.output_dir
        / "children"
        / image_case.name
        / f"concurrency-{len(pairs)}"
        / f"round-{round_index}"
        / transport
    )
    round_root.mkdir(parents=True, exist_ok=True)

    work_items = tuple(
        (index, pair, worker_iterations[index])
        for index, pair in enumerate(pairs)
        if worker_iterations[index] > 0
    )

    def run_worker(item: tuple[int, ResolvedSourcePair, int]) -> dict[str, object]:
        index, pair, iterations = item
        child_config = {
            "transport": transport,
            "buffers_root": str(settings.buffers_root),
            "endpoint": pair.zeromq_endpoint,
            "trigger_source_id": (
                pair.zeromq_source_id
                if transport == "zeromq-topic"
                else pair.shared_source_id
            ),
            "route_generation": pair.shared_route_generation,
            "input_binding": "request_image_ref",
            "input_mode": (
                image_case.baseline_mode
                if transport == "zeromq-topic"
                else image_case.candidate_mode
            ),
            "input_path": str(image_case.path),
            "media_type": image_case.media_type,
            "width": image_case.width,
            "height": image_case.height,
            "warmup_iterations": settings.warmup_iterations,
            "iterations": iterations,
            "timeout_seconds": settings.timeout_seconds,
            "enable_timings": settings.enable_timings,
        }
        config_path = round_root / f"worker-{index}.config.json"
        report_path = round_root / f"worker-{index}.result.json"
        _write_json(config_path, child_config)
        completed = subprocess.run(
            [
                str(DOTNET_PROBE),
                "--benchmark-workflow-trigger",
                str(config_path),
                str(report_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(
                120.0,
                settings.timeout_seconds * (iterations + settings.warmup_iterations),
            ),
            check=False,
        )
        if not report_path.is_file():
            raise RuntimeError(completed.stdout + completed.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if completed.returncode != 0 or int(report.get("error_count") or 0) != 0:
            raise RuntimeError(json.dumps(report, ensure_ascii=False))
        return report

    with ThreadPoolExecutor(max_workers=len(work_items)) as executor:
        reports = list(executor.map(run_worker, work_items))
    samples = sorted(
        float(value)
        for report in reports
        for value in report.get("latency_samples_ms", [])
    )
    if len(samples) != settings.iterations_per_round:
        raise RuntimeError("子进程 latency sample 数量不符合每轮契约")
    transport_overhead_samples = sorted(
        float(value)
        for report in reports
        for value in report.get("transport_overhead_samples_ms", [])
    )
    if transport_overhead_samples and len(transport_overhead_samples) != len(samples):
        raise RuntimeError("子进程 transport overhead sample 数量不符合每轮契约")
    return {
        "transport": transport,
        "input_mode": (
            image_case.baseline_mode
            if transport == "zeromq-topic"
            else image_case.candidate_mode
        ),
        "request_count": len(samples),
        "latency_ms": _distribution(samples),
        "transport_overhead_ms": (
            _distribution(transport_overhead_samples)
            if transport_overhead_samples
            else None
        ),
        "workers": reports,
    }


def _run_shared_memory_soak(
    *,
    settings: BenchmarkSettings,
    pairs: tuple[ResolvedSourcePair, ...],
) -> dict[str, object]:
    """并发混合不同 Runtime 和图片表示，完成固定总次数稳定性 soak。"""

    worker_iterations = _split_iterations(settings.soak_iterations, len(pairs))
    soak_root = settings.output_dir / "soak" / "local-shared-memory"
    soak_root.mkdir(parents=True, exist_ok=True)

    work_items = tuple(
        (index, pair, worker_iterations[index])
        for index, pair in enumerate(pairs)
        if worker_iterations[index] > 0
    )

    def run_worker(item: tuple[int, ResolvedSourcePair, int]) -> dict[str, object]:
        index, pair, iterations = item
        image_case = settings.image_cases[index % len(settings.image_cases)]
        config_path = soak_root / f"worker-{index}.config.json"
        report_path = soak_root / f"worker-{index}.result.json"
        _write_json(
            config_path,
            {
                "transport": "local-shared-memory",
                "buffers_root": str(settings.buffers_root),
                "trigger_source_id": pair.shared_source_id,
                "route_generation": pair.shared_route_generation,
                "input_binding": "request_image_ref",
                "input_mode": image_case.candidate_mode,
                "input_path": str(image_case.path),
                "media_type": image_case.media_type,
                "width": image_case.width,
                "height": image_case.height,
                "warmup_iterations": settings.warmup_iterations,
                "iterations": iterations,
                "timeout_seconds": settings.timeout_seconds,
                "enable_timings": settings.enable_timings,
            },
        )
        completed = subprocess.run(
            [
                str(DOTNET_PROBE),
                "--benchmark-workflow-trigger",
                str(config_path),
                str(report_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(
                120.0,
                settings.timeout_seconds
                * (iterations + settings.warmup_iterations),
            ),
            check=False,
        )
        if not report_path.is_file():
            raise RuntimeError(completed.stdout + completed.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if completed.returncode != 0 or int(report.get("error_count") or 0) != 0:
            raise RuntimeError(json.dumps(report, ensure_ascii=False))
        report["source_id"] = pair.shared_source_id
        report["runtime_id"] = pair.runtime_id
        report["case"] = image_case.name
        return report

    with ThreadPoolExecutor(max_workers=len(work_items)) as executor:
        reports = list(executor.map(run_worker, work_items))
    total_success = sum(int(report.get("success_count") or 0) for report in reports)
    if total_success != settings.soak_iterations:
        raise RuntimeError(
            "共享内存混合 soak 成功次数不符合契约："
            f"{total_success} != {settings.soak_iterations}"
        )
    return {
        "transport": "local-shared-memory",
        "requested_iterations": settings.soak_iterations,
        "completed_iterations": total_success,
        "worker_count": len(reports),
        "workers": reports,
    }


def _resolve_source_pairs(
    settings: BenchmarkSettings,
) -> tuple[tuple[ResolvedSourcePair, ...], dict[str, object]]:
    """通过公开 API 固定 endpoint、route generation 和 Runtime 配对关系。"""

    client = _api_client(settings)
    try:
        system_health = _get_json(client, "/system/health")
        pairs: list[ResolvedSourcePair] = []
        sources: list[dict[str, object]] = []
        runtime_ids: set[str] = set()
        for zeromq_id, shared_id in zip(
            settings.zeromq_source_ids,
            settings.shared_source_ids,
            strict=True,
        ):
            zeromq = _get_json(client, f"/workflows/trigger-sources/{zeromq_id}")
            shared = _get_json(client, f"/workflows/trigger-sources/{shared_id}")
            zeromq_health = _get_json(
                client, f"/workflows/trigger-sources/{zeromq_id}/health"
            )
            shared_health = _get_json(
                client, f"/workflows/trigger-sources/{shared_id}/health"
            )
            if zeromq.get("trigger_kind") != "zeromq-topic":
                raise RuntimeError(f"{zeromq_id} 不是 zeromq-topic")
            if shared.get("trigger_kind") != "local-shared-memory":
                raise RuntimeError(f"{shared_id} 不是 local-shared-memory")
            runtime_id = str(zeromq.get("workflow_runtime_id") or "")
            if not runtime_id or runtime_id != str(shared.get("workflow_runtime_id") or ""):
                raise RuntimeError(f"{zeromq_id}/{shared_id} 未绑定同一个 Runtime")
            if runtime_id in runtime_ids:
                raise RuntimeError("并发 source pair 必须绑定不同 Runtime")
            runtime_ids.add(runtime_id)
            _require_running(zeromq_health, zeromq_id)
            _require_running(shared_health, shared_id)
            transport = zeromq.get("transport_config")
            endpoint = str(
                transport.get("bind_endpoint")
                if isinstance(transport, dict)
                else ""
            )
            route_generation = _read_route_generation(shared_health)
            if not endpoint or route_generation <= 0:
                raise RuntimeError("TriggerSource endpoint/route generation 未就绪")
            pairs.append(
                ResolvedSourcePair(
                    runtime_id=runtime_id,
                    zeromq_source_id=zeromq_id,
                    zeromq_endpoint=endpoint,
                    shared_source_id=shared_id,
                    shared_route_generation=route_generation,
                )
            )
            sources.extend((zeromq_health, shared_health))
        return tuple(pairs), {"system_health": system_health, "sources": sources}
    finally:
        client.close()


def _capture_health(
    settings: BenchmarkSettings,
    pairs: tuple[ResolvedSourcePair, ...],
) -> dict[str, object]:
    """采集不含业务内容的公开 health。"""

    client = _api_client(settings)
    try:
        sources: dict[str, object] = {}
        for pair in pairs:
            for source_id in (pair.zeromq_source_id, pair.shared_source_id):
                sources[source_id] = _get_json(
                    client, f"/workflows/trigger-sources/{source_id}/health"
                )
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "system": _get_json(client, "/system/health"),
            "sources": sources,
        }
    finally:
        client.close()


def _warmup_persistent_shared_clients(
    *,
    settings: BenchmarkSettings,
    pairs: tuple[ResolvedSourcePair, ...],
) -> None:
    """在 before health 前建立服务端懒加载的常驻 Broker client。

    预热只验证每个 local-shared-memory source 一次，不进入性能样本。
    """

    image_case = min(settings.image_cases, key=lambda item: item.path.stat().st_size)
    warmup_root = settings.output_dir / "preflight-shared-client-warmup"
    warmup_root.mkdir(parents=True, exist_ok=True)

    def warm_pair(item: tuple[int, ResolvedSourcePair]) -> None:
        index, pair = item
        config_path = warmup_root / f"worker-{index}.config.json"
        report_path = warmup_root / f"worker-{index}.result.json"
        _write_json(
            config_path,
            {
                "transport": "local-shared-memory",
                "buffers_root": str(settings.buffers_root),
                "trigger_source_id": pair.shared_source_id,
                "route_generation": pair.shared_route_generation,
                "input_binding": "request_image_ref",
                "input_mode": image_case.candidate_mode,
                "input_path": str(image_case.path),
                "media_type": image_case.media_type,
                "width": image_case.width,
                "height": image_case.height,
                "warmup_iterations": 0,
                "iterations": 1,
                "timeout_seconds": settings.timeout_seconds,
                "enable_timings": False,
            },
        )
        completed = subprocess.run(
            [
                str(DOTNET_PROBE),
                "--benchmark-workflow-trigger",
                str(config_path),
                str(report_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(120.0, settings.timeout_seconds),
            check=False,
        )
        if not report_path.is_file():
            raise RuntimeError(completed.stdout + completed.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if completed.returncode != 0 or int(report.get("error_count") or 0) != 0:
            raise RuntimeError(json.dumps(report, ensure_ascii=False))

    with ThreadPoolExecutor(max_workers=len(pairs)) as executor:
        tuple(executor.map(warm_pair, enumerate(pairs)))


def _collect_lifecycle_counts(payload: object, prefix: str = "") -> dict[str, int]:
    """递归提取必须回到基线的在途 gauge，排除累计量和高水位。"""

    result: dict[str, int] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            normalized = str(key).lower()
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and normalized in LIFECYCLE_GAUGE_KEYS
            ):
                result[path] = value
            else:
                result.update(_collect_lifecycle_counts(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            result.update(_collect_lifecycle_counts(value, f"{prefix}[{index}]"))
    return result


def _write_partial_result(
    settings: BenchmarkSettings,
    cells: list[dict[str, object]],
    failures: list[str],
    before_health: dict[str, object],
) -> None:
    _write_json(
        settings.output_dir / "result.json",
        {
            "format_id": "amvision.workflow-trigger-performance-matrix.v1",
            "status": "running",
            "settings": _public_settings(settings),
            "before_health": before_health,
            "cells": cells,
            "failures": failures,
        },
    )


def _public_settings(settings: BenchmarkSettings) -> dict[str, object]:
    """输出不包含 token 的基准配置。"""

    return {
        "base_url": settings.base_url,
        "buffers_root": str(settings.buffers_root),
        "zeromq_trigger_source_ids": settings.zeromq_source_ids,
        "shared_memory_trigger_source_ids": settings.shared_source_ids,
        "concurrency": settings.concurrency,
        "rounds": settings.rounds,
        "warmup_iterations": settings.warmup_iterations,
        "iterations_per_round": settings.iterations_per_round,
        "soak_iterations": settings.soak_iterations,
        "enable_timings": settings.enable_timings,
    }


def _latency(cell: dict[str, object], key: str) -> dict[str, float]:
    report = cell[key]
    assert isinstance(report, dict)
    latency = report["latency_ms"]
    assert isinstance(latency, dict)
    return {name: float(value) for name, value in latency.items()}


def _optional_distribution(
    cell: dict[str, object],
    report_key: str,
    distribution_key: str,
) -> dict[str, float] | None:
    """读取可选分位数；正式大图数据面门禁要求该字段存在。"""

    report = cell.get(report_key)
    if not isinstance(report, dict):
        return None
    distribution = report.get(distribution_key)
    if not isinstance(distribution, dict):
        return None
    return {name: float(value) for name, value in distribution.items()}


def _distribution(values: list[float]) -> dict[str, float]:
    """计算线性插值分位数。"""

    if not values:
        raise ValueError("latency samples 不能为空")
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 6),
        "mean": round(sum(ordered) / len(ordered), 6),
        "p50": round(_percentile(ordered, 0.50), 6),
        "p95": round(_percentile(ordered, 0.95), 6),
        "p99": round(_percentile(ordered, 0.99), 6),
        "max": round(ordered[-1], 6),
    }


def _percentile(ordered: list[float], quantile: float) -> float:
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _build_dotnet_probe() -> None:
    completed = subprocess.run(
        [
            "dotnet",
            "msbuild",
            str(DOTNET_PROJECT),
            "/t:Rebuild",
            "/p:Configuration=Release",
            "/p:TreatWarningsAsErrors=true",
            "/v:minimal",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout + completed.stderr)


def _api_client(settings: BenchmarkSettings) -> httpx.Client:
    return httpx.Client(
        base_url=f"{settings.base_url}/api/v1",
        headers={"Authorization": f"Bearer {settings.token}"},
        timeout=httpx.Timeout(settings.timeout_seconds),
    )


def _get_json(client: httpx.Client, path: str) -> dict[str, object]:
    response = client.get(path)
    if response.status_code >= 400:
        raise RuntimeError(f"GET {path} failed: {response.status_code} {response.text[:1000]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {path} 未返回 JSON object")
    return payload


def _require_running(payload: dict[str, object], label: str) -> None:
    state = str(payload.get("observed_state") or payload.get("state") or "").lower()
    summary = payload.get("health_summary")
    if state not in {"running", "ready", "healthy"}:
        raise RuntimeError(f"{label} 未运行：{state}")
    if isinstance(summary, dict) and summary.get("adapter_running") is False:
        raise RuntimeError(f"{label} adapter_running 不是 true")


def _read_route_generation(payload: dict[str, object]) -> int:
    """从正式 health 的 supervisor/adapter 层读取本机共享内存路由代次。"""

    summary = payload.get("health_summary")
    supervisor = summary.get("supervisor") if isinstance(summary, dict) else None
    adapter_health = (
        supervisor.get("adapter_health") if isinstance(supervisor, dict) else None
    )
    value = (
        adapter_health.get("route_generation")
        if isinstance(adapter_health, dict)
        else None
    )
    try:
        generation = int(value)
    except (TypeError, ValueError):
        generation = 0
    return max(0, generation)


def _required_text(payload: dict[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} 不能为空")
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(dict.fromkeys(items))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    replace_path_with_retry(temporary, path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.config_json.resolve(), args.output_dir)
        return run_benchmark(settings, build_dotnet=not args.skip_dotnet_build)
    except Exception as error:
        print(f"{error.__class__.__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
