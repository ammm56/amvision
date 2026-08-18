"""Color Convert 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, read_choice
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.color-convert"

_CONVERSION_NAMES = {
    "bgr-to-gray": "COLOR_BGR2GRAY",
    "gray-to-bgr": "COLOR_GRAY2BGR",
    "bgr-to-rgb": "COLOR_BGR2RGB",
    "rgb-to-bgr": "COLOR_RGB2BGR",
    "bgr-to-hsv": "COLOR_BGR2HSV",
    "hsv-to-bgr": "COLOR_HSV2BGR",
    "bgr-to-hls": "COLOR_BGR2HLS",
    "hls-to-bgr": "COLOR_HLS2BGR",
    "bgr-to-lab": "COLOR_BGR2LAB",
    "lab-to-bgr": "COLOR_LAB2BGR",
    "bgr-to-ycrcb": "COLOR_BGR2YCrCb",
    "ycrcb-to-bgr": "COLOR_YCrCb2BGR",
    "bgr-to-xyz": "COLOR_BGR2XYZ",
    "xyz-to-bgr": "COLOR_XYZ2BGR",
    "bgr-to-luv": "COLOR_BGR2Luv",
    "luv-to-bgr": "COLOR_Luv2BGR",
    "bgra-to-bgr": "COLOR_BGRA2BGR",
    "bgr-to-bgra": "COLOR_BGR2BGRA",
}


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行显式颜色空间转换。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request, imdecode_flags=cv2_module.IMREAD_UNCHANGED)
    conversion = read_choice(
        request.parameters.get("conversion"),
        field_name="conversion",
        choices=_CONVERSION_NAMES,
        default="bgr-to-gray",
    )
    output = cv2_module.cvtColor(image, getattr(cv2_module, _CONVERSION_NAMES[conversion]))
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="color-convert",
            save_location=request.parameters.get("save_location"),
        )
    }
