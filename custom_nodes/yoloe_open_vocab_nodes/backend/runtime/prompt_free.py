"""YOLOE prompt-free project-native runtime session。"""

from __future__ import annotations

from typing import Any

import torch

from custom_nodes.yoloe_open_vocab_nodes.backend.core.nn.models import (
    YoloePromptFreeSegmentationModel,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.postprocess.segmentation import (
    postprocess_prompt_free_outputs as _postprocess_prompt_free_outputs,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.environment import (
    prepare_runtime_environment,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.model_loading import (
    load_prompt_free_model_from_checkpoint,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.preprocess import (
    prepare_image_tensor,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.types import (
    ProjectNativeYoloePrediction,
)


class YoloePromptFreeRuntimeSession:
    """可重复执行的 project-native YOLOE prompt-free 推理会话。"""

    def __init__(
        self,
        *,
        variant: Any,
        device_name: str,
        precision: str,
        imports: Any,
        model: YoloePromptFreeSegmentationModel,
        input_size: tuple[int, int],
        class_names: dict[int, str],
    ) -> None:
        self.variant = variant
        self.device_name = device_name
        self.precision = precision
        self.imports = imports
        self.model = model
        self.input_size = input_size
        self.class_names = class_names

    @classmethod
    def load(
        cls,
        *,
        variant: Any,
        device_name: str,
        precision: str,
    ) -> "YoloePromptFreeRuntimeSession":
        """从本地预训练 checkpoint 加载 prompt-free 会话。"""

        imports, resolved_device_name = prepare_runtime_environment(
            requested_device_name=device_name,
            precision=precision,
            mode_name="prompt-free",
        )
        model, artifacts = load_prompt_free_model_from_checkpoint(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
        )
        return cls(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            imports=imports,
            model=model,
            input_size=artifacts.input_size,
            class_names=artifacts.class_names,
        )

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        image_payload: object,
        confidence_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> ProjectNativeYoloePrediction:
        """执行 prompt-free 单图推理。"""

        runtime_input = prepare_image_tensor(
            imports=self.imports,
            image_bytes=image_bytes,
            image_payload=image_payload,
            input_size=self.input_size,
            device_name=self.device_name,
            precision=self.precision,
        )
        prediction_tensor, proto_tensor = self.model(runtime_input.input_tensor)
        prediction_array = prediction_tensor.detach().float().cpu().numpy()
        proto_array = proto_tensor.detach().float().cpu().numpy()
        detections, regions = _postprocess_prompt_free_outputs(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            class_names=self.class_names,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            resize_ratio=runtime_input.resize_ratio,
            image_width=int(runtime_input.image.shape[1]),
            image_height=int(runtime_input.image.shape[0]),
            input_size=self.input_size,
        )
        summary = {
            "model_series": self.variant.model_series,
            "model_scale": self.variant.model_scale,
            "variant_name": self.variant.variant_name,
            "checkpoint_path": str(self.variant.checkpoint_path),
            "task_type": self.variant.task_type,
            "prompt_count": 0,
            "detection_count": len(detections),
            "region_count": len(regions),
            "device": self.device_name,
            "precision": self.precision,
            "confidence_threshold": float(confidence_threshold),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "prompt_free": True,
            "inference_mode": "prompt-free",
            "vocabulary_size": len(self.class_names),
            "top_classes": [str(item["class_name"]) for item in detections[:5]],
            "input_size": [int(self.input_size[0]), int(self.input_size[1])],
            "project_native": True,
        }
        return ProjectNativeYoloePrediction(
            detections=tuple(detections),
            regions=tuple(regions),
            summary=summary,
        )


__all__ = ["YoloePromptFreeRuntimeSession"]
