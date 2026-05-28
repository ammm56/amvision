"""RF-DETR segmentation 推理实现。"""

from __future__ import annotations
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.segmentation_runtime_contracts import SegmentationPredictionRequest, SegmentationPredictionExecutionResult
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchRfdetrSegmentationRuntimeSession:
    """PyTorch RF-DETR segmentation 会话。"""

    model_type = "rfdetr"; model_label = "RF-DETR"; task_type = "segmentation"

    def __init__(self, *, dataset_storage, runtime_target, imports, model, device_name, input_size):
        self.dataset_storage = dataset_storage; self.runtime_target = runtime_target; self.imports = imports
        self.model = model; self.device_name = device_name; self.input_size = input_size

    @classmethod
    def load(cls, *, dataset_storage: LocalDatasetStorage, runtime_target: RuntimeTargetSnapshot) -> "PyTorchRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError("RF-DETR segmentation 仅支持 pytorch", details={"runtime_backend": runtime_target.runtime_backend})
        import cv2, numpy as np, torch
        imp = type("_I", (), {"cv2": cv2, "np": np, "torch": torch})()
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imp, model=None, device_name="cpu", input_size=(384, 384))

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        raise InvalidRequestError("RF-DETR segmentation 推理后端尚未接通，仅登记入口", details={"model_type": "rfdetr"})
