"""YOLOX OpenVINO runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_core.postprocess import (
    build_yolox_detection_records,
    postprocess_yolox_prediction_array,
)
from backend.service.application.runtime.predictors.yolox.backend import (
    YoloXInferenceImports,
    build_yolox_openvino_compile_properties,
    import_yolox_openvino_module,
    normalize_yolox_openvino_outputs,
    require_yolox_inference_imports,
    resolve_yolox_openvino_compiled_runtime_precision,
    resolve_yolox_openvino_device_name,
    resolve_yolox_openvino_port_dtype,
    resolve_yolox_openvino_port_name,
)
from backend.service.application.runtime.predictors.yolox.contracts import (
    DEFAULT_YOLOX_NMS_THRESHOLD,
    RuntimeTensorSpec,
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
    YoloXRuntimeSessionInfo,
    resolve_yolox_probability,
)
from backend.service.application.runtime.predictors.yolox.io import (
    load_yolox_prediction_image,
    preprocess_yolox_image,
)
from backend.service.application.runtime.predictors.yolox.preview import (
    render_yolox_preview_image_if_requested,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class OpenVINOYoloXRuntimeSession:
    """描述一个已经加载完成并可重复推理的 OpenVINO YOLOX 会话。

    属性：
    - dataset_storage：本地文件存储服务。
    - runtime_target：当前会话绑定的运行时快照。
    - imports：基础推理依赖集合。
    - session：已经加载完成的 OpenVINO CompiledModel。
    - device_name：当前执行 device 名称。
    - input_name：模型输入张量名称。
    - output_name：模型输出张量名称。
    - input_port：模型主输入端口对象。
    - output_port：模型主输出端口对象。
    - compiled_device_name：传给 OpenVINO 的实际 device 选择串。
    - compiled_runtime_precision：当前编译后实际采用的 runtime precision。
    """

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: YoloXInferenceImports,
        session: Any,
        device_name: str,
        input_name: str,
        output_name: str,
        input_port: Any,
        output_port: Any,
        compiled_device_name: str,
        compiled_runtime_precision: str,
    ) -> None:
        """初始化一个已加载完成的 OpenVINO runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：当前会话绑定的运行时快照。
        - imports：基础推理依赖集合。
        - session：已经加载完成的 OpenVINO CompiledModel。
        - device_name：当前执行 device 名称。
        - input_name：模型输入张量名称。
        - output_name：模型输出张量名称。
        - input_port：模型主输入端口对象。
        - output_port：模型主输出端口对象。
        - compiled_device_name：传给 OpenVINO 的实际 device 选择串。
        - compiled_runtime_precision：当前编译后实际采用的 runtime precision。
        """

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
    ) -> OpenVINOYoloXRuntimeSession:
        """加载一次 OpenVINO runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：待加载的运行时快照。

        返回：
        - OpenVINOYoloXRuntimeSession：已完成模型加载的会话对象。
        """

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "当前 predictor 仅支持 openvino runtime_backend",
                details={
                    "runtime_backend": runtime_target.runtime_backend,
                    "model_build_id": runtime_target.model_build_id,
                },
            )

        imports = require_yolox_inference_imports()
        openvino_module = import_yolox_openvino_module()
        compiled_device_name = resolve_yolox_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = build_yolox_openvino_compile_properties(
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
            input_name=resolve_yolox_openvino_port_name(input_port, fallback="images"),
            output_name=resolve_yolox_openvino_port_name(output_port, fallback="predictions"),
            input_port=input_port,
            output_port=output_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_yolox_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用当前常驻会话执行一次单图预测。

        参数：
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """

        decode_started_at = perf_counter()
        image = load_yolox_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_yolox_image(
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

        nms_threshold = resolve_yolox_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_YOLOX_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        predictions = postprocess_yolox_prediction_array(
            prediction_array=normalize_yolox_openvino_outputs(
                outputs=outputs,
                output_port=self.output_port,
                output_name=self.output_name,
                imports=self.imports,
            ),
            np_module=self.imports.np,
            num_classes=len(self.runtime_target.labels),
            conf_thre=request.score_threshold,
            nms_thre=nms_threshold,
        )
        detections = build_yolox_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
            detection_factory=YoloXPredictionDetection,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolox_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            detections=detections,
            save_result_image=request.save_result_image,
        )

        return YoloXPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloXRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=RuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype=resolve_yolox_openvino_port_dtype(self.input_port, fallback="float32"),
                ),
                output_spec=RuntimeTensorSpec(
                    name=self.output_name,
                    shape=(-1, 7),
                    dtype=resolve_yolox_openvino_port_dtype(self.output_port, fallback="float32"),
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
                    "score_threshold": request.score_threshold,
                    "nms_threshold": nms_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )
