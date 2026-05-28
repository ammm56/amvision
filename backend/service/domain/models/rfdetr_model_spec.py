"""RF-DETR 模型规格。"""

from __future__ import annotations
from backend.service.domain.models.model_build_formats import ONNX_BUILD_FORMAT, ONNX_OPTIMIZED_BUILD_FORMAT, OPENVINO_IR_BUILD_FORMAT, TENSORRT_ENGINE_BUILD_FORMAT

RFDETR_DETECTION_SCALES = ("nano", "small", "medium", "large")
RFDETR_SEGMENTATION_SCALES = ("nano", "small", "medium", "large", "xlarge")
RFDETR_SUPPORTED_TASKS = ("detection", "segmentation")
RFDETR_SUPPORTED_BUILD_FORMATS = (ONNX_BUILD_FORMAT, ONNX_OPTIMIZED_BUILD_FORMAT, OPENVINO_IR_BUILD_FORMAT, TENSORRT_ENGINE_BUILD_FORMAT)
RFDETR_DEFAULT_DATASET_FORMAT = "coco-detection-v1"
