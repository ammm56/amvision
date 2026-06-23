"""Image Diff 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_image_diff_mode,
    normalize_optional_object_key,
    require_opencv_imports,
)


NODE_TYPE_ID = "custom.opencv.image-diff"


def _build_summary_matrix(*, image_matrix, cv2_module):
    """把差分结果统一规整成单通道摘要矩阵。"""

    if len(image_matrix.shape) == 2:
        return image_matrix
    return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对当前图片和参考图片执行绝对差分。"""

    cv2_module, np_module = require_opencv_imports()
    raw_diff_mode = request.parameters.get("diff_mode")
    diff_mode = "grayscale" if raw_diff_mode in {None, ""} else normalize_image_diff_mode(raw_diff_mode)
    imdecode_flags = cv2_module.IMREAD_GRAYSCALE if diff_mode == "grayscale" else cv2_module.IMREAD_COLOR
    image_payload, _, image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=imdecode_flags,
    )
    _reference_payload, _, reference_matrix = load_image_matrix(
        request,
        input_name="reference_image",
        imdecode_flags=imdecode_flags,
    )
    if image_matrix.shape != reference_matrix.shape:
        raise InvalidRequestError(
            "image-diff 节点要求 image 与 reference_image 的尺寸和通道一致",
            details={
                "image_shape": list(image_matrix.shape),
                "reference_shape": list(reference_matrix.shape),
            },
        )

    diff_image = cv2_module.absdiff(image_matrix, reference_matrix)
    summary_matrix = _build_summary_matrix(image_matrix=diff_image, cv2_module=cv2_module)
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=diff_image,
        error_message="OpenCV image-diff 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="image-diff",
        output_extension=".png",
        width=int(diff_image.shape[1]),
        height=int(diff_image.shape[0]),
        media_type="image/png",
    )
    non_zero_pixel_count = int(np_module.count_nonzero(summary_matrix))
    total_pixel_count = int(summary_matrix.shape[0] * summary_matrix.shape[1])
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "diff_mode": diff_mode,
                "width": int(diff_image.shape[1]),
                "height": int(diff_image.shape[0]),
                "mean_abs_diff": round(float(summary_matrix.mean()), 4),
                "max_abs_diff": int(summary_matrix.max()) if total_pixel_count > 0 else 0,
                "non_zero_pixel_count": non_zero_pixel_count,
                "non_zero_ratio": round(
                    float(non_zero_pixel_count / total_pixel_count) if total_pixel_count > 0 else 0.0,
                    6,
                ),
            }
        ),
    }
