"""YOLOv8 classification head。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.tasks.classification import (
    Classify as _CommonClassify,
)


Classify = _CommonClassify
