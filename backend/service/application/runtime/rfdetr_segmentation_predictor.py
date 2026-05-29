"""RF-DETR segmentation 推理实现。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_segmentation_model import (
    build_rfdetr_segmentation_model,
)
from backend.service.application.runtime.detection_runtime_support import (
    import_onnxruntime_module,
    load_prediction_image,
    render_preview_image,
    resolve_onnxruntime_providers,
)
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_RF_SEGMENTATION_INPUT_SIZES = {
    "nano": 384,
    "s": 512,
    "m": 576,
    "l": 704,
    "x": 768,
}


class PyTorchRfdetrSegmentationRuntimeSession:
    """PyTorch RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        model: Any,
        device_name: str,
        runtime_precision: str,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "PyTorchRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "RF-DETR segmentation 当前仅支持 pytorch",
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

        imports = type("_RfdetrSegmentationPredictorImports", (), {"cv2": cv2, "np": np, "torch": torch})()
        input_edge = _RF_SEGMENTATION_INPUT_SIZES.get(runtime_target.model_scale, 384)
        model = build_rfdetr_segmentation_model(
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            pretrained_path=str(runtime_target.runtime_artifact_path)
            if runtime_target.runtime_artifact_path
            else None,
        )
        device_name = runtime_target.device_name or "cpu"
        if device_name == "cuda" and torch.cuda.is_available():
            device_name = "cuda:0"
        model.to(device_name)
        if runtime_target.runtime_precision == "fp16" and device_name.startswith("cuda"):
            model.half()
        model.eval()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            model=model,
            device_name=device_name,
            runtime_precision=runtime_target.runtime_precision or "fp32",
            input_size=(input_edge, input_edge),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_height, input_width = self.input_size
        resized_image = imports.cv2.resize(
            image,
            (input_width, input_height),
            interpolation=imports.cv2.INTER_LINEAR,
        )
        tensor = resized_image[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        input_tensor = imports.torch.from_numpy(tensor).unsqueeze(0).to(self.device_name).float()
        if self.runtime_precision == "fp16" and self.device_name.startswith("cuda"):
            input_tensor = input_tensor.half()
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        inference_mode = getattr(imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        target_sizes = imports.torch.tensor(
            [[float(image.shape[0]), float(image.shape[1])]],
            device=input_tensor.device,
        )
        processed = self.model.postprocess(outputs, target_sizes)
        instances = _build_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image and instances:
            preview_image_bytes = render_preview_image(
                cv2_module=imports.cv2,
                image=image,
                detections=tuple(_as_preview_detection(item) for item in instances),
            )

        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, input_height, input_width),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_specs=(
                    SegmentationRuntimeTensorSpec(
                        name="pred_logits",
                        shape=tuple(int(item) for item in outputs["pred_logits"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="pred_boxes",
                        shape=tuple(int(item) for item in outputs["pred_boxes"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="pred_masks",
                        shape=tuple(int(item) for item in outputs["pred_masks"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend=self.runtime_target.runtime_backend,
                        runtime_precision=self.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class OnnxRuntimeRfdetrSegmentationRuntimeSession:
    """ONNX Runtime RF-DETR segmentation 会话。"""

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
        input_name: str,
        output_names: tuple[str, ...],
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.input_name = input_name
        self.output_names = output_names
        self.postprocess_model = postprocess_model
        self.input_size = input_size
        self.device_name = runtime_target.device_name or "cpu"
        self.runtime_precision = runtime_target.runtime_precision or "fp32"

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 仅支持 onnxruntime",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if (runtime_target.runtime_precision or "fp32") != "fp32":
            raise InvalidRequestError(
                "当前 RF-DETR segmentation onnxruntime session 仅支持 fp32",
                details={"runtime_precision": runtime_target.runtime_precision},
            )
        import cv2
        import numpy as np
        import torch

        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(
            onnxruntime_module=onnxruntime_module,
            requested_device_name=runtime_target.device_name,
        )
        session = onnxruntime_module.InferenceSession(
            str(runtime_target.runtime_artifact_path),
            providers=providers,
        )
        input_edge = _RF_SEGMENTATION_INPUT_SIZES.get(runtime_target.model_scale, 384)
        postprocess_model = build_rfdetr_segmentation_model(
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
        )
        postprocess_model.eval()
        imports = type(
            "_RfdetrSegmentationOnnxImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            input_name=session.get_inputs()[0].name,
            output_names=tuple(item.name for item in session.get_outputs()),
            postprocess_model=postprocess_model,
            input_size=(input_edge, input_edge),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_height, input_width = self.input_size
        resized_image = imports.cv2.resize(
            image,
            (input_width, input_height),
            interpolation=imports.cv2.INTER_LINEAR,
        )
        input_array = (
            resized_image[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        )
        input_array = imports.np.expand_dims(input_array, axis=0)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        raw_outputs = self.session.run(
            list(self.output_names),
            {self.input_name: input_array},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        pred_logits = imports.torch.from_numpy(raw_outputs[0])
        pred_boxes = imports.torch.from_numpy(raw_outputs[1])
        pred_masks = imports.torch.from_numpy(raw_outputs[2])
        processed = self.postprocess_model.postprocess(
            {
                "pred_logits": pred_logits,
                "pred_boxes": pred_boxes,
                "pred_masks": pred_masks,
            },
            imports.torch.tensor(
                [[float(image.shape[0]), float(image.shape[1])]],
                dtype=imports.torch.float32,
            ),
        )
        instances = _build_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image and instances:
            preview_image_bytes = render_preview_image(
                cv2_module=imports.cv2,
                image=image,
                detections=tuple(_as_preview_detection(item) for item in instances),
            )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name="onnxruntime",
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, input_height, input_width),
                    dtype="float32",
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=name,
                        shape=tuple(int(item) for item in array.shape),
                        dtype="float32",
                    )
                    for name, array in zip(self.output_names, raw_outputs, strict=False)
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend="onnxruntime",
                        runtime_precision="fp32",
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


def _build_segmentation_instances(
    *,
    cv2_module: Any,
    scores: Any,
    labels: Any,
    boxes_xyxy: Any,
    masks: Any,
    label_names: tuple[str, ...],
    score_threshold: float,
    mask_threshold: float,
) -> tuple[SegmentationPredictionInstance, ...]:
    result: list[SegmentationPredictionInstance] = []
    if scores is None or labels is None or boxes_xyxy is None or masks is None:
        return ()
    score_count = min(int(scores.shape[0]), int(scores.shape[1]))
    for index in range(score_count):
        score = float(scores[0, index].item())
        if score < score_threshold:
            continue
        class_id = int(labels[0, index].item())
        box = boxes_xyxy[0, index]
        binary_mask = (masks[0, index].sigmoid() >= mask_threshold).detach().cpu().numpy().astype("uint8")
        contours, _ = cv2_module.findContours(binary_mask, cv2_module.RETR_EXTERNAL, cv2_module.CHAIN_APPROX_SIMPLE)
        segments = []
        for contour in contours:
            if contour.shape[0] < 3:
                continue
            polygon = tuple(
                (round(float(point[0][0]), 4), round(float(point[0][1]), 4))
                for point in contour
            )
            if len(polygon) >= 3:
                segments.append(polygon)
        result.append(
            SegmentationPredictionInstance(
                bbox_xyxy=(
                    round(float(box[0].item()), 4),
                    round(float(box[1].item()), 4),
                    round(float(box[2].item()), 4),
                    round(float(box[3].item()), 4),
                ),
                score=round(score, 6),
                class_id=class_id,
                class_name=label_names[class_id] if 0 <= class_id < len(label_names) else None,
                segments=tuple(segments),
                mask_area=float(binary_mask.sum()),
            )
        )
    return tuple(result)


def _as_preview_detection(instance: SegmentationPredictionInstance) -> dict[str, object]:
    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
    }
