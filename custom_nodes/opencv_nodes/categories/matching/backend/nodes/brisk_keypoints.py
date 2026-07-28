"""提取 BRISK 关键点和二进制描述子。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.features import (
    build_local_features_payload,
    require_local_features_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.brisk-keypoints"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """运行 BRISK 检测和描述，并构造 local-features.v1。"""

    cv2, np = require_opencv_imports()
    image_payload, source_key, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2)
    detector = cv2.BRISK_create(
        thresh=read_int(
            request.parameters.get("threshold"),
            field_name="threshold",
            default=30,
            minimum=1,
        ),
        octaves=read_int(
            request.parameters.get("octaves"),
            field_name="octaves",
            default=3,
            minimum=0,
        ),
        patternScale=read_float(
            request.parameters.get("pattern_scale"),
            field_name="pattern_scale",
            default=1.0,
            minimum=0.01,
        ),
    )
    keypoints, descriptors = detector.detectAndCompute(gray, None)
    keypoints = keypoints or []
    if descriptors is None:
        descriptor_length = int(detector.descriptorSize())
        descriptors = np.empty((0, descriptor_length), dtype=np.uint8)
    else:
        descriptor_length = int(descriptors.shape[1])
    items = [
        {
            "feature_id": f"feature-{index}",
            "feature_index": index - 1,
            "x": float(keypoint.pt[0]),
            "y": float(keypoint.pt[1]),
            "point_xy": [float(keypoint.pt[0]), float(keypoint.pt[1])],
            "size": float(keypoint.size),
            "angle_deg": float(keypoint.angle),
            "response": float(keypoint.response),
            "octave": int(keypoint.octave),
            "class_id": int(keypoint.class_id),
        }
        for index, keypoint in enumerate(keypoints, start=1)
    ]
    payload = build_local_features_payload(
        items=items,
        descriptors=descriptors.tolist(),
        source_image=image_payload,
        source_object_key=source_key,
        descriptor_length=descriptor_length,
        feature_extractor="brisk",
        descriptor_kind="brisk",
        descriptor_dtype="uint8",
        descriptor_norm="hamming",
    )
    return {
        "features": require_local_features_payload(payload),
        "summary": build_value_payload(
            {
                "feature_extractor": "brisk",
                "feature_count": len(items),
                "descriptor_length": descriptor_length,
                "descriptor_dtype": "uint8",
                "descriptor_norm": "hamming",
            }
        ),
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
