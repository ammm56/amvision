"""二维控制点标定；只在配置/验证工作流显式执行，不在测量时重新求解。"""

from typing import Annotated, Literal

from pydantic import Field, ValidationError

from backend.contracts.workflows.metrology import (
    CalibrationPointPair,
    Contract,
    Finite,
    Identifier,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.metrology import fit_planar_calibration

NODE_TYPE_ID = "custom.opencv.planar-calibrate"


class Settings(Contract):
    """平面标定输入、拟合模型、覆盖和独立验证门槛。"""

    image_width: Annotated[int, Field(strict=True, ge=1, le=32766)]
    image_height: Annotated[int, Field(strict=True, ge=1, le=32766)]
    model: Literal["similarity", "affine", "homography"] = "affine"
    unit: Literal["millimeter", "meter"] = "millimeter"
    plane_id: Identifier
    control_points: Annotated[
        tuple[CalibrationPointPair, ...], Field(min_length=3, max_length=4096)
    ]
    validation_points: Annotated[
        tuple[CalibrationPointPair, ...], Field(min_length=2, max_length=4096)
    ]
    max_validation_error: Annotated[Finite, Field(gt=0)]


def handle_node(request) -> dict:
    """拟合并验证独立点；不合格标定不能成为有效资源。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    try:
        settings = Settings.model_validate(request.parameters)
        result = fit_planar_calibration(
            [p.image for p in settings.control_points],
            [p.world for p in settings.control_points],
            [p.image for p in settings.validation_points],
            [p.world for p in settings.validation_points],
            model=settings.model,
            image_size=(settings.image_width, settings.image_height),
            unit=settings.unit,
            plane_id=settings.plane_id,
        )
    except (ValueError, ValidationError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    control.raise_if_cancelled_or_expired()
    if result.validation_max_error > settings.max_validation_error:
        raise InvalidRequestError(
            "独立标定验证误差超过配置上限",
            details={
                "measured": result.validation_max_error,
                "limit": settings.max_validation_error,
                "unit": settings.unit,
            },
        )
    outputs = {
        "calibration": result.model_dump(mode="json"),
        "summary": build_value_payload(
            {
                "fit_rms": result.fit_rms,
                "validation_max_error": result.validation_max_error,
                "unit": result.unit,
                "plane_id": result.plane_id,
            }
        ),
    }
    # 仅编辑预览携带完整拟合结果和参数快照，供显式保存；生产调用不复制配置。
    if request.execution_metadata.get("debug_image_panels_enabled") is True:
        outputs["debug_preview"] = {
            "type": "value-preview",
            "title": "Planar Calibration",
            "value": outputs["summary"]["value"],
            "calibration_resource": outputs["calibration"],
            "parameter_snapshot": settings.model_dump(mode="json"),
        }
    return outputs
