"""YOLOv8 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.models.yolov8_core import (
    build_yolov8_export_task_plan,
    resolve_yolov8_segmentation_export_output_names,
)
from backend.service.application.models.yolov8_core.export import (
    YoloV8ExportSourceSession,
    build_yolov8_openvino_ir,
    build_yolov8_tensorrt_engine,
    export_yolov8_onnx,
    validate_yolov8_onnx,
)
from backend.service.domain.files.yolov8_file_types import (
    YOLOV8_ONNX_FILE,
    YOLOV8_ONNX_OPTIMIZED_FILE,
    YOLOV8_OPENVINO_IR_FILE,
    YOLOV8_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolo_model_conversion_runner import (
    LocalYoloModelConversionRunner,
)
from backend.workers.conversion.model_conversion_common import run_conversion_script


YoloV8ConversionRunRequest = ConversionBackendRunRequest
YoloV8ConversionOutput = ConversionBackendOutput
YoloV8ConversionRunResult = ConversionBackendRunResult
YoloV8ConversionRunner = ConversionBackend


class LocalYoloV8ConversionRunner(LocalYoloModelConversionRunner):
    """使用本地文件存储执行 YOLOv8 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLOv8"
    task_runtime_session_classes = {
        "detection": YoloV8ExportSourceSession,
        "classification": YoloV8ExportSourceSession,
        "segmentation": YoloV8ExportSourceSession,
        "pose": YoloV8ExportSourceSession,
        "obb": YoloV8ExportSourceSession,
    }
    task_export_output_names = {
        **LocalYoloModelConversionRunner.task_export_output_names,
        "segmentation": resolve_yolov8_segmentation_export_output_names(),
    }
    onnx_file_type = YOLOV8_ONNX_FILE
    onnx_optimized_file_type = YOLOV8_ONNX_OPTIMIZED_FILE
    openvino_ir_file_type = YOLOV8_OPENVINO_IR_FILE
    tensorrt_engine_file_type = YOLOV8_TENSORRT_ENGINE_FILE
    export_task_plan_builder = staticmethod(build_yolov8_export_task_plan)

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLOv8 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)

    def _export_onnx(
        self,
        *,
        session: object,
        output_object_key: str,
        export_plan: object,
    ) -> dict[str, object]:
        """通过 YOLOv8 core 执行 ONNX 导出。"""

        return export_yolov8_onnx(
            session=session,
            output_path=self.dataset_storage.resolve(output_object_key),
            output_object_key=output_object_key,
            export_plan=export_plan,
        )

    def _validate_onnx(
        self,
        *,
        session: object,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
        export_plan: object,
    ) -> dict[str, object]:
        """通过 YOLOv8 core 执行 ONNX 数值校验。"""

        return validate_yolov8_onnx(
            session=session,
            onnx_path=self.dataset_storage.resolve(onnx_object_key),
            onnx_module=onnx_module,
            onnxruntime_module=onnxruntime_module,
            export_plan=export_plan,
        )

    def _build_openvino_ir(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """通过 YOLOv8 core 构建 OpenVINO IR。"""

        return build_yolov8_openvino_ir(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
            run_conversion_script=run_conversion_script,
        )

    def _build_tensorrt_engine(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """通过 YOLOv8 core 构建 TensorRT engine。"""

        return build_yolov8_tensorrt_engine(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
            run_conversion_script=run_conversion_script,
        )


__all__ = [
    "YoloV8ConversionRunRequest",
    "YoloV8ConversionOutput",
    "YoloV8ConversionRunResult",
    "YoloV8ConversionRunner",
    "LocalYoloV8ConversionRunner",
]
