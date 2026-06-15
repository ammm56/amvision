"""RF-DETR core 导出处理模块：`export._onnx.inference`。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image as PILImage

from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


def _create_onnx_session(model_path: str | Path) -> Any:
    """执行 `_create_onnx_session`。
    
    参数：
    - `model_path`：传入的 `model_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ImportError(
            "RF-DETR ONNX Runtime 推理需要安装 onnxruntime。请先安装 requirements.txt。"
        ) from exc

    session = ort.InferenceSession(str(model_path))
    for inp in session.get_inputs():
        logger.debug("Input  : name=%s  shape=%s  type=%s", inp.name, inp.shape, inp.type)
    for out in session.get_outputs():
        logger.debug("Output : name=%s  shape=%s  type=%s", out.name, out.shape, out.type)
    return session


def _run_inference(
    session: Any,
    image_path: str | Path,
    threshold: float = 0.3,
) -> tuple[Any, PILImage.Image]:
    """执行 `_run_inference`。
    
    参数：
    - `session`：传入的 `session` 参数。
    - `image_path`：传入的 `image_path` 参数。
    - `threshold`：传入的 `threshold` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core import supervision_compat as sv

    inputs = session.get_inputs()
    outputs = session.get_outputs()
    input_name = inputs[0].name
    _, channels, height, width = inputs[0].shape

    _imagenet_mean = [0.485, 0.456, 0.406]
    _imagenet_std = [0.229, 0.224, 0.225]
    mean = np.array([_imagenet_mean[i % 3] for i in range(channels)], dtype=np.float32)
    std = np.array([_imagenet_std[i % 3] for i in range(channels)], dtype=np.float32)

    pil_img = PILImage.open(image_path)
    pil_mode = "L" if channels == 1 else "RGB"
    arr = (
        np.array(
            pil_img.convert(pil_mode).resize((width, height), PILImage.Resampling.BILINEAR),
            dtype=np.float32,
        )
        / 255.0
    )
    if arr.ndim == 2:
        arr = arr[:, :, np.newaxis]

    arr = (arr - mean) / std
    arr = arr.transpose(2, 0, 1)
    inp_tensor = arr[np.newaxis].astype(np.float32)

    raw_outputs = session.run(None, {input_name: inp_tensor})

    # 优先按名字匹配，避免输出顺序变化导致解码错误。
    output_names = [out.name for out in outputs]
    boxes_idx = next((i for i, name in enumerate(output_names) if "dets" in name), None)
    logits_idx = next((i for i, name in enumerate(output_names) if "labels" in name), None)
    if boxes_idx is None or logits_idx is None:
        logger.warning(
            "Name-based ONNX output matching failed (available names: %s). Falling back to shape-based matching.",
            output_names,
        )
        shape_boxes_candidates = [
            i for i, arr_out in enumerate(raw_outputs) if arr_out.ndim == 3 and arr_out.shape[-1] == 4
        ]
        shape_logits_candidates = [
            i for i, arr_out in enumerate(raw_outputs) if arr_out.ndim == 3 and arr_out.shape[-1] != 4
        ]
        if len(shape_boxes_candidates) == 1 and len(shape_logits_candidates) == 1:
            boxes_idx = shape_boxes_candidates[0]
            logits_idx = shape_logits_candidates[0]
        elif len(raw_outputs) == 2:
            logger.warning(
                "ONNX 输出 shape 匹配存在歧义：两个输出最后一维都等于 4。"
                "当前按参考导出顺序回退：output 0 = boxes ('dets')，"
                "output 1 = logits ('labels')。如结果异常，请用 _create_onnx_session() "
                "查看输出名，并设置 LOG_LEVEL=DEBUG。"
            )
            boxes_idx = 0
            logits_idx = 1
        else:
            available_shapes = [list(arr_out.shape) for arr_out in raw_outputs]
            raise ValueError(
                "ONNX 输出 shape 匹配失败。需要一个最后一维等于 4 的 rank-3 boxes 输出，"
                "以及一个最后一维不等于 4 的 rank-3 logits 输出。"
                f"当前输出 shapes: {available_shapes}"
            )

    boxes_cwh = raw_outputs[boxes_idx][0]
    logits = raw_outputs[logits_idx][0, :, :-1]

    logger.debug(
        "Logits stats: shape=%s min=%.3f max=%.3f mean=%.3f",
        logits.shape,
        float(logits.min()),
        float(logits.max()),
        float(logits.mean()),
    )
    one = np.asarray(1, dtype=logits.dtype)
    scores_all = one / (one + np.exp(-logits.clip(-88, 88)))
    scores = scores_all.max(axis=-1)
    cls = scores_all.argmax(axis=-1)
    logger.debug(
        "Scores stats: min=%.3f max=%.3f — detections above threshold %.2f: %d",
        float(scores.min()),
        float(scores.max()),
        threshold,
        int((scores > threshold).sum()),
    )
    keep = scores > threshold

    cx, cy, bw, bh = boxes_cwh[keep].T
    ow, oh = pil_img.size
    xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    xyxy *= np.array([ow, oh, ow, oh], dtype=np.float32)

    return sv.Detections(xyxy=xyxy, confidence=scores[keep], class_id=cls[keep].astype(int)), pil_img
