"""segmentation 模型文件类型定义。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_build_formats import (
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    RKNN_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
)


@dataclass(frozen=True)
class SegmentationModelFileTypes:
    checkpoint_file_type: str
    onnx_file_type: str
    onnx_optimized_file_type: str
    openvino_ir_file_type: str
    tensorrt_engine_file_type: str
    rknn_file_type: str

    def resolve_build_file_type(self, build_format: str) -> str:
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
                "当前 segmentation 模型分类不支持指定 build 格式",
                details={"build_format": build_format},
            )
        return file_type


YOLO_PRIMARY_SEGMENTATION_CHECKPOINT_TYPE = "pytorch-checkpoint"
YOLO_PRIMARY_SEGMENTATION_ONNX_TYPE = "onnx"
YOLO_PRIMARY_SEGMENTATION_ONNX_OPTIMIZED_TYPE = "onnx-optimized"
YOLO_PRIMARY_SEGMENTATION_OPENVINO_IR_TYPE = "openvino-ir"
YOLO_PRIMARY_SEGMENTATION_TENSORRT_ENGINE_TYPE = "tensorrt-engine"
YOLO_PRIMARY_SEGMENTATION_RKNN_TYPE = "rknn"

YOLO_PRIMARY_SEGMENTATION_FILE_TYPES = SegmentationModelFileTypes(
    checkpoint_file_type=YOLO_PRIMARY_SEGMENTATION_CHECKPOINT_TYPE,
    onnx_file_type=YOLO_PRIMARY_SEGMENTATION_ONNX_TYPE,
    onnx_optimized_file_type=YOLO_PRIMARY_SEGMENTATION_ONNX_OPTIMIZED_TYPE,
    openvino_ir_file_type=YOLO_PRIMARY_SEGMENTATION_OPENVINO_IR_TYPE,
    tensorrt_engine_file_type=YOLO_PRIMARY_SEGMENTATION_TENSORRT_ENGINE_TYPE,
    rknn_file_type=YOLO_PRIMARY_SEGMENTATION_RKNN_TYPE,
)
