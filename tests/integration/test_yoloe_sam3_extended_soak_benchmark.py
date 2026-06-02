"""YOLOE / SAM3 更长时长与更大图尺寸 soak 基线。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from custom_nodes.sam3_segment_nodes.backend.nodes._common import (
    get_or_create_sam3_semantic_runtime_session,
    merge_text_prompt_items as merge_sam3_text_prompt_items,
    read_text_prompt_items as read_sam3_text_prompt_items,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import (
    get_or_create_yoloe_text_prompt_runtime_session,
)
from tests.integration.test_yoloe_sam3_soak_benchmark import (
    CPU_MEMORY_DRIFT_LIMIT_BYTES,
    GPU_MEMORY_DRIFT_LIMIT_BYTES,
    _build_test_png_bytes,
    _run_cpu_soak_benchmark,
    _run_cuda_soak_benchmark,
)


EXTENDED_CPU_SOAK_ITERATIONS = 10
EXTENDED_GPU_SOAK_ITERATIONS = 6


def test_yoloe_text_prompt_cpu_extended_soak_benchmark() -> None:
    """验证 YOLOE text-prompt 在更大图尺寸与更长迭代下的 CPU 稳定性。"""

    session = get_or_create_yoloe_text_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    repeated_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    assert session is repeated_session

    image_bytes = _build_test_png_bytes(width=640, height=448)
    prompts = (
        SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language="en"),
        SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
        SimpleNamespace(prompt_id="prompt-2", text="car", display_name="vehicle", negative=False, language="en"),
        SimpleNamespace(prompt_id="prompt-2", text="truck", display_name="vehicle", negative=False, language="en"),
        SimpleNamespace(prompt_id="prompt-2", text="road", display_name="vehicle", negative=True, language="en"),
        SimpleNamespace(prompt_id="prompt-3", text="equipment", display_name="equipment", negative=False, language="en"),
    )

    warm_prediction = session.predict(
        image_bytes=image_bytes,
        prompts=prompts,
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=20,
    )
    assert warm_prediction.summary["project_native"] is True
    assert warm_prediction.summary["prompt_group_count"] == 3

    benchmark = _run_cpu_soak_benchmark(
        benchmark_name="yoloe-text-prompt-cpu-extended",
        iterations=EXTENDED_CPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(
            image_bytes=image_bytes,
            prompts=prompts,
            confidence_threshold=0.25,
            iou_threshold=0.7,
            max_detections=20,
        ),
    )
    assert benchmark["memory_drift_bytes"] <= CPU_MEMORY_DRIFT_LIMIT_BYTES


def test_sam3_semantic_cpu_extended_soak_benchmark() -> None:
    """验证 SAM3 semantic 在更大图尺寸与更长迭代下的 CPU 稳定性。"""

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

    image_bytes = _build_test_png_bytes(width=768, height=512)
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
                    {
                        "prompt_id": "prompt-2",
                        "text": "shadow",
                        "display_name": "surface",
                        "negative": True,
                    },
                    {
                        "prompt_id": "prompt-3",
                        "text": "edge",
                        "display_name": "edge",
                    },
                ]
            }
        )
    )

    warm_prediction = session.predict(image_bytes=image_bytes, prompt_items=prompt_groups)
    assert warm_prediction.summary["project_native"] is True
    assert warm_prediction.summary["prompt_group_count"] == 3

    benchmark = _run_cpu_soak_benchmark(
        benchmark_name="sam3-semantic-cpu-extended",
        iterations=EXTENDED_CPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(image_bytes=image_bytes, prompt_items=prompt_groups),
    )
    assert benchmark["memory_drift_bytes"] <= CPU_MEMORY_DRIFT_LIMIT_BYTES


@pytest.mark.skipif(not torch.cuda.is_available(), reason="当前环境没有可用 CUDA")
def test_yoloe_text_prompt_cuda_extended_soak_benchmark() -> None:
    """验证 YOLOE text-prompt 在更大图尺寸与更长迭代下的 CUDA 稳定性。"""

    session = get_or_create_yoloe_text_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cuda",
        precision="fp16",
    )
    repeated_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cuda",
        precision="fp16",
    )
    assert session is repeated_session

    image_bytes = _build_test_png_bytes(width=640, height=448)
    prompts = (
        SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language="en"),
        SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
        SimpleNamespace(prompt_id="prompt-2", text="car", display_name="vehicle", negative=False, language="en"),
        SimpleNamespace(prompt_id="prompt-2", text="road", display_name="vehicle", negative=True, language="en"),
    )

    warm_prediction = session.predict(
        image_bytes=image_bytes,
        prompts=prompts,
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=20,
    )
    assert warm_prediction.summary["project_native"] is True

    benchmark = _run_cuda_soak_benchmark(
        benchmark_name="yoloe-text-prompt-cuda-extended",
        iterations=EXTENDED_GPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(
            image_bytes=image_bytes,
            prompts=prompts,
            confidence_threshold=0.25,
            iou_threshold=0.7,
            max_detections=20,
        ),
    )
    assert benchmark["memory_drift_bytes"] <= GPU_MEMORY_DRIFT_LIMIT_BYTES


@pytest.mark.skipif(not torch.cuda.is_available(), reason="当前环境没有可用 CUDA")
def test_sam3_semantic_cuda_extended_soak_benchmark() -> None:
    """验证 SAM3 semantic 在更大图尺寸与更长迭代下的 CUDA 稳定性。"""

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

    image_bytes = _build_test_png_bytes(width=768, height=512)
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

    benchmark = _run_cuda_soak_benchmark(
        benchmark_name="sam3-semantic-cuda-extended",
        iterations=EXTENDED_GPU_SOAK_ITERATIONS,
        predict_once=lambda: session.predict(image_bytes=image_bytes, prompt_items=prompt_groups),
    )
    assert benchmark["memory_drift_bytes"] <= GPU_MEMORY_DRIFT_LIMIT_BYTES
