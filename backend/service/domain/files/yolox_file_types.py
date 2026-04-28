"""YOLOX 文件类型定义。"""

from __future__ import annotations

from typing import Final


# YOLOX 模型主文件类型。
YOLOX_CHECKPOINT_FILE: Final[str] = "yolox-checkpoint"
YOLOX_ONNX_FILE: Final[str] = "yolox-onnx"
YOLOX_OPENVINO_IR_FILE: Final[str] = "yolox-openvino-ir"
YOLOX_TENSORRT_ENGINE_FILE: Final[str] = "yolox-tensorrt-engine"

# YOLOX 辅助输出文件类型。
YOLOX_LABEL_MAP_FILE: Final[str] = "yolox-label-map"
YOLOX_TRAINING_METRICS_FILE: Final[str] = "yolox-training-metrics"
YOLOX_EVAL_REPORT_FILE: Final[str] = "yolox-eval-report"


# 当前支持登记的全部 YOLOX file type。
YOLOX_FILE_TYPES: Final[tuple[str, ...]] = (
    YOLOX_CHECKPOINT_FILE,
    YOLOX_ONNX_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
    YOLOX_LABEL_MAP_FILE,
    YOLOX_TRAINING_METRICS_FILE,
    YOLOX_EVAL_REPORT_FILE,
)