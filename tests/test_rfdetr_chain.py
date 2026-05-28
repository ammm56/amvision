"""RF-DETR 内部链烟雾验证。"""

from __future__ import annotations
import torch

def test_rfdetr_model_can_build():
    """验证 RF-DETR 模型可以构建。"""
    from backend.service.application.models.rfdetr_model import build_rfdetr_model
    model = build_rfdetr_model(model_scale="nano", num_classes=91)
    assert model is not None
    assert isinstance(model.backbone, torch.nn.Module)
    assert isinstance(model.decoder, torch.nn.Module)
    assert isinstance(model.detection_head, torch.nn.Module)

def test_rfdetr_backend_registration():
    """验证 RF-DETR 已登记到 detection backend registry。"""
    from backend.service.application.detection_backend_registry import get_detection_backend_registration
    reg = get_detection_backend_registration("rfdetr")
    assert reg is not None
    assert reg.display_name == "RF-DETR"
    assert reg.features.inference is True
    assert reg.features.deployment is True

def test_rfdetr_imports():
    """验证所有 RF-DETR 模块可以被导入。"""
    from backend.service.application.models.rfdetr_model import RfdetrModel, RfdetrPostProcess
    from backend.service.application.models.rfdetr_model_service import SqlAlchemyRfdetrModelService
    from backend.service.application.runtime.rfdetr_predictor import PyTorchRfdetrRuntimeSession
    from backend.service.application.runtime.rfdetr_runtime_target import SqlAlchemyRfdetrRuntimeTargetResolver
    from backend.service.application.conversions.rfdetr_conversion_planner import DefaultRfdetrConversionPlanner
    from backend.service.domain.models.rfdetr_model_spec import RFDETR_MODEL_SCALES
