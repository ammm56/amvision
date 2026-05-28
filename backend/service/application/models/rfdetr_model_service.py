"""RF-DETR 模型服务。"""

from __future__ import annotations
from backend.service.application.models.rfdetr_model import build_rfdetr_model, RfdetrModel


class RfdetrModelService:
    """RF-DETR 模型登记与预训练注册服务。"""

    def __init__(self, *, session_factory=None, dataset_storage=None) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def build_model(self, *, model_scale: str = "nano", num_classes: int = 91, pretrained_path: str | None = None) -> RfdetrModel:
        return build_rfdetr_model(model_scale=model_scale, num_classes=num_classes, pretrained_path=pretrained_path)
