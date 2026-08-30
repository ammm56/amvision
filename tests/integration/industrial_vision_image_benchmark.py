"""工业二维视觉 Run 内图片链路可复现测量工具。

该工具只测量同一进程、同一次 Workflow Run 内的 typed image identity 与平移链路，
用于确认常见分辨率没有引入 Base64，并记录 P50/P95 与 Working Set。机器相关数值
只写入指定报告，不作为 CI 的绝对耗时阈值。
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Final

import numpy as np
import psutil

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.nodes import ExecutionImageRegistry  # noqa: E402
from backend.nodes.runtime_support import register_image_matrix  # noqa: E402
from backend.service.application.workflows.graph_executor import (  # noqa: E402
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.basic.backend.nodes.industrial_image import (  # noqa: E402
    handle_image_translate,
    handle_image_type_convert,
)

DEFAULT_OUTPUT: Final = ROOT / ".tmp" / "industrial-vision" / "image-benchmark.json"
RESOLUTIONS: Final = (
    ("640x480", 640, 480),
    ("1024x1024", 1024, 1024),
    ("1080p", 1920, 1080),
    ("4k", 3840, 2160),
    ("20mp", 5472, 3648),
)


def _request(
    registry: ExecutionImageRegistry,
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造同一 Run 内共享图片 registry 的节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="industrial-vision-image-benchmark",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
        execution_metadata={"execution_image_registry": registry},
    )


def _run_once(source: np.ndarray) -> tuple[float, bool]:
    """运行一次 identity 与 translate，并返回耗时和零 Base64 判定。"""

    registry = ExecutionImageRegistry()
    source_payload = register_image_matrix(
        _request(registry),
        image_matrix=source,
    )
    started_at = time.perf_counter_ns()
    identity_payload = handle_image_type_convert(
        _request(
            registry,
            parameters={
                "target_dtype": "uint8",
                "channel_layout": "keep",
                "range_mode": "preserve",
            },
            input_values={"image": source_payload},
        )
    )["image"]
    identity_matrix = registry.read_matrix(str(identity_payload["image_handle"]))
    if identity_matrix is not source:
        raise AssertionError("identity 转换产生了无必要的整图副本")
    translated_payload = handle_image_translate(
        _request(
            registry,
            parameters={
                "offset_x": 1,
                "offset_y": 1,
                "interpolation": "nearest",
            },
            input_values={"image": identity_payload},
        )
    )["image"]
    elapsed_ms = (time.perf_counter_ns() - started_at) / 1_000_000.0
    translated_matrix = registry.read_matrix(str(translated_payload["image_handle"]))
    if translated_matrix.shape != source.shape or translated_matrix.dtype != source.dtype:
        raise AssertionError("代表链路改变了图片 shape 或 dtype")
    no_base64 = all(
        payload.get("transport_kind") == "memory" and "image_base64" not in payload
        for payload in (identity_payload, translated_payload)
    )
    registry.clear()
    return elapsed_ms, no_base64


def _percentile(samples: list[float], quantile: float) -> float:
    """按线性插值计算分位数。"""

    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def run_benchmark(*, warmup: int, iterations: int) -> dict[str, object]:
    """执行固定分辨率矩阵并返回稳定 JSON 报告。"""

    if warmup < 1 or iterations < 5:
        raise ValueError("warmup 至少为 1，iterations 至少为 5")
    process = psutil.Process(os.getpid())
    cases = []
    for label, width, height in RESOLUTIONS:
        source = np.zeros((height, width, 3), dtype=np.uint8)
        source[height // 2, width // 2] = (20, 120, 240)
        for _ in range(warmup):
            _run_once(source)
        gc.collect()
        before = process.memory_info()
        peak_working_set = int(before.rss)
        samples = []
        no_base64 = True
        for _ in range(iterations):
            elapsed_ms, iteration_no_base64 = _run_once(source)
            samples.append(elapsed_ms)
            no_base64 = no_base64 and iteration_no_base64
            peak_working_set = max(peak_working_set, int(process.memory_info().rss))
        gc.collect()
        after = process.memory_info()
        cases.append(
            {
                "label": label,
                "width": width,
                "height": height,
                "source_bytes": int(source.nbytes),
                "iterations": iterations,
                "latency_ms": {
                    "p50": round(statistics.median(samples), 3),
                    "p95": round(_percentile(samples, 0.95), 3),
                    "maximum": round(max(samples), 3),
                },
                "working_set": {
                    "before_bytes": int(before.rss),
                    "after_bytes": int(after.rss),
                    "delta_bytes": int(after.rss) - int(before.rss),
                    "observed_peak_bytes": peak_working_set,
                },
                "identity_reuses_source_matrix": True,
                "memory_transport_only": no_base64,
            }
        )
        del source
        gc.collect()
    return {
        "format_id": "amvision.industrial-vision-image-benchmark.v1",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "warmup_iterations": warmup,
        "iterations": iterations,
        "cases": cases,
    }


def main() -> None:
    """解析命令行并写入测量报告。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=10)
    arguments = parser.parse_args()
    report = run_benchmark(
        warmup=arguments.warmup,
        iterations=arguments.iterations,
    )
    output_path = arguments.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
