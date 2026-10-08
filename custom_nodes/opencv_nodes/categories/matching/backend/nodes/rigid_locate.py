"""计量用通用刚性定位：失败状态是可连线结果，参数/资源错误仍报错。"""

import cv2
from typing import Annotated
from pydantic import Field

from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    PoseObservation,
    ResourceReference,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.measurement_resources import require_prepared_measurement_resource
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.metrology import prepare_gray
from custom_nodes.opencv_nodes.shared.backend.metrology.identity import image_identity
from custom_nodes.opencv_nodes.shared.backend.metrology.localization import (
    RigidLocateSettings,
    locate_rigid,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix

NODE_TYPE_ID = "custom.opencv.rigid-locate"


class Settings(Contract):
    """模板内容只由不可变资源拥有，节点仅配置本次搜索范围。"""

    template_resource: ResourceReference
    angle_min: Annotated[Finite, Field(ge=-180, le=180)] = -15.0
    angle_max: Annotated[Finite, Field(ge=-180, le=180)] = 15.0
    angle_step: Annotated[Finite, Field(ge=0.1, le=30)] = 1.0
    minimum_score: Annotated[Finite, Field(gt=0, le=1)] = 0.75


def handle_node(request) -> dict:
    """借用本次图片和参考图，模板坐标始终对应完整参考图。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    payload, _, image = load_image_matrix(request, imdecode_flags=cv2.IMREAD_UNCHANGED)
    try:
        parameters = Settings.model_validate(request.parameters)
        prepared = require_prepared_measurement_resource(
            request, "template_resource", "localization-template"
        )
        template = prepared["content"].template
        reference = prepared["image"]
        if image.shape[:2] != (template.image_height, template.image_width):
            raise ValueError("定位输入尺寸与模板成像条件不一致")
        settings = RigidLocateSettings(
            reference_id=template.reference_id,
            template_roi=template.template_roi,
            anchor=template.anchor,
            **parameters.model_dump(exclude={"template_resource"}),
        )
        result = locate_rigid(
            prepare_gray(image),
            prepare_gray(reference),
            settings,
            check=control.raise_if_cancelled_or_expired,
        )
        pose = PoseObservation(
            image=image_identity(request, payload, image),
            reference_id=settings.reference_id,
            reference_sha256=parameters.template_resource.sha256,
            state=result["state"],
            reason=result["reason"],
            image_from_reference=result["matrix"],
        )
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return {
        "pose": pose.model_dump(mode="json"),
        "summary": build_value_payload(
            {k: v for k, v in result.items() if k != "matrix"}
        ),
    }
