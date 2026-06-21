"""YOLO26 导出数值校验策略。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError


def summarize_yolo26_detection_processed_onnx_validation(
    *,
    np_module: object,
    torch_outputs: list[object],
    ort_outputs: list[object],
    task_type: str,
) -> dict[str, object]:
    """校验 YOLO26 detection end2end processed TopK 输出。

    官方 processed 输出已经包含 TopK。PyTorch 和 ONNXRuntime 在大量同分候选框
    上可能选择不同的等价行顺序，因此这里校验 shape、finite、score/class 语义，
    并把逐行 raw 差异保留在摘要里用于排查。
    """

    if task_type != "detection":
        raise ServiceConfigurationError(
            "YOLO26 processed TopK 校验只支持 detection task",
            details={"task_type": task_type},
        )
    if len(torch_outputs) != 1 or len(ort_outputs) != 1:
        raise ServiceConfigurationError(
            "YOLO26 detection ONNX 输出数量不合法",
            details={
                "torch_output_count": len(torch_outputs),
                "ort_output_count": len(ort_outputs),
            },
        )
    torch_output = torch_outputs[0]
    ort_output = ort_outputs[0]
    if tuple(torch_output.shape) != tuple(ort_output.shape):
        raise ServiceConfigurationError(
            "YOLO26 detection ONNX 输出形状与 PyTorch 不一致",
            details={
                "torch_shape": list(torch_output.shape),
                "ort_shape": list(ort_output.shape),
            },
        )
    if len(tuple(torch_output.shape)) != 3 or int(torch_output.shape[2]) != 6:
        raise ServiceConfigurationError(
            "YOLO26 detection processed 输出必须是 [B,K,6]",
            details={"shape": list(torch_output.shape)},
        )

    abs_diff = np_module.abs(torch_output - ort_output)
    finite = bool(np_module.isfinite(torch_output).all()) and bool(
        np_module.isfinite(ort_output).all()
    )
    raw_row_allclose = bool(
        np_module.allclose(torch_output, ort_output, rtol=1e-3, atol=1e-4)
    )
    score_allclose = bool(
        np_module.allclose(
            torch_output[:, :, 4],
            ort_output[:, :, 4],
            rtol=1e-3,
            atol=1e-4,
        )
    )
    class_allclose = bool(
        np_module.allclose(
            torch_output[:, :, 5],
            ort_output[:, :, 5],
            rtol=0.0,
            atol=1e-4,
        )
    )
    return {
        "stage": "validate-onnx",
        "allclose": score_allclose and class_allclose,
        "finite": finite,
        "max_abs_diff": float(np_module.max(abs_diff)),
        "mean_abs_diff": float(np_module.mean(abs_diff)),
        "output_count": 1,
        "processed_topk_validation": True,
        "raw_row_allclose": raw_row_allclose,
        "score_allclose": score_allclose,
        "class_allclose": class_allclose,
    }


__all__ = [
    "summarize_yolo26_detection_processed_onnx_validation",
]
