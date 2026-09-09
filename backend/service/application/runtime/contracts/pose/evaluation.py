"""仅供进程内评估使用的请求扩展，不加入 HTTP 或共享内存消息 schema。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.models.evaluation.pose_policy import (
    PoseEvaluationPolicy,
)
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionRequest,
)


@dataclass(frozen=True)
class PoseEvaluationPredictionRequest(PosePredictionRequest):
    """携带冻结策略的内部评估请求，不通过 extra_options 猜测调用用途。"""

    evaluation_policy: PoseEvaluationPolicy = field(kw_only=True)


def pose_evaluation_preprocess_options(
    request: PosePredictionRequest,
) -> dict[str, object]:
    """普通预测返回空参数，内部评估显式控制小图放大。"""
    if isinstance(request, PoseEvaluationPredictionRequest):
        return {"scaleup": request.evaluation_policy.scaleup}
    return {}


def pose_evaluation_postprocess_options(
    request: PosePredictionRequest,
    *,
    end2end: bool = False,
) -> dict[str, object]:
    """内部评估保留坐标；end2end 模型没有 NMS，不注入无效参数。"""
    if not isinstance(request, PoseEvaluationPredictionRequest):
        return {}
    policy = request.evaluation_policy
    options: dict[str, object] = {"clip_coordinates": policy.clip_coordinates}
    if not end2end:
        options["nms_threshold"] = policy.nms_threshold
    return options
