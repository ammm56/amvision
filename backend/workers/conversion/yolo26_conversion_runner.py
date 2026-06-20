"""YOLO26 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.models.yolo26_core import (
    build_yolo26_export_task_plan,
    resolve_yolo26_segmentation_export_output_names,
)
from backend.service.application.models.yolo26_core.export import (
    Yolo26ExportSourceSession,
    build_yolo26_openvino_ir,
    build_yolo26_tensorrt_engine,
    export_yolo26_onnx,
    validate_yolo26_onnx,
)
from backend.service.domain.files.yolo26_file_types import (
    YOLO26_ONNX_FILE,
    YOLO26_ONNX_OPTIMIZED_FILE,
    YOLO26_OPENVINO_IR_FILE,
    YOLO26_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.model_conversion_common import run_conversion_script
from backend.workers.conversion.yolo_model_conversion_runner import (
    LocalYoloModelConversionRunner,
)


Yolo26ConversionRunRequest = ConversionBackendRunRequest
Yolo26ConversionOutput = ConversionBackendOutput
Yolo26ConversionRunResult = ConversionBackendRunResult
Yolo26ConversionRunner = ConversionBackend


class LocalYolo26ConversionRunner(LocalYoloModelConversionRunner):
    """使用本地文件存储执行 YOLO26 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLO26"
    task_runtime_session_classes = {
        "detection": Yolo26ExportSourceSession,
        "classification": Yolo26ExportSourceSession,
        "segmentation": Yolo26ExportSourceSession,
        "pose": Yolo26ExportSourceSession,
        "obb": Yolo26ExportSourceSession,
    }
    task_export_output_names = {
        **LocalYoloModelConversionRunner.task_export_output_names,
        "segmentation": resolve_yolo26_segmentation_export_output_names(),
    }
    onnx_file_type = YOLO26_ONNX_FILE
    onnx_optimized_file_type = YOLO26_ONNX_OPTIMIZED_FILE
    openvino_ir_file_type = YOLO26_OPENVINO_IR_FILE
    tensorrt_engine_file_type = YOLO26_TENSORRT_ENGINE_FILE
    export_task_plan_builder = staticmethod(build_yolo26_export_task_plan)

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLO26 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)

    def _export_onnx(
        self,
        *,
        session: object,
        output_object_key: str,
        export_plan: object,
    ) -> dict[str, object]:
        """通过 YOLO26 core 执行 ONNX 导出。"""

        return export_yolo26_onnx(
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
        """通过 YOLO26 core 执行 ONNX 数值校验。"""

        return validate_yolo26_onnx(
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
        """通过 YOLO26 core 构建 OpenVINO IR。"""

        return build_yolo26_openvino_ir(
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
        """通过 YOLO26 core 构建 TensorRT engine。"""

        return build_yolo26_tensorrt_engine(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
            run_conversion_script=run_conversion_script,
        )
