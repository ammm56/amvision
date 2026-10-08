"""计量资源内容契约；引用身份和二进制摘要参与版本校验。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    Identifier,
    PlanarCalibration,
    Point,
    ResourceReference,
)


class LocalizationTemplate(Contract):
    """完整参考图像内的模板区域与锚点；算法搜索参数由定位节点配置。"""

    reference_id: Identifier
    image_width: Annotated[int, Field(strict=True, ge=8, le=16384)]
    image_height: Annotated[int, Field(strict=True, ge=8, le=16384)]
    template_roi: tuple[StrictInt, StrictInt, StrictInt, StrictInt]
    anchor: Point
    image_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def check_region(self) -> Self:
        """固定解码预算和完整图像坐标，拒绝越界模板。"""
        x, y, width, height = self.template_roi
        if min(x, y) < 0 or min(width, height) < 8 or width * height > 2_000_000:
            raise ValueError("模板区域大小无效")
        if (
            x + width > self.image_width
            or y + height > self.image_height
            or self.image_width * self.image_height > 16_000_000
        ):
            raise ValueError("模板区域越界或参考图超过 1600 万像素")
        if not (x <= self.anchor[0] < x + width and y <= self.anchor[1] < y + height):
            raise ValueError("模板锚点必须位于区域内")
        return self


class MeasurementResourceContent(Contract):
    """资源内容 hash 不含路径、创建时间或项目，允许受控跨项目导入。"""

    format_id: Literal["amvision.measurement-resource.v1"] = (
        "amvision.measurement-resource.v1"
    )
    kind: Literal["planar-calibration", "localization-template"]
    calibration: PlanarCalibration | None = None
    template: LocalizationTemplate | None = None

    @model_validator(mode="after")
    def check_kind(self) -> Self:
        """每个版本只承载一种内容，不能忽略与类型无关的字段。"""
        if (self.kind == "planar-calibration") != (self.calibration is not None) or (
            self.kind == "localization-template"
        ) != (self.template is not None):
            raise ValueError("计量资源类型与内容不一致")
        return self


class MeasurementResourceDocument(Contract):
    """版本目录的唯一提交记录；所有内容先完成再发布此记录。"""

    reference: ResourceReference
    name: Annotated[str, Field(min_length=1, max_length=128)]
    content: MeasurementResourceContent
    image_object_key: str | None = None
    created_at: str
    created_by: str | None = None
