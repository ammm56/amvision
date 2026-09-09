"""训练与独立 Pose 评估共用的指标策略，不改变普通部署默认参数。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.coco_style_metrics import (
    resolve_keypoint_oks_sigmas,
)


@dataclass(frozen=True)
class PoseEvaluationPolicy:
    """冻结输入、阈值与指标几何；max_detections 与现有 core 上限一致。"""

    input_size: tuple[int, int]
    score_threshold: float
    nms_threshold: float = 0.7
    oks_sigmas: tuple[float, ...] = ()
    scaleup: bool = field(default=False, init=False)
    clip_coordinates: bool = field(default=False, init=False)
    max_detections: int = field(default=300, init=False)
    version: str = field(default="pose-evaluation-v2", init=False)

    def __post_init__(self) -> None:
        """在评估开始前拒绝非有限阈值和非法输入规格。"""
        if len(self.input_size) != 2 or any(value <= 0 for value in self.input_size):
            raise InvalidRequestError("Pose 评估 input_size 不合法")
        for value in (self.score_threshold, self.nms_threshold):
            if not isfinite(value) or not 0 <= value <= 1:
                raise InvalidRequestError("Pose 评估阈值必须在 0 到 1 之间")
        if any(not isfinite(value) or value <= 0 for value in self.oks_sigmas):
            raise InvalidRequestError("Pose 评估 oks_sigmas 必须是有限正数")

    def resolve_sigmas(self, keypoint_count: int) -> tuple[float, ...]:
        """按实际拓扑解析 sigma，禁止静默截断或补齐自定义数组。"""
        if self.oks_sigmas:
            if len(self.oks_sigmas) != keypoint_count:
                raise InvalidRequestError("Pose 评估 oks_sigmas 数量与关键点拓扑不一致")
            return self.oks_sigmas
        return resolve_keypoint_oks_sigmas(keypoint_count)

    def to_report(self) -> dict[str, object]:
        """生成报告元数据；坐标不裁剪，GT area 使用同域 bbox 面积。"""
        return {**asdict(self), "coordinate_policy": "unclipped", "area_policy": "bbox"}


def build_pose_evaluation_policy(
    *,
    input_size: tuple[int, int],
    score_threshold: float,
    extra_options: dict[str, object],
) -> PoseEvaluationPolicy:
    """解析两端共用的显式评估参数。"""
    raw_sigmas = extra_options.get("oks_sigmas", ())
    if not isinstance(raw_sigmas, (list, tuple)):
        raise InvalidRequestError("Pose 评估 oks_sigmas 必须是数组")
    try:
        return PoseEvaluationPolicy(
            input_size=input_size,
            score_threshold=score_threshold,
            nms_threshold=float(extra_options.get("evaluation_nms_threshold", 0.7)),
            oks_sigmas=tuple(float(value) for value in raw_sigmas),
        )
    except (ValueError, TypeError) as error:
        raise InvalidRequestError("Pose 评估参数不是有效数值") from error
