"""YOLOE / SAM3 本地资产长时 soak 与 benchmark。"""

from __future__ import annotations

import ctypes
import gc
import io
import json
import statistics
import time
from types import SimpleNamespace
from ctypes import wintypes

from PIL import Image
import pytest
import torch

from backend.service.application.errors import InvalidRequestError
from custom_nodes.sam3_segment_nodes.backend.nodes._common import (
    get_or_create_sam3_semantic_runtime_session,
    merge_text_prompt_items as merge_sam3_text_prompt_items,
    read_text_prompt_items as read_sam3_text_prompt_items,
    resolve_sam3_pretrained_variant,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.pretrained import (
    resolve_yoloe_pretrained_variant,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.access import (
    get_or_create_yoloe_text_prompt_runtime_session,
)


CPU_SOAK_ITERATIONS = 6
GPU_SOAK_ITERATIONS = 4
CPU_MEMORY_DRIFT_LIMIT_BYTES = 512 * 1024 * 1024
GPU_MEMORY_DRIFT_LIMIT_BYTES = 768 * 1024 * 1024


def test_yoloe_text_prompt_cpu_soak_benchmark() -> None:
    """验证 YOLOE text-prompt 在 CPU 上的长时重复推理、缓存驻留和内存漂移。"""

    session = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    repeated_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    assert session is repeated_session

    image_bytes = _build_test_png_bytes(width=96, height=72)
    prompts = (
        SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
        SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
        SimpleNamespace(prompt_id="prompt-2", text="car", display_name="car", negative=False, language=None),
    )
    warm_prediction = session.predict(
        image_bytes=image_bytes,
        prompts=prompts,
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=10,
    )
    assert warm_prediction.summary["project_native"] is True
    benchmark = _run_cpu_soak_benchmark(
        benchmark_name="yoloe-text-prompt-cpu",
        iterations=CPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(
            image_bytes=image_bytes,
            prompts=prompts,
            confidence_threshold=0.25,
            iou_threshold=0.7,
            max_detections=10,
        ),
    )
    assert benchmark["memory_drift_bytes"] <= CPU_MEMORY_DRIFT_LIMIT_BYTES


def test_sam3_semantic_cpu_soak_benchmark() -> None:
    """验证 SAM3 semantic 在 CPU 上的长时重复推理、缓存驻留和内存漂移。"""

    session = get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cpu",
        precision="fp32",
    )
    repeated_session = get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cpu",
        precision="fp32",
    )
    assert session is repeated_session

    image_bytes = _build_test_png_bytes(width=128, height=96)
    prompt_groups = merge_sam3_text_prompt_items(
        read_sam3_text_prompt_items(
            {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "object",
                        "display_name": "object",
                    },
                    {
                        "prompt_id": "prompt-1",
                        "text": "background",
                        "display_name": "object",
                        "negative": True,
                    },
                    {
                        "prompt_id": "prompt-2",
                        "text": "surface",
                        "display_name": "surface",
                    },
                ]
            }
        )
    )
    warm_prediction = session.predict(image_bytes=image_bytes, prompt_items=prompt_groups)
    assert warm_prediction.summary["project_native"] is True
    benchmark = _run_cpu_soak_benchmark(
        benchmark_name="sam3-semantic-cpu",
        iterations=CPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(image_bytes=image_bytes, prompt_items=prompt_groups),
    )
    assert benchmark["memory_drift_bytes"] <= CPU_MEMORY_DRIFT_LIMIT_BYTES


@pytest.mark.skipif(not torch.cuda.is_available(), reason="当前环境没有可用 CUDA")
def test_yoloe_text_prompt_cuda_soak_benchmark() -> None:
    """验证 YOLOE text-prompt 在 CUDA 上的会话驻留、重复推理和显存漂移。"""

    session = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cuda",
        precision="fp16",
    )
    repeated_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cuda",
        precision="fp16",
    )
    assert session is repeated_session

    image_bytes = _build_test_png_bytes(width=96, height=72)
    prompts = (
        SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
        SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
    )
    warm_prediction = session.predict(
        image_bytes=image_bytes,
        prompts=prompts,
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=10,
    )
    assert warm_prediction.summary["project_native"] is True
    benchmark = _run_cuda_soak_benchmark(
        benchmark_name="yoloe-text-prompt-cuda",
        iterations=GPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(
            image_bytes=image_bytes,
            prompts=prompts,
            confidence_threshold=0.25,
            iou_threshold=0.7,
            max_detections=10,
        ),
    )
    assert benchmark["memory_drift_bytes"] <= GPU_MEMORY_DRIFT_LIMIT_BYTES


@pytest.mark.skipif(not torch.cuda.is_available(), reason="当前环境没有可用 CUDA")
def test_sam3_semantic_cuda_soak_benchmark() -> None:
    """验证 SAM3 semantic 在 CUDA 上的会话驻留、重复推理和显存漂移。"""

    session = get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cuda",
        precision="fp16",
    )
    repeated_session = get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cuda",
        precision="fp16",
    )
    assert session is repeated_session

    image_bytes = _build_test_png_bytes(width=128, height=96)
    prompt_groups = merge_sam3_text_prompt_items(
        read_sam3_text_prompt_items(
            {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "object",
                        "display_name": "object",
                    },
                    {
                        "prompt_id": "prompt-1",
                        "text": "background",
                        "display_name": "object",
                        "negative": True,
                    },
                ]
            }
        )
    )
    warm_prediction = session.predict(image_bytes=image_bytes, prompt_items=prompt_groups)
    assert warm_prediction.summary["project_native"] is True
    benchmark = _run_cuda_soak_benchmark(
        benchmark_name="sam3-semantic-cuda",
        iterations=GPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(image_bytes=image_bytes, prompt_items=prompt_groups),
    )
    assert benchmark["memory_drift_bytes"] <= GPU_MEMORY_DRIFT_LIMIT_BYTES


