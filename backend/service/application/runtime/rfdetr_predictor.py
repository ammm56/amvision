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
from backend.service.application.runtime.detection_runtime_support import load_prediction_image, render_preview_image
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot, describe_runtime_execution_mode
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

_RF_INPUT_SIZES = {"nano": 384, "small": 512, "medium": 576, "large": 704}


class PyTorchRfdetrRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch RF-DETR 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "detection"

    def __init__(self, *, dataset_storage, runtime_target, imports, model, device_name, runtime_precision, input_size):
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision
        self.input_size = input_size

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
        t0 = perf_counter()
        image = load_prediction_image(cv2_module=self.imports.cv2, np_module=self.imports.np, dataset_storage=self.dataset_storage, request=request)
        dms = round((perf_counter() - t0) * 1000, 3)
        t1 = perf_counter()
        ih, iw = self.input_size
        resized = self.imports.cv2.resize(image, (iw, ih), interpolation=self.imports.cv2.INTER_LINEAR)
        tensor = resized[:, :, ::-1].transpose(2, 0, 1).astype(self.imports.np.float32) / 255.0
        tensor = self.imports.torch.from_numpy(tensor).unsqueeze(0).to(self.device_name)
        pms = round((perf_counter() - t1) * 1000, 3)
        t2 = perf_counter()
        with self.imports.torch.no_grad():
            outputs = self.model(tensor)
        ims = round((perf_counter() - t2) * 1000, 3)
        t3 = perf_counter()
        ts = self.imports.torch.tensor([[float(image.shape[0]), float(image.shape[1])]], device=self.device_name)
        proc = self.model.postprocess(outputs, ts)
        dets = _build_detections(proc, self.runtime_target.labels, request.score_threshold)
        pms2 = round((perf_counter() - t3) * 1000, 3)
        lat = dms + pms + ims + pms2
        preview = None
        if request.save_result_image and dets: preview = render_preview_image(cv2_module=self.imports.cv2, image=image, detections=dets)
        return DetectionPredictionExecutionResult(
            detections=dets, latency_ms=round(lat, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]),
            preview_image_bytes=preview, runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend, model_uri=self.runtime_target.runtime_artifact_storage_uri, device_name=self.device_name,
                input_spec=DetectionRuntimeTensorSpec(name="images", shape=(1, 3, ih, iw), dtype="float32"),
                output_specs=(DetectionRuntimeTensorSpec(name="predictions", shape=(1, 300, 4), dtype="float32"),),
                metadata={"model_type": "rfdetr", "model_scale": self.runtime_target.model_scale, "decode_ms": dms, "preprocess_ms": pms, "infer_ms": ims, "postprocess_ms": pms2},
            ),
        )


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
