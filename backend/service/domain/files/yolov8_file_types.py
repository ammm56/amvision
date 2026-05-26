"""YOLOv8 文件类型定义。"""

from __future__ import annotations

from typing import Final

from backend.service.domain.files.detection_model_file_types import (
    YOLOV8_DETECTION_FILE_TYPES,
)


YOLOV8_CHECKPOINT_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.checkpoint_file_type
YOLOV8_ONNX_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.onnx_file_type
YOLOV8_ONNX_OPTIMIZED_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.onnx_optimized_file_type
YOLOV8_OPENVINO_IR_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.openvino_ir_file_type
YOLOV8_TENSORRT_ENGINE_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.tensorrt_engine_file_type
YOLOV8_RKNN_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.rknn_file_type

YOLOV8_LABEL_MAP_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.label_map_file_type
YOLOV8_TRAINING_METRICS_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.training_metrics_file_type
YOLOV8_EVAL_REPORT_FILE: Final[str] = YOLOV8_DETECTION_FILE_TYPES.eval_report_file_type


YOLOV8_FILE_TYPES: Final[tuple[str, ...]] = (
    YOLOV8_CHECKPOINT_FILE,
    YOLOV8_ONNX_FILE,
    YOLOV8_ONNX_OPTIMIZED_FILE,
    YOLOV8_OPENVINO_IR_FILE,
    YOLOV8_TENSORRT_ENGINE_FILE,
    YOLOV8_RKNN_FILE,
    YOLOV8_LABEL_MAP_FILE,
    YOLOV8_TRAINING_METRICS_FILE,
    YOLOV8_EVAL_REPORT_FILE,
)
