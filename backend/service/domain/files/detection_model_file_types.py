"""detection 模型文件类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_build_formats import (
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    RKNN_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
)


@dataclass(frozen=True)
class DetectionModelFileTypes:
    """描述一个 detection 模型分类对应的平台文件类型集合。

    字段：
    - checkpoint_file_type：原始训练权重或 checkpoint 文件类型。
    - onnx_file_type：ONNX 文件类型。
    - onnx_optimized_file_type：优化后 ONNX 文件类型。
    - openvino_ir_file_type：OpenVINO IR 主文件类型。
    - tensorrt_engine_file_type：TensorRT engine 文件类型。
    - rknn_file_type：RKNN 文件类型。
    - label_map_file_type：标签文件类型。
    - training_metrics_file_type：训练指标文件类型。
    - eval_report_file_type：评估报告文件类型。
    """

    checkpoint_file_type: str
    onnx_file_type: str
    onnx_optimized_file_type: str
    openvino_ir_file_type: str
    tensorrt_engine_file_type: str
    rknn_file_type: str
    label_map_file_type: str
    training_metrics_file_type: str
    eval_report_file_type: str

    def resolve_build_file_type(self, build_format: str) -> str:
        """把 build 格式映射到当前 detection 模型分类对应的文件类型。"""

        build_file_type_map = {
            ONNX_BUILD_FORMAT: self.onnx_file_type,
            ONNX_OPTIMIZED_BUILD_FORMAT: self.onnx_optimized_file_type,
            OPENVINO_IR_BUILD_FORMAT: self.openvino_ir_file_type,
            TENSORRT_ENGINE_BUILD_FORMAT: self.tensorrt_engine_file_type,
            RKNN_BUILD_FORMAT: self.rknn_file_type,
        }
        file_type = build_file_type_map.get(build_format)
        if file_type is None:
            raise InvalidRequestError(
                "当前 detection 模型分类不支持指定 build 格式",
                details={"build_format": build_format},
            )
        return file_type


YOLOX_DETECTION_FILE_TYPES: Final[DetectionModelFileTypes] = DetectionModelFileTypes(
    checkpoint_file_type="yolox-checkpoint",
    onnx_file_type="yolox-onnx",
    onnx_optimized_file_type="yolox-onnx-optimized",
    openvino_ir_file_type="yolox-openvino-ir",
    tensorrt_engine_file_type="yolox-tensorrt-engine",
    rknn_file_type="yolox-rknn",
    label_map_file_type="yolox-label-map",
    training_metrics_file_type="yolox-training-metrics",
    eval_report_file_type="yolox-eval-report",
)


YOLOV8_DETECTION_FILE_TYPES: Final[DetectionModelFileTypes] = DetectionModelFileTypes(
    checkpoint_file_type="yolov8-checkpoint",
    onnx_file_type="yolov8-onnx",
    onnx_optimized_file_type="yolov8-onnx-optimized",
    openvino_ir_file_type="yolov8-openvino-ir",
    tensorrt_engine_file_type="yolov8-tensorrt-engine",
    rknn_file_type="yolov8-rknn",
    label_map_file_type="yolov8-label-map",
    training_metrics_file_type="yolov8-training-metrics",
    eval_report_file_type="yolov8-eval-report",
)


YOLO11_DETECTION_FILE_TYPES: Final[DetectionModelFileTypes] = DetectionModelFileTypes(
    checkpoint_file_type="yolo11-checkpoint",
    onnx_file_type="yolo11-onnx",
    onnx_optimized_file_type="yolo11-onnx-optimized",
    openvino_ir_file_type="yolo11-openvino-ir",
    tensorrt_engine_file_type="yolo11-tensorrt-engine",
    rknn_file_type="yolo11-rknn",
    label_map_file_type="yolo11-label-map",
    training_metrics_file_type="yolo11-training-metrics",
    eval_report_file_type="yolo11-eval-report",
)


YOLO26_DETECTION_FILE_TYPES: Final[DetectionModelFileTypes] = DetectionModelFileTypes(
    checkpoint_file_type="yolo26-checkpoint",
    onnx_file_type="yolo26-onnx",
    onnx_optimized_file_type="yolo26-onnx-optimized",
    openvino_ir_file_type="yolo26-openvino-ir",
    tensorrt_engine_file_type="yolo26-tensorrt-engine",
    rknn_file_type="yolo26-rknn",
    label_map_file_type="yolo26-label-map",
    training_metrics_file_type="yolo26-training-metrics",
    eval_report_file_type="yolo26-eval-report",
)
