"""ECC Align 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_gray,
    read_choice,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.ecc-align"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用 ECC 最大化相关系数估计平移、欧氏、仿射或单应变换。"""

    cv2_module, np_module = require_opencv_imports()
    reference_payload, _, reference = load_image_matrix(request, input_name="reference_image")
    moving_payload, _, moving = load_image_matrix(request, input_name="moving_image")
    if reference.shape[:2] != moving.shape[:2]:
        raise InvalidRequestError("ecc-align 的两张图片宽高必须一致")
    motion = read_choice(
        request.parameters.get("motion"),
        field_name="motion",
        choices={"translation", "euclidean", "affine", "homography"},
        default="affine",
    )
    iterations = read_int(request.parameters.get("iterations"), field_name="iterations", default=100, minimum=1)
    epsilon = read_float(request.parameters.get("epsilon"), field_name="epsilon", default=1e-6, minimum=0.0)
    gaussian_filter_size = read_int(
        request.parameters.get("gaussian_filter_size"),
        field_name="gaussian_filter_size",
        default=5,
        minimum=1,
    )
    if gaussian_filter_size % 2 == 0:
        raise InvalidRequestError("gaussian_filter_size 必须是奇数")
    motion_type = {
        "translation": cv2_module.MOTION_TRANSLATION,
        "euclidean": cv2_module.MOTION_EUCLIDEAN,
        "affine": cv2_module.MOTION_AFFINE,
        "homography": cv2_module.MOTION_HOMOGRAPHY,
    }[motion]
    warp_matrix = (
        np_module.eye(3, dtype=np_module.float32)
        if motion == "homography"
        else np_module.eye(2, 3, dtype=np_module.float32)
    )
    reference_gray = ensure_gray(reference, cv2_module=cv2_module).astype(np_module.float32) / 255.0
    moving_gray = ensure_gray(moving, cv2_module=cv2_module).astype(np_module.float32) / 255.0
    try:
        correlation, warp_matrix = cv2_module.findTransformECC(
            reference_gray,
            moving_gray,
            warp_matrix,
            motion_type,
            (cv2_module.TERM_CRITERIA_COUNT | cv2_module.TERM_CRITERIA_EPS, iterations, epsilon),
            None,
            gaussian_filter_size,
        )
    except cv2_module.error as error:
        raise InvalidRequestError("ECC 配准未收敛", details={"opencv_error": str(error)}) from error
    output_size = (int(reference.shape[1]), int(reference.shape[0]))
    if motion == "homography":
        aligned = cv2_module.warpPerspective(
            moving,
            warp_matrix,
            output_size,
            flags=cv2_module.INTER_LINEAR | cv2_module.WARP_INVERSE_MAP,
        )
        matrix_3x3 = warp_matrix
    else:
        aligned = cv2_module.warpAffine(
            moving,
            warp_matrix,
            output_size,
            flags=cv2_module.INTER_LINEAR | cv2_module.WARP_INVERSE_MAP,
        )
        matrix_3x3 = np_module.vstack([warp_matrix, [0.0, 0.0, 1.0]])
    return {
        "image": build_image_output(
            request,
            source_payload=moving_payload,
            image_matrix=aligned,
            variant_name="ecc-align",
            output_object_key=request.parameters.get("output_object_key"),
        ),
        "transform": build_value_payload(
            {
                "transform_kind": motion,
                "correlation": float(correlation),
                "matrix_3x3": matrix_3x3.astype(float).tolist(),
                "reference_image": reference_payload,
            }
        ),
    }
