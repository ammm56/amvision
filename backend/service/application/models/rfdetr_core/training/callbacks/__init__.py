"""RF-DETR core 训练处理模块：`training.callbacks.__init__`。"""

from backend.service.application.models.rfdetr_core.training.callbacks.best_model import BestModelCallback, RFDETREarlyStopping
from backend.service.application.models.rfdetr_core.training.callbacks.coco_eval import COCOEvalCallback
from backend.service.application.models.rfdetr_core.training.callbacks.drop_schedule import DropPathCallback
from backend.service.application.models.rfdetr_core.training.callbacks.ema import RFDETREMACallback

__all__ = [
    "BestModelCallback",
    "COCOEvalCallback",
    "DropPathCallback",
    "RFDETREMACallback",
    "RFDETREarlyStopping",
]


