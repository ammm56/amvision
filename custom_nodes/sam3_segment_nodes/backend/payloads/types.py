"""SAM3 custom node 使用的 payload 数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Sam3TextPromptItem:
    """描述一条 SAM3 语义提示。"""

    prompt_id: str
    text: str
    display_name: str
    negative: bool = False
    language: str | None = None


@dataclass(frozen=True)
class Sam3TextPromptGroup:
    """描述一个按 prompt_id 聚合后的 SAM3 语义提示组。"""

    prompt_id: str
    display_name: str
    positive_texts: tuple[str, ...]
    negative_texts: tuple[str, ...]
    languages: tuple[str, ...]

    @property
    def source_prompt_text(self) -> str:
        """返回写入结果摘要的可追溯文本组合。"""

        positive_segment = " | ".join(self.positive_texts)
        if not self.negative_texts:
            return positive_segment
        negative_segment = " | ".join(f"!{item}" for item in self.negative_texts)
        return f"{positive_segment} || {negative_segment}"

    @property
    def source_prompt_positive_texts(self) -> tuple[str, ...]:
        """返回正向文本集合。"""

        return self.positive_texts

    @property
    def source_prompt_negative_texts(self) -> tuple[str, ...]:
        """返回负向文本集合。"""

        return self.negative_texts


@dataclass(frozen=True)
class Sam3InteractivePromptItem:
    """描述一条 SAM3 交互提示。"""

    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None = None
    point_xy: tuple[float, float] | None = None
    point_label: str | None = None
    polygon_xy: tuple[tuple[float, float], ...] | None = None
    prompt_mask: np.ndarray | None = None


@dataclass(frozen=True)
class Sam3FrameWindowItem:
    """描述一帧已解码完成的视频帧。"""

    frame_index: int
    timestamp_ms: float
    image_payload: dict[str, object]
    image_bytes: bytes
    width: int
    height: int


@dataclass(frozen=True)
class Sam3PretrainedVariant:
    """描述一个 SAM3 预训练权重目录。"""

    model_scale: str
    variant_name: str
    manifest_path: Path
    checkpoint_path: Path
    model_name: str
    task_type: str
    metadata: dict[str, object]


__all__ = [
    "Sam3FrameWindowItem",
    "Sam3InteractivePromptItem",
    "Sam3PretrainedVariant",
    "Sam3TextPromptGroup",
    "Sam3TextPromptItem",
]
