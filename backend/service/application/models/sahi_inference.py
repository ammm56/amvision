"""SAHI (Slicing Aided Hyper Inference) 大图推理节点。

实现基于切片的大图推理，通过将大图切分为多个小图分别推理，
然后合并检测结果，提升大图上的检测精度。
"""

from __future__ import annotations

from typing import Any

import numpy as np


def compute_sahi_inference(
    *,
    image: np.ndarray,
    slice_width: int = 640,
    slice_height: int = 640,
    overlap_width: int = 100,
    overlap_height: int = 100,
    inference_callback: Any,
    nms_threshold: float = 0.5,
    score_threshold: float = 0.25,
) -> dict[str, Any]:
    """执行 SAHI 大图推理。

    参数：
    - image: 原始大图 (H, W, 3) BGR 格式
    - slice_width: 切片宽度
    - slice_height: 切片高度
    - overlap_width: 水平重叠宽度
    - overlap_height: 垂直重叠高度
    - inference_callback: 推理回调函数，接收切片图像返回检测结果
    - nms_threshold: NMS 阈值
    - score_threshold: 分数阈值

    返回：
    - dict 包含 detections、slice_count、inference_time_ms
    """
    import time

    image_height, image_width = image.shape[:2]

    # 计算切片位置
    slices = _compute_slice_positions(
        image_width=image_width,
        image_height=image_height,
        slice_width=slice_width,
        slice_height=slice_height,
        overlap_width=overlap_width,
        overlap_height=overlap_height,
    )

    all_detections = []
    total_inference_time = 0.0

    # 对每个切片执行推理
    for slice_info in slices:
        x1, y1, x2, y2 = slice_info["bbox"]

        # 裁剪切片
        slice_image = image[y1:y2, x1:x2]

        # 执行推理
        start_time = time.perf_counter()
        slice_result = inference_callback(slice_image)
        inference_time = (time.perf_counter() - start_time) * 1000
        total_inference_time += inference_time

        # 将切片检测结果转换回原图坐标
        if slice_result and "detections" in slice_result:
            for det in slice_result["detections"]:
                # 将切片坐标转换为原图坐标
                slice_bbox = det.get("bbox_xyxy")
                if slice_bbox:
                    sx1, sy1, sx2, sy2 = slice_bbox
                    # 转换为原图坐标
                    ox1 = sx1 + x1
                    oy1 = sy1 + y1
                    ox2 = sx2 + x1
                    oy2 = sy2 + y1

                    # 检查分数阈值
                    score = det.get("score", 0.0)
                    if score >= score_threshold:
                        all_detections.append({
                            "bbox_xyxy": (ox1, oy1, ox2, oy2),
                            "score": score,
                            "class_id": det.get("class_id"),
                            "class_name": det.get("class_name"),
                        })

    # 执行 NMS 合并所有检测结果
    if all_detections:
        final_detections = _apply_nms(
            detections=all_detections,
            nms_threshold=nms_threshold,
        )
    else:
        final_detections = []

    return {
        "detections": final_detections,
        "slice_count": len(slices),
        "inference_time_ms": total_inference_time,
        "image_width": image_width,
        "image_height": image_height,
    }


def _compute_slice_positions(
    *,
    image_width: int,
    image_height: int,
    slice_width: int,
    slice_height: int,
    overlap_width: int,
    overlap_height: int,
) -> list[dict[str, Any]]:
    """计算所有切片的边界框位置。

    返回：
    - list of dict，每个 dict 包含 bbox: (x1, y1, x2, y2)
    """
    slices = []

    # 计算步长
    step_width = slice_width - overlap_width
    step_height = slice_height - overlap_height

    # 计算切片数量
    num_cols = max(1, (image_width - overlap_width + step_width - 1) // step_width)
    num_rows = max(1, (image_height - overlap_height + step_height - 1) // step_height)

    for row in range(num_rows):
        for col in range(num_cols):
            x1 = col * step_width
            y1 = row * step_height
            x2 = min(x1 + slice_width, image_width)
            y2 = min(y1 + slice_height, image_height)

            # 如果切片太小，调整位置
            if x2 - x1 < slice_width and x2 == image_width:
                x1 = max(0, x2 - slice_width)
            if y2 - y1 < slice_height and y2 == image_height:
                y1 = max(0, y2 - slice_height)

            slices.append({
                "bbox": (x1, y1, x2, y2),
                "row": row,
                "col": col,
            })

    return slices


def _apply_nms(
    *,
    detections: list[dict[str, Any]],
    nms_threshold: float,
) -> list[dict[str, Any]]:
    """应用 NMS 合并重叠检测。

    参数：
    - detections: 所有检测结果列表
    - nms_threshold: NMS 阈值

    返回：
    - 过滤后的检测结果列表
    """
    if not detections:
        return []

    # 按类别分组
    detections_by_class: dict[int, list[dict[str, Any]]] = {}
    for det in detections:
        class_id = det.get("class_id", 0)
        if class_id not in detections_by_class:
            detections_by_class[class_id] = []
        detections_by_class[class_id].append(det)

    final_detections = []

    # 对每个类别分别执行 NMS
    for class_id, class_detections in detections_by_class.items():
        # 按分数降序排序
        class_detections.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        keep_indices = []
        while class_detections:
            # 选择最高分数的检测
            best = class_detections.pop(0)
            keep_indices.append(best)

            # 过滤掉与 best 重叠度过高的检测
            filtered = []
            for det in class_detections:
                iou = _compute_iou(best["bbox_xyxy"], det["bbox_xyxy"])
                if iou < nms_threshold:
                    filtered.append(det)
            class_detections = filtered

        final_detections.extend(keep_indices)

    # 按分数降序排序最终结果
    final_detections.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return final_detections


def _compute_iou(bbox1: tuple[float, float, float, float], bbox2: tuple[float, float, float, float]) -> float:
    """计算两个边界框的 IoU。

    参数：
    - bbox1: (x1, y1, x2, y2)
    - bbox2: (x1, y1, x2, y2)

    返回：
    - IoU 值
    """
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union = area1 + area2 - intersection

    if union <= 0:
        return 0.0

    return intersection / union
