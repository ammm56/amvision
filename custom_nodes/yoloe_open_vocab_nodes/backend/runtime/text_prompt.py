"""YOLOE text-prompt project-native runtime session。"""

from __future__ import annotations

from typing import Any

import torch

from backend.nodes.text_encoder_runtime_support import (
    get_or_create_mobileclip_blt_text_encoder,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.yoloe_open_vocab_nodes.backend.core.nn.models import (
    YoloeTextPromptSegmentationModel,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.postprocess.segmentation import (
    postprocess_prompt_free_outputs as _postprocess_prompt_free_outputs,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.prompts.text import (
    build_group_source_prompt_text,
    build_grouped_text_features,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.inputs import (
    merge_text_prompt_items,
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


class YoloeTextPromptRuntimeSession:
    """可重复执行的 project-native YOLOE text-prompt 推理会话。"""

    NEGATIVE_PROMPT_WEIGHT = 0.5

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
        self.text_encoder = get_or_create_mobileclip_blt_text_encoder(device=device_name)

    @classmethod
    def load(
        cls,
        *,
        variant: Any,
        device_name: str,
        precision: str,
    ) -> "YoloeTextPromptRuntimeSession":
        """从本地预训练 checkpoint 加载 text-prompt 会话。"""

        imports, resolved_device_name = prepare_runtime_environment(
            requested_device_name=device_name,
            precision=precision,
            mode_name="text-prompt",
        )
        model, artifacts = load_text_prompt_model_from_checkpoint(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            mode_name="text-prompt",
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
        prompts: tuple[Any, ...],
        confidence_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> ProjectNativeYoloePrediction:
        """执行 text-prompt 单图推理。"""

        if not prompts:
            raise InvalidRequestError("YOLOE text-prompt 节点要求 prompts 不能为空")
        runtime_input = prepare_image_tensor(
            imports=self.imports,
            image_bytes=image_bytes,
            input_size=self.input_size,
            device_name=self.device_name,
            precision=self.precision,
        )

        prompt_groups = merge_text_prompt_items(prompts)
        prompt_texts: list[str] = []
        prompt_text_offsets: list[tuple[int, int, int]] = []
        prompt_display_names: dict[int, str] = {}
        prompt_id_map: dict[int, str] = {}
        source_text_map: dict[int, str] = {}
        positive_text_map: dict[int, tuple[str, ...]] = {}
        negative_text_map: dict[int, tuple[str, ...]] = {}
        for index, group in enumerate(prompt_groups):
            prompt_display_names[index] = str(group.display_name)
            prompt_id_map[index] = str(group.prompt_id)
            positive_text_map[index] = tuple(group.positive_texts)
            negative_text_map[index] = tuple(group.negative_texts)
            source_text_map[index] = build_group_source_prompt_text(group)
            positive_start = len(prompt_texts)
            prompt_texts.extend(group.positive_texts)
            prompt_texts.extend(group.negative_texts)
            prompt_text_offsets.append(
                (
                    positive_start,
                    len(group.positive_texts),
                    len(group.negative_texts),
                )
            )

        if not prompt_texts:
            raise InvalidRequestError("YOLOE text-prompt 节点要求至少包含一条 positive 文本提示")
        tokens = self.text_encoder.tokenize(prompt_texts)
        text_features = self.text_encoder.encode_text(tokens).to(dtype=runtime_input.input_tensor.dtype)
        grouped_text_features = build_grouped_text_features(
            text_features=text_features,
            prompt_text_offsets=tuple(prompt_text_offsets),
            negative_prompt_weight=self.NEGATIVE_PROMPT_WEIGHT,
        )
        class_embeddings = self.model.model[-1].get_tpe(grouped_text_features.unsqueeze(0))
        if class_embeddings is None:
            raise InvalidRequestError("YOLOE text-prompt 无法生成类别 embedding")

        prediction_tensor, proto_tensor = self.model(runtime_input.input_tensor, class_embeddings)
        prediction_array = prediction_tensor.detach().float().cpu().numpy()
        proto_array = proto_tensor.detach().float().cpu().numpy()
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
            item["source_prompt_text"] = source_text_map.get(class_id)
            item["source_prompt_positive_texts"] = list(positive_text_map.get(class_id, ()))
            item["source_prompt_negative_texts"] = list(negative_text_map.get(class_id, ()))
        for item in regions:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
            item["source_prompt_text"] = source_text_map.get(class_id)
            item["source_prompt_positive_texts"] = list(positive_text_map.get(class_id, ()))
            item["source_prompt_negative_texts"] = list(negative_text_map.get(class_id, ()))

        summary = {
            "model_series": self.variant.model_series,
            "model_scale": self.variant.model_scale,
            "variant_name": self.variant.variant_name,
            "checkpoint_path": str(self.variant.checkpoint_path),
            "task_type": self.variant.task_type,
            "prompt_count": len(prompt_groups),
            "prompt_item_count": len(prompts),
            "prompt_group_count": len(prompt_groups),
            "positive_prompt_count": sum(len(group.positive_texts) for group in prompt_groups),
            "negative_prompt_count": sum(len(group.negative_texts) for group in prompt_groups),
            "detection_count": len(detections),
            "region_count": len(regions),
            "device": self.device_name,
            "precision": self.precision,
            "confidence_threshold": float(confidence_threshold),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "prompt_free": False,
            "inference_mode": "text-prompt",
            "text_encoder": "mobileclip/blt",
            "negative_prompt_weight": self.NEGATIVE_PROMPT_WEIGHT,
            "prompt_groups": [
                _build_text_prompt_group_summary_item(group)
                for group in prompt_groups
            ],
            "project_native": True,
        }
        return ProjectNativeYoloePrediction(
            detections=tuple(detections),
            regions=tuple(regions),
            summary=summary,
        )


def _build_text_prompt_group_summary_item(group: Any) -> dict[str, object]:
    """构建 text prompt group 的运行时摘要项。"""

    return {
        "prompt_id": str(group.prompt_id),
        "display_name": str(group.display_name),
        "positive_texts": list(group.positive_texts),
        "negative_texts": list(group.negative_texts),
        "languages": list(group.languages),
    }


__all__ = ["YoloeTextPromptRuntimeSession"]
