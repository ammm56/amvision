"""RF-DETR runtime target resolver。"""

from __future__ import annotations
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetResolveRequest, RuntimeTargetSnapshot
from backend.service.application.runtime.yolox_runtime_target import SqlAlchemyYoloXRuntimeTargetResolver


class SqlAlchemyRfdetrRuntimeTargetResolver(SqlAlchemyYoloXRuntimeTargetResolver):
    """RF-DETR runtime target 解析器。复用标准 target resolver。"""

    model_type = "rfdetr"
