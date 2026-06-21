"""YOLO11 classification OpenVINO runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.predictors.yolo11.classification.backend import (
    build_yolo11_classification_openvino_compile_properties,
    import_yolo11_classification_openvino_module,
    normalize_yolo11_classification_outputs_for_backend,
    require_yolo11_classification_inference_imports,
    resolve_yolo11_classification_openvino_compiled_runtime_precision,
    resolve_yolo11_classification_openvino_device_name,
    resolve_yolo11_classification_openvino_port_dtype,
    resolve_yolo11_classification_openvino_port_name,
    resolve_yolo11_classification_single_output,
)
from backend.service.application.runtime.predictors.yolo11.classification.contracts import (
    Yolo11ClassificationPredictionExecutionResult,
    Yolo11ClassificationPredictionRequest,
    Yolo11ClassificationRuntimeSessionInfo,
    Yolo11ClassificationRuntimeTensorSpec,
    resolve_yolo11_classification_top_k,
)
from backend.service.application.runtime.predictors.yolo11.classification.io import (
    load_yolo11_classification_prediction_image,
    preprocess_yolo11_classification_image,
)
from backend.service.application.runtime.predictors.yolo11.classification.postprocess import (
    build_yolo11_classification_runtime_categories,
)
from backend.service.application.runtime.predictors.yolo11.classification.preview import (
    render_yolo11_classification_preview_image_if_requested,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class OpenVINOYolo11ClassificationRuntimeSession:
    """已经加载完成并可重复推理的 OpenVINO YOLO11 classification 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"
    task_type = "classification"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        session: Any,
        device_name: str,
        input_name: str,
        output_name: str,
        input_port: Any,
        output_port: Any,
        compiled_device_name: str,
        compiled_runtime_precision: str,
    ) -> None:
        """初始化 OpenVINO YOLO11 classification 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_name = output_name
        self.input_port = input_port
        self.output_port = output_port
        self.compiled_device_name = compiled_device_name
        self.compiled_runtime_precision = compiled_runtime_precision

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OpenVINOYolo11ClassificationRuntimeSession":
        """加载一套 OpenVINO YOLO11 classification 会话。"""

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "当前 YOLO11 classification predictor 仅支持 openvino runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLO11 classification predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )

        imports = require_yolo11_classification_inference_imports()
        openvino_module = import_yolo11_classification_openvino_module()
        compiled_device_name = resolve_yolo11_classification_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = build_yolo11_classification_openvino_compile_properties(
            openvino_module=openvino_module,
            runtime_precision=runtime_target.runtime_precision,
            requested_device_name=runtime_target.device_name,
        )
        session = openvino_module.Core().compile_model(
            str(runtime_target.runtime_artifact_path),
            compiled_device_name,
            compile_properties,
        )
        input_port = session.input(0)
        output_port = session.output(0)
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name,
            input_name=resolve_yolo11_classification_openvino_port_name(
                input_port, fallback="images"
            ),
            output_name=resolve_yolo11_classification_openvino_port_name(
                output_port,
                fallback="probabilities",
            ),
            input_port=input_port,
            output_port=output_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_yolo11_classification_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(
        self,
        request: Yolo11ClassificationPredictionRequest,
    ) -> Yolo11ClassificationPredictionExecutionResult:
        """执行一次 OpenVINO YOLO11 classification 预测。"""

        top_k = resolve_yolo11_classification_top_k(
            request=request,
            class_count=len(self.runtime_target.labels),
        )

        decode_started_at = perf_counter()
        image = load_yolo11_classification_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor = preprocess_yolo11_classification_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            self.imports.np.float32,
            copy=False,
        )
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        raw_output = resolve_yolo11_classification_single_output(
            outputs=outputs,
            output_port=self.output_port,
            output_name=self.output_name,
        )
        probabilities, logits = normalize_yolo11_classification_outputs_for_backend(
            outputs=[raw_output],
            np_module=self.imports.np,
        )
        categories = build_yolo11_classification_runtime_categories(
            np_module=self.imports.np,
            probabilities=probabilities,
            logits=logits,
            labels=self.runtime_target.labels,
            top_k=top_k,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolo11_classification_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            categories=categories,
            save_result_image=request.save_result_image,
        )
        return Yolo11ClassificationPredictionExecutionResult(
            categories=categories,
            top_category=categories[0] if categories else None,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=Yolo11ClassificationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=Yolo11ClassificationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(
                        1,
                        3,
                        self.runtime_target.input_size[0],
                        self.runtime_target.input_size[1],
                    ),
                    dtype=resolve_yolo11_classification_openvino_port_dtype(
                        self.input_port,
                        fallback="float32",
                    ),
                ),
                output_spec=Yolo11ClassificationRuntimeTensorSpec(
                    name=self.output_name,
                    shape=tuple(int(item) for item in probabilities.shape),
                    dtype=resolve_yolo11_classification_openvino_port_dtype(
                        self.output_port,
                        fallback="float32",
                    ),
                ),
                metadata={
                    "model_version_id": self.runtime_target.model_version_id,
                    "model_build_id": self.runtime_target.model_build_id,
                    "runtime_precision": self.runtime_target.runtime_precision,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend=self.runtime_target.runtime_backend,
                        runtime_precision=self.runtime_target.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "top_k": top_k,
                    "class_count": len(self.runtime_target.labels),
                    "logits_available": logits is not None,
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )


__all__ = ["OpenVINOYolo11ClassificationRuntimeSession"]
