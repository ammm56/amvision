"""YOLO11 文件类型定义。"""

from __future__ import annotations

from typing import Final

from backend.service.domain.files.detection_model_file_types import (
    YOLO11_DETECTION_FILE_TYPES,
)


YOLO11_CHECKPOINT_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.checkpoint_file_type
YOLO11_ONNX_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.onnx_file_type
YOLO11_ONNX_OPTIMIZED_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.onnx_optimized_file_type
YOLO11_OPENVINO_IR_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.openvino_ir_file_type
YOLO11_TENSORRT_ENGINE_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.tensorrt_engine_file_type
YOLO11_RKNN_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.rknn_file_type

YOLO11_LABEL_MAP_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.label_map_file_type
YOLO11_TRAINING_METRICS_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.training_metrics_file_type
YOLO11_EVAL_REPORT_FILE: Final[str] = YOLO11_DETECTION_FILE_TYPES.eval_report_file_type