def test_yoloe_sam3_asset_failure_recovery_smoke() -> None:
    """验证异常预训练目录失败后，恢复到真实本地资产仍可继续推理。"""

    with pytest.raises(InvalidRequestError, match="manifest"):
        resolve_yoloe_pretrained_variant(model_series="v8", model_scale="xx", prompt_free=False)
    with pytest.raises(InvalidRequestError, match="manifest"):
        resolve_sam3_pretrained_variant(model_scale="xx")

    yoloe_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    yoloe_prediction = yoloe_session.predict(
        image_bytes=_build_test_png_bytes(width=80, height=60),
        prompts=(
            SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
        ),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )
    assert yoloe_prediction.summary["project_native"] is True

    sam3_session = get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cpu",
        precision="fp32",
    )
    sam3_prediction = sam3_session.predict(
        image_bytes=_build_test_png_bytes(width=128, height=96),
        prompt_items=merge_sam3_text_prompt_items(
            read_sam3_text_prompt_items(
                {
                    "items": [
                        {
                            "prompt_id": "prompt-1",
                            "text": "object",
                            "display_name": "object",
                        }
                    ]
                }
            )
        ),
    )
    assert sam3_prediction.summary["project_native"] is True


def _run_cpu_soak_benchmark(
    *,
    benchmark_name: str,
    iterations: int,
    predict_once,
) -> dict[str, object]:
    """执行 CPU 长时重复推理并输出 benchmark 摘要。"""

    gc.collect()
    baseline_memory_bytes = _read_process_memory_bytes()
    iteration_durations_ms: list[float] = []
    last_summary: dict[str, object] | None = None
    for _index in range(iterations):
        started_at = time.perf_counter()
        prediction = predict_once()
        iteration_durations_ms.append((time.perf_counter() - started_at) * 1000.0)
        last_summary = dict(prediction.summary)
        gc.collect()
    end_memory_bytes = _read_process_memory_bytes()
    benchmark = {
        "benchmark_name": benchmark_name,
        "iterations": int(iterations),
        "device": "cpu",
        "memory_baseline_bytes": int(baseline_memory_bytes),
        "memory_end_bytes": int(end_memory_bytes),
        "memory_drift_bytes": int(max(0, end_memory_bytes - baseline_memory_bytes)),
        "duration_ms": _summarize_durations(iteration_durations_ms),
        "last_summary": last_summary or {},
    }
    print(json.dumps(benchmark, ensure_ascii=False))
    return benchmark


def _run_cuda_soak_benchmark(
    *,
    benchmark_name: str,
    iterations: int,
    predict_once,
) -> dict[str, object]:
    """执行 CUDA 长时重复推理并输出显存 benchmark 摘要。"""

    if not torch.cuda.is_available():
        pytest.skip("当前环境没有可用 CUDA")
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()
    baseline_allocated_bytes = int(torch.cuda.memory_allocated())
    baseline_reserved_bytes = int(torch.cuda.memory_reserved())
    torch.cuda.reset_peak_memory_stats()
    iteration_durations_ms: list[float] = []
    last_summary: dict[str, object] | None = None
    for _index in range(iterations):
        started_at = time.perf_counter()
        prediction = predict_once()
        torch.cuda.synchronize()
        iteration_durations_ms.append((time.perf_counter() - started_at) * 1000.0)
        last_summary = dict(prediction.summary)
    end_allocated_bytes = int(torch.cuda.memory_allocated())
    end_reserved_bytes = int(torch.cuda.memory_reserved())
    peak_allocated_bytes = int(torch.cuda.max_memory_allocated())
    benchmark = {
        "benchmark_name": benchmark_name,
        "iterations": int(iterations),
        "device": "cuda",
        "memory_baseline_allocated_bytes": baseline_allocated_bytes,
        "memory_baseline_reserved_bytes": baseline_reserved_bytes,
        "memory_end_allocated_bytes": end_allocated_bytes,
        "memory_end_reserved_bytes": end_reserved_bytes,
        "memory_peak_allocated_bytes": peak_allocated_bytes,
        "memory_drift_bytes": int(max(0, end_allocated_bytes - baseline_allocated_bytes)),
        "duration_ms": _summarize_durations(iteration_durations_ms),
        "last_summary": last_summary or {},
    }
    print(json.dumps(benchmark, ensure_ascii=False))
    return benchmark


def _summarize_durations(durations_ms: list[float]) -> dict[str, float]:
    """汇总多次推理耗时。"""

    if not durations_ms:
        return {"avg": 0.0, "min": 0.0, "max": 0.0}
    return {
        "avg": round(float(statistics.mean(durations_ms)), 3),
        "min": round(float(min(durations_ms)), 3),
        "max": round(float(max(durations_ms)), 3),
    }


def _read_process_memory_bytes() -> int:
    """读取当前进程常驻内存。"""

    if hasattr(ctypes, "windll"):
        class _ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCountersEx),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        counters = _ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(_ProcessMemoryCountersEx)
        process_handle = ctypes.windll.kernel32.GetCurrentProcess()
        success = get_process_memory_info(
            process_handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if success:
            return int(counters.WorkingSetSize)
    return 0


def _build_test_png_bytes(*, width: int, height: int) -> bytes:
    """构造测试 PNG 图片。"""

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
