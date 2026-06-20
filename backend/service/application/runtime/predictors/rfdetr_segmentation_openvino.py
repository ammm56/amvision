"""RF-DETR segmentation OpenVINO runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.rfdetr_core.runtime import (
    build_rfdetr_runtime_postprocess_model,
    resolve_rfdetr_runtime_input_size,
    resolve_rfdetr_runtime_output_names,
)
from backend.service.application.runtime.predictors.rfdetr_io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.predictors.rfdetr_segmentation_result import (
    build_rfdetr_segmentation_instances,
    postprocess_rfdetr_segmentation_outputs,
    render_rfdetr_segmentation_preview,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.contracts.segmentation import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.support.detection import (
    build_openvino_compile_properties,
    import_openvino_module,
    resolve_openvino_compiled_runtime_precision,
    resolve_openvino_device_name,
    resolve_openvino_port_dtype,
    resolve_openvino_port_name,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class OpenVINORfdetrSegmentationRuntimeSession:
    """OpenVINO RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        session: Any,
        device_name: str,
        input_name: str,
        output_names: tuple[str, ...],
        input_port: Any,
        output_ports: tuple[Any, ...],
        compiled_device_name: str,
        compiled_runtime_precision: str,
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names
        self.input_port = input_port
        self.output_ports = output_ports
        self.compiled_device_name = compiled_device_name
        self.compiled_runtime_precision = compiled_runtime_precision
        self.postprocess_model = postprocess_model
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OpenVINORfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 仅支持 openvino",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        import cv2
        import numpy as np
        import torch

        openvino_module = import_openvino_module()
        compiled_device_name = resolve_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = build_openvino_compile_properties(
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
        all_output_ports = tuple(session.output(index) for index in range(len(session.outputs)))
        if len(all_output_ports) < 3:
            raise ServiceConfigurationError(
                "OpenVINO RF-DETR segmentation 模型输出数量不足",
                details={"output_count": len(all_output_ports)},
            )
        all_output_names = tuple(
            resolve_openvino_port_name(port, fallback=f"output-{index}")
            for index, port in enumerate(all_output_ports)
        )
        resolved_output_names = resolve_rfdetr_runtime_output_names(
            task_type=runtime_target.task_type,
            output_names=all_output_names,
        )
        output_ports = tuple(
            all_output_ports[all_output_names.index(output_name)]
            for output_name in resolved_output_names
        )
        imports = type(
            "_RfdetrSegmentationOpenVinoImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name or "auto",
            input_name=resolve_openvino_port_name(input_port, fallback="images"),
            output_names=resolved_output_names,
            input_port=input_port,
            output_ports=output_ports,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
            postprocess_model=build_rfdetr_runtime_postprocess_model(
                task_type=runtime_target.task_type,
            ),
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        image, decode_ms = load_rfdetr_runtime_input_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        input_array, preprocess_ms = build_rfdetr_input_array(
            cv2_module=imports.cv2,
            np_module=imports.np,
            image=image,
            input_size=self.input_size,
        )

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_array})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        raw_tensors = []
        for index, output_port in enumerate(self.output_ports):
            raw_tensor = outputs.get(output_port)
            if raw_tensor is None:
                raw_tensor = outputs.get(self.output_names[index])
            if raw_tensor is None:
                raise InvalidRequestError(
                    "OpenVINO segmentation 推理输出缺少必要张量",
                    details={"missing_output_name": self.output_names[index]},
                )
            raw_tensors.append(raw_tensor)
        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.postprocess_model,
            raw_outputs={
                "pred_logits": raw_tensors[0],
                "pred_boxes": raw_tensors[1],
                "pred_masks": raw_tensors[2],
            },
            image_height=int(image.shape[0]),
            image_width=int(image.shape[1]),
        )
        instances = build_rfdetr_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        preview_image_bytes = render_rfdetr_segmentation_preview(
            cv2_module=imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name="openvino",
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.input_size[0], self.input_size[1]),
                    dtype=resolve_openvino_port_dtype(self.input_port, fallback="float32"),
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=self.output_names[index],
                        shape=tuple(int(item) for item in raw_tensors[index].shape),
                        dtype=resolve_openvino_port_dtype(output_port, fallback="float32"),
                    )
                    for index, output_port in enumerate(self.output_ports)
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend="openvino",
                        runtime_precision=self.runtime_target.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )
