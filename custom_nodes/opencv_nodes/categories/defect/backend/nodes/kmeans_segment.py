"""在颜色空间中执行 K-Means 像素聚类。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_bgr,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.kmeans-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """聚类 BGR 像素并输出量化图像与聚类统计。"""

    cv2, np = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    bgr = ensure_bgr(image, cv2_module=cv2)
    cluster_count = read_int(
        request.parameters.get("cluster_count"),
        field_name="cluster_count",
        default=3,
        minimum=2,
        maximum=32,
    )
    attempts = read_int(
        request.parameters.get("attempts"),
        field_name="attempts",
        default=3,
        minimum=1,
    )
    max_iterations = read_int(
        request.parameters.get("max_iterations"),
        field_name="max_iterations",
        default=20,
        minimum=1,
    )
    epsilon = read_float(
        request.parameters.get("epsilon"),
        field_name="epsilon",
        default=1.0,
        minimum=1e-9,
    )
    data = bgr.reshape(-1, 3).astype(np.float32)
    compactness, labels, centers = cv2.kmeans(
        data,
        cluster_count,
        None,
        (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            max_iterations,
            epsilon,
        ),
        attempts,
        cv2.KMEANS_PP_CENTERS,
    )
    result = centers.astype(np.uint8)[labels.reshape(-1)].reshape(bgr.shape)
    counts = np.bincount(labels.reshape(-1), minlength=cluster_count)
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=result,
            variant_name="kmeans-segment",
            save_location=request.parameters.get("save_location"),
        ),
        "clusters": build_value_payload(
            {
                "cluster_count": cluster_count,
                "centers_bgr": centers.astype(float).tolist(),
                "pixel_counts": counts.astype(int).tolist(),
                "compactness": float(compactness),
            }
        ),
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
