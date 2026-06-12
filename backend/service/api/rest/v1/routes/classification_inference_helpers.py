"""classification inference 路由辅助函数。"""

from __future__ import annotations

from typing import Any


def build_classification_inference_error_detail(error_message: str, details: dict[str, object] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"message": error_message}
    if details:
        result["details"] = details
    return result


def build_classification_direct_inference_result(
    *,
    categories: tuple[Any, ...],
    top_category: Any | None,
    latency_ms: float | None,
    image_width: int,
    image_height: int,
    preview_image_base64: str | None,
) -> dict[str, Any]:
    return {
        "categories": [
            {
                "class_id": c.class_id,
                "class_name": c.class_name,
                "probability": c.probability,
                "logit": c.logit,
            }
            for c in categories
        ],
        "top_category": {
            "class_id": top_category.class_id,
            "class_name": top_category.class_name,
            "probability": top_category.probability,
            "logit": top_category.logit,
        }
        if top_category is not None
        else None,
        "latency_ms": latency_ms,
        "image_width": image_width,
        "image_height": image_height,
        "preview_image_base64": preview_image_base64,
    }
