"""RF-DETR 单图推理实现。"""

from __future__ import annotations
from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.rfdetr_model import RfdetrModel, build_rfdetr_model
from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionPredictionDetection, DetectionPredictionExecutionResult,
    DetectionPredictionRequest, DetectionRuntimeSessionInfo, DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.detection_runtime_support import (
    load_prediction_image, render_preview_image,
    import_onnxruntime_module, resolve_onnxruntime_providers, require_inference_imports,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot, describe_runtime_execution_mode
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

_RF_INPUT_SIZES = {"nano": 384, "s": 512, "m": 576, "l": 704}


class PyTorchRfdetrRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch RF-DETR 会话。"""

    model_type = "rfdetr"; model_label = "RF-DETR"; task_type = "detection"

    def __init__(self, *, dataset_storage, runtime_target, imports, model, device_name, runtime_precision, input_size):
        self.dataset_storage = dataset_storage; self.runtime_target = runtime_target; self.imports = imports
        self.model = model; self.device_name = device_name; self.runtime_precision = runtime_precision; self.input_size = input_size

    @classmethod
    def load(cls, *, dataset_storage: LocalDatasetStorage, runtime_target: RuntimeTargetSnapshot) -> "PyTorchRfdetrRuntimeSession":
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError("RF-DETR predictor 仅支持 pytorch", details={"runtime_backend": runtime_target.runtime_backend})
        import cv2, numpy as np, torch
        imp = type("_I", (), {"cv2": cv2, "np": np, "torch": torch})()
        input_size = _RF_INPUT_SIZES.get(runtime_target.model_scale, 384)
        model = build_rfdetr_model(model_scale=runtime_target.model_scale, num_classes=len(runtime_target.labels), pretrained_path=str(runtime_target.runtime_artifact_path) if runtime_target.runtime_artifact_path else None)
        dn = runtime_target.device_name or "cpu"
        if dn == "cuda" and torch.cuda.is_available(): dn = "cuda:0"
        model.to(dn); model.eval()
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imp, model=model, device_name=dn, runtime_precision=runtime_target.runtime_precision or "fp32", input_size=(input_size, input_size))

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        return _predict(self, request, is_onnx=False)


class OnnxRuntimeRfdetrRuntimeSession:
    """已经加载完成并可重复推理的 ONNX RF-DETR 会话。"""

    model_type = "rfdetr"; model_label = "RF-DETR"; task_type = "detection"

    def __init__(self, *, dataset_storage, runtime_target, imports, session, device_name, input_name, output_names, input_size):
        self.dataset_storage = dataset_storage; self.runtime_target = runtime_target; self.imports = imports
        self.session = session; self.device_name = device_name; self.input_name = input_name
        self.output_names = output_names; self.input_size = input_size

    @classmethod
    def load(cls, *, dataset_storage: LocalDatasetStorage, runtime_target: RuntimeTargetSnapshot) -> "OnnxRuntimeRfdetrRuntimeSession":
        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError("RF-DETR predictor 仅支持 onnxruntime", details={"runtime_backend": runtime_target.runtime_backend})
        import cv2, numpy as np, torch
        imp = type("_I", (), {"cv2": cv2, "np": np, "torch": torch})()
        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(onnxruntime_module=onnxruntime_module, requested_device_name=runtime_target.device_name)
        session = onnxruntime_module.InferenceSession(str(runtime_target.runtime_artifact_path), providers=providers)
        input_size = _RF_INPUT_SIZES.get(runtime_target.model_scale, 384)
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imp, session=session, device_name=runtime_target.device_name, input_name=session.get_inputs()[0].name, output_names=tuple(o.name for o in session.get_outputs()), input_size=(input_size, input_size))

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        return _predict_onnx(self, request)


def _predict(session_obj, request, is_onnx=False):
    imp = session_obj.imports; t0 = perf_counter()
    image = load_prediction_image(cv2_module=imp.cv2, np_module=imp.np, dataset_storage=session_obj.dataset_storage, request=request)
    dms = round((perf_counter() - t0) * 1000, 3)
    t1 = perf_counter(); ih, iw = session_obj.input_size
    resized = imp.cv2.resize(image, (iw, ih), interpolation=imp.cv2.INTER_LINEAR)
    tensor = resized[:, :, ::-1].transpose(2, 0, 1).astype(imp.np.float32) / 255.0
    tensor = imp.torch.from_numpy(tensor).unsqueeze(0).to(session_obj.device_name)
    pms = round((perf_counter() - t1) * 1000, 3)
    t2 = perf_counter()
    with imp.torch.no_grad(): outputs = session_obj.model(tensor)
    ims = round((perf_counter() - t2) * 1000, 3)
    t3 = perf_counter(); ts = imp.torch.tensor([[float(image.shape[0]), float(image.shape[1])]], device=session_obj.device_name)
    proc = session_obj.model.postprocess(outputs, ts)
    dets = _build_detections(proc, session_obj.runtime_target.labels, request.score_threshold)
    pms2 = round((perf_counter() - t3) * 1000, 3); lat = dms + pms + ims + pms2
    preview = None
    if request.save_result_image and dets: preview = render_preview_image(cv2_module=imp.cv2, image=image, detections=dets)
    return DetectionPredictionExecutionResult(detections=dets, latency_ms=round(lat, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]), preview_image_bytes=preview, runtime_session_info=DetectionRuntimeSessionInfo(backend_name=session_obj.runtime_target.runtime_backend, model_uri=session_obj.runtime_target.runtime_artifact_storage_uri, device_name=session_obj.device_name, input_spec=DetectionRuntimeTensorSpec(name="images", shape=(1, 3, ih, iw), dtype="float32"), output_specs=(DetectionRuntimeTensorSpec(name="predictions", shape=(1, 300, 4), dtype="float32"),), metadata={"model_type": "rfdetr", "model_scale": session_obj.runtime_target.model_scale, "decode_ms": dms, "preprocess_ms": pms, "infer_ms": ims, "postprocess_ms": pms2}))


def _predict_onnx(session_obj, request):
    imp = session_obj.imports; t0 = perf_counter()
    image = load_prediction_image(cv2_module=imp.cv2, np_module=imp.np, dataset_storage=session_obj.dataset_storage, request=request)
    dms = round((perf_counter() - t0) * 1000, 3)
    t1 = perf_counter(); ih, iw = session_obj.input_size
    resized = imp.cv2.resize(image, (iw, ih), interpolation=imp.cv2.INTER_LINEAR)
    tensor = resized[:, :, ::-1].transpose(2, 0, 1).astype(imp.np.float32) / 255.0
    tensor = imp.np.expand_dims(tensor, axis=0)
    pms = round((perf_counter() - t1) * 1000, 3)
    t2 = perf_counter(); onnx_outputs = session_obj.session.run(list(session_obj.output_names), {session_obj.input_name: tensor})
    ims = round((perf_counter() - t2) * 1000, 3)
    t3 = perf_counter(); ts = imp.torch.tensor([[float(image.shape[0]), float(image.shape[1])]])
    pred_logits = imp.torch.from_numpy(onnx_outputs[0]) if onnx_outputs else imp.torch.zeros(1, 300, 91)
    pred_boxes = imp.torch.from_numpy(onnx_outputs[1]) if len(onnx_outputs) > 1 else imp.torch.zeros(1, 300, 4)
    outputs = {"pred_logits": pred_logits, "pred_boxes": pred_boxes}
    model = build_rfdetr_model(model_scale=session_obj.runtime_target.model_scale, num_classes=len(session_obj.runtime_target.labels))
    model.to("cpu"); model.eval()
    proc = model.postprocess(outputs, ts)
    dets = _build_detections(proc, session_obj.runtime_target.labels, request.score_threshold)
    pms2 = round((perf_counter() - t3) * 1000, 3); lat = dms + pms + ims + pms2
    preview = None
    if request.save_result_image and dets: preview = render_preview_image(cv2_module=imp.cv2, image=image, detections=dets)
    return DetectionPredictionExecutionResult(detections=dets, latency_ms=round(lat, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]), preview_image_bytes=preview, runtime_session_info=DetectionRuntimeSessionInfo(backend_name=session_obj.runtime_target.runtime_backend, model_uri=session_obj.runtime_target.runtime_artifact_storage_uri, device_name=session_obj.device_name, input_spec=DetectionRuntimeTensorSpec(name=session_obj.input_name, shape=(1, 3, ih, iw), dtype="float32"), output_specs=(DetectionRuntimeTensorSpec(name=session_obj.output_names[0] if session_obj.output_names else "predictions", shape=(1, 300, 4), dtype="float32"),), metadata={"model_type": "rfdetr", "decode_ms": dms, "preprocess_ms": pms, "infer_ms": ims, "postprocess_ms": pms2}))


def _build_detections(proc: dict, labels: tuple[str, ...], thr: float) -> tuple[DetectionPredictionDetection, ...]:
    scores = proc.get("scores"); cids = proc.get("labels"); boxes = proc.get("boxes_xyxy")
    if scores is None or cids is None or boxes is None: return ()
    r = []
    for i in range(min(int(scores.shape[0]), int(scores.shape[1]))):
        s = float(scores[0, i])
        if s < thr: continue
        c = int(cids[0, i])
        r.append(DetectionPredictionDetection(bbox_xyxy=(round(float(boxes[0, i, 0]), 4), round(float(boxes[0, i, 1]), 4), round(float(boxes[0, i, 2]), 4), round(float(boxes[0, i, 3]), 4)), score=round(s, 6), class_id=c, class_name=labels[c] if 0 <= c < len(labels) else None))
    return tuple(r)

