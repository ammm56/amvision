"""detection 训练任务 API 聚合路由。"""

from __future__ import annotations

from fastapi import APIRouter

from .controls import detection_training_control_router
from .create import detection_training_create_router
from .outputs import detection_training_outputs_router
from .queries import detection_training_query_router


detection_training_tasks_router = APIRouter(prefix="/models", tags=["models"])
detection_training_tasks_router.include_router(detection_training_create_router)
detection_training_tasks_router.include_router(detection_training_query_router)
detection_training_tasks_router.include_router(detection_training_control_router)
detection_training_tasks_router.include_router(detection_training_outputs_router)
