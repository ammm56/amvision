"""YOLO Pose 数据集拓扑与增强参数连接。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.pose_topology import normalize_pose_flip_indices


COCO_PERSON_KEYPOINT_FLIP_INDICES = (
    0,
    2,
    1,
    4,
    3,
    6,
    5,
    8,
    7,
    10,
    9,
    12,
    11,
    14,
    13,
    16,
    15,
)


def prepare_pose_augmentation_options(
    *,
    extra_options: dict[str, object] | None,
    manifest_payload: dict[str, object],
    keypoint_shape: tuple[int, int],
) -> dict[str, object]:
    """把数据集 flip topology 注入训练增强，并拒绝静默无效的翻转。"""

    extra = dict(extra_options or {})
    metadata = manifest_payload.get("metadata")
    raw_indices = (
        metadata.get("keypoint_flip_indices") if isinstance(metadata, dict) else None
    )
    try:
        indices = normalize_pose_flip_indices(
            raw_indices,
            keypoint_count=int(keypoint_shape[0]),
        )
    except ValueError as error:
        raise InvalidRequestError(
            "pose DatasetExport 的 keypoint_flip_indices 无效",
            details={"reason": str(error)},
        ) from error
    if indices is not None:
        extra["keypoint_flip_indices"] = list(indices)
        return extra

    augmentation_disabled = bool(
        extra.get(
            "disable_augmentation",
            extra.get("no_augmentation", extra.get("no_aug", False)),
        )
    )
    flip_probability = float(extra.get("flip_prob", extra.get("fliplr", 0.5)))
    if (
        not augmentation_disabled
        and flip_probability > 0.0
        and int(keypoint_shape[0]) != len(COCO_PERSON_KEYPOINT_FLIP_INDICES)
    ):
        raise InvalidRequestError(
            "自定义 pose 关键点拓扑启用水平翻转时必须由数据集声明 flip_idx",
            details={
                "keypoint_count": int(keypoint_shape[0]),
                "flip_prob": flip_probability,
            },
        )
    return extra


__all__ = [
    "COCO_PERSON_KEYPOINT_FLIP_INDICES",
    "prepare_pose_augmentation_options",
]
