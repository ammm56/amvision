"""YOLOX 文件类型定义。"""

from __future__ import annotations

from typing import Final

from backend.service.domain.files.detection_model_file_types import (
    YOLOX_DETECTION_FILE_TYPES,
)


# YOLOX 模型主文件类型。
YOLOX_CHECKPOINT_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.checkpoint_file_type
YOLOX_ONNX_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.onnx_file_type
YOLOX_ONNX_OPTIMIZED_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.onnx_optimized_file_type
YOLOX_OPENVINO_IR_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.openvino_ir_file_type
YOLOX_TENSORRT_ENGINE_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.tensorrt_engine_file_type
YOLOX_RKNN_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.rknn_file_type

# YOLOX 辅助输出文件类型。
YOLOX_LABEL_MAP_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.label_map_file_type
YOLOX_TRAINING_METRICS_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.training_metrics_file_type
YOLOX_EVAL_REPORT_FILE: Final[str] = YOLOX_DETECTION_FILE_TYPES.eval_report_file_type


# 当前支持登记的全部 YOLOX file type。
YOLOX_FILE_TYPES: Final[tuple[str, ...]] = (
    YOLOX_CHECKPOINT_FILE,
    YOLOX_ONNX_FILE,
    YOLOX_ONNX_OPTIMIZED_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
    YOLOX_RKNN_FILE,
    YOLOX_LABEL_MAP_FILE,
    YOLOX_TRAINING_METRICS_FILE,
    YOLOX_EVAL_REPORT_FILE,
)
