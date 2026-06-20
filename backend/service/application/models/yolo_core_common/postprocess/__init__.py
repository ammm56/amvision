"""YOLO 主线共用 postprocess 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.postprocess.candidates import (
    select_top_scoring_candidate_indices,
)
from backend.service.application.models.yolo_core_common.postprocess.detection import (
    DetectionNmsInputArrays,
    DetectionNmsInputTensors,
    prepare_detection_nms_inputs_array,
    prepare_detection_nms_inputs_tensor,
)
from backend.service.application.models.yolo_core_common.postprocess.segmentation import (
    SegmentationNmsInputArrays,
    SegmentationPostprocessInstance,
    build_segmentation_postprocess_instances,
    extract_mask_segments,
    normalize_segmentation_outputs,
    postprocess_segmentation_prediction_array,
    prepare_segmentation_nms_inputs_array,
)

__all__ = [
    "DetectionNmsInputArrays",
    "DetectionNmsInputTensors",
    "SegmentationNmsInputArrays",
    "SegmentationPostprocessInstance",
    "build_segmentation_postprocess_instances",
    "extract_mask_segments",
    "normalize_segmentation_outputs",
    "postprocess_segmentation_prediction_array",
    "prepare_detection_nms_inputs_array",
    "prepare_detection_nms_inputs_tensor",
    "prepare_segmentation_nms_inputs_array",
    "select_top_scoring_candidate_indices",
]
