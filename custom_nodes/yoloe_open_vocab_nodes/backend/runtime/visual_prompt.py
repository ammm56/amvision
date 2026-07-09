"""YOLOE visual-prompt project-native runtime session。"""

from __future__ import annotations

from typing import Any

import torch

from backend.service.application.errors import InvalidRequestError
from custom_nodes.yoloe_open_vocab_nodes.backend.core.nn.models import (
    YoloeTextPromptSegmentationModel,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.postprocess.segmentation import (
    postprocess_prompt_free_outputs as _postprocess_prompt_free_outputs,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.prompts.visual import (
    build_visual_prompt_tensor as _build_visual_prompt_tensor,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.prompts.visual_embeddings import (
    extract_visual_prompt_embeddings,
    forward_with_class_embeddings,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.environment import (
    prepare_runtime_environment,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.model_loading import (
    load_text_prompt_model_from_checkpoint,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.preprocess import (
    prepare_image_tensor,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.types import (
    ProjectNativeYoloePrediction,
)


class YoloeVisualPromptRuntimeSession:
    """可重复执行的 project-native YOLOE visual-prompt 推理会话。"""

    def __init__(
        self,
        *,
        variant: Any,
        device_name: str,
        precision: str,
        imports: Any,
        model: YoloeTextPromptSegmentationModel,
        input_size: tuple[int, int],
    ) -> None:
        self.variant = variant
        self.device_name = device_name
        self.precision = precision
        self.imports = imports
        self.model = model
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        variant: Any,
        device_name: str,
        precision: str,
    ) -> "YoloeVisualPromptRuntimeSession":
        """从本地预训练 checkpoint 加载 visual-prompt 会话。"""

        imports, resolved_device_name = prepare_runtime_environment(
            requested_device_name=device_name,
            precision=precision,
            mode_name="visual-prompt",
        )
        model, artifacts = load_text_prompt_model_from_checkpoint(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            mode_name="visual-prompt",
        )
        return cls(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            imports=imports,
            model=model,
            input_size=artifacts.input_size,
        )

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        image_payload: object,
        prompt_image_bytes: bytes,
        prompt_image_payload: object,
        prompts: tuple[Any, ...],
        confidence_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> ProjectNativeYoloePrediction:
        """执行 visual-prompt 单图推理。"""

        if not prompts:
            raise InvalidRequestError("YOLOE visual-prompt 节点要求 prompts 不能为空")
        runtime_input = prepare_image_tensor(
            imports=self.imports,
            image_bytes=image_bytes,
            image_payload=image_payload,
            input_size=self.input_size,
            device_name=self.device_name,
            precision=self.precision,
        )
        prompt_runtime_input = prepare_image_tensor(
            imports=self.imports,
            image_bytes=prompt_image_bytes,
            image_payload=prompt_image_payload,
            input_size=self.input_size,
            device_name=self.device_name,
            precision=self.precision,
        )

        visual_prompt_tensor = _build_visual_prompt_tensor(
            torch_module=self.imports.torch,
            np_module=self.imports.np,
            prompts=prompts,
            input_size=self.input_size,
            resize_ratio=prompt_runtime_input.resize_ratio,
            prompt_image_width=int(prompt_runtime_input.image.shape[1]),
            prompt_image_height=int(prompt_runtime_input.image.shape[0]),
            device_name=self.device_name,
            dtype=prompt_runtime_input.input_tensor.dtype,
        )
        class_embeddings = extract_visual_prompt_embeddings(
            model=self.model,
            prompt_input_tensor=prompt_runtime_input.input_tensor,
            visual_prompt_tensor=visual_prompt_tensor,
        )
        prediction_tensor, proto_tensor = forward_with_class_embeddings(
            model=self.model,
            input_tensor=runtime_input.input_tensor,
            class_embeddings=class_embeddings,
        )
        prediction_array = prediction_tensor.detach().float().cpu().numpy()
        proto_array = proto_tensor.detach().float().cpu().numpy()
        prompt_display_names = {index: str(item.display_name) for index, item in enumerate(prompts)}
        prompt_id_map = {index: str(item.prompt_id) for index, item in enumerate(prompts)}
        detections, regions = _postprocess_prompt_free_outputs(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            class_names=prompt_display_names,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            resize_ratio=runtime_input.resize_ratio,
            image_width=int(runtime_input.image.shape[1]),
            image_height=int(runtime_input.image.shape[0]),
            input_size=self.input_size,
        )
        for item in detections:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
        for item in regions:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
        visual_prompt_kinds = tuple(
            sorted(
                {
                    str(kind)
                    for item in prompts
                    for kind in (
                        tuple(getattr(item, "prompt_kinds", ())) or (str(getattr(item, "prompt_kind", "mixed")),)
                    )
                }
            )
        )
        prompt_item_count = sum(max(1, int(getattr(item, "raw_item_count", 1))) for item in prompts)
        prompt_kind_counts: dict[str, int] = {}
        for item in prompts:
            normalized_prompt_kinds = tuple(getattr(item, "prompt_kinds", ())) or (
                str(getattr(item, "prompt_kind", "mixed")),
            )
            for prompt_kind in normalized_prompt_kinds:
                prompt_kind_counts[str(prompt_kind)] = int(prompt_kind_counts.get(str(prompt_kind), 0)) + 1

        summary = {
            "model_series": self.variant.model_series,
            "model_scale": self.variant.model_scale,
            "variant_name": self.variant.variant_name,
            "checkpoint_path": str(self.variant.checkpoint_path),
            "task_type": self.variant.task_type,
            "prompt_count": len(prompts),
            "prompt_item_count": int(prompt_item_count),
            "prompt_group_count": len(prompts),
            "detection_count": len(detections),
            "region_count": len(regions),
            "device": self.device_name,
            "precision": self.precision,
            "confidence_threshold": float(confidence_threshold),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "prompt_free": False,
            "inference_mode": "visual-prompt",
            "visual_prompt_kinds": list(visual_prompt_kinds),
            "visual_prompt_kind": visual_prompt_kinds[0] if len(visual_prompt_kinds) == 1 else "mixed",
            "prompt_kind_counts": prompt_kind_counts,
            "prompt_groups": [_build_visual_prompt_summary_item(item) for item in prompts],
            "project_native": True,
        }
        return ProjectNativeYoloePrediction(
            detections=tuple(detections),
            regions=tuple(regions),
            summary=summary,
        )


def _build_visual_prompt_summary_item(item: Any) -> dict[str, object]:
    """构建 visual prompt 运行时摘要项。"""

    prompt_kinds = tuple(getattr(item, "prompt_kinds", ())) or (str(getattr(item, "prompt_kind", "mixed")),)
    summary_item: dict[str, object] = {
        "prompt_id": str(getattr(item, "prompt_id", "")),
        "display_name": str(getattr(item, "display_name", "") or getattr(item, "prompt_id", "")),
        "prompt_kind": str(getattr(item, "prompt_kind", "mixed")),
        "prompt_kinds": list(prompt_kinds),
        "raw_item_count": max(1, int(getattr(item, "raw_item_count", 1))),
    }
    bbox_xyxy = getattr(item, "bbox_xyxy", None)
    if bbox_xyxy is not None:
        summary_item["bbox_xyxy"] = [float(value) for value in bbox_xyxy]
    point_xy = getattr(item, "point_xy", None)
    if point_xy is not None:
        summary_item["point_xy"] = [float(value) for value in point_xy]
    point_label = getattr(item, "point_label", None)
    if point_label is not None:
        summary_item["point_label"] = str(point_label)
    polygon_xy = getattr(item, "polygon_xy", None)
    if polygon_xy is not None:
        summary_item["polygon_xy"] = [[float(value) for value in point] for point in polygon_xy]
    if getattr(item, "prompt_mask", None) is not None:
        summary_item["has_prompt_mask"] = True
    return summary_item


__all__ = ["YoloeVisualPromptRuntimeSession"]
