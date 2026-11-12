"""专用样本 ZIP v1 的输入约束；坐标均为原图左上角起算的像素。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
Unit = Literal["mm", "m"]
MEDIA_TASKS = ("anomaly", "connector-reference", "rgbd", "point-cloud")
SOURCE_ASSETS = ("cloud", "depth", "mask", "calibration")


class MediaFields(BaseModel):
    """拒绝未知字段及非有限数，防止误写的单位或真值被忽略。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Entry(MediaFields):
    """配对身份、数据划分和可选的素材来源。"""

    id: Text
    origin_id: Text | None = None
    split: Literal["train", "val", "test"]
    source: Text | None = None


class Anomaly(Entry):
    """图片与导入真值；mask 是同尺寸二值 PNG。"""

    image: Text
    label: Literal["normal", "anomaly"]
    category: Text | None = None
    defect: Text | None = None
    mask: Text | None = None


class Pin(MediaFields):
    """PIN 编号及标注在原始图像上的位置。"""

    id: Text
    x: float
    y: float


class ReferenceValue(MediaFields):
    """独立参考值必须标明量名、单位和来源。"""

    name: Text
    value: float
    unit: Text
    source: Text


class Connector(Entry):
    """连接器图像、参考平面及可独立追溯的设计和参考数据。"""

    image: Text
    synthetic: bool
    unit: Unit
    pitch: float | None = Field(default=None, gt=0)
    plane: Text | None = None
    pins: list[Pin] = Field(default_factory=list, max_length=2048)
    calibration: Text | None = None
    measured: list[ReferenceValue] = Field(default_factory=list, max_length=256)


class RGBD(Entry):
    """一帧 RGB 和 uint16 深度。scale 是每个原始计数对应的物理量。"""

    image: Text
    depth: Text
    unit: Unit
    scale: float = Field(gt=0)
    invalid: int = Field(ge=0, le=65535)
    alignment: Literal["registered", "unregistered", "unknown"] = "unknown"
    calibration: Text | None = None

    @model_validator(mode="after")
    def check_calibration(self):
        """已配准数据须随包提供标定资料。"""
        if self.alignment == "registered" and not self.calibration:
            raise ValueError("registered 配对缺少 calibration")
        return self


class Cloud(Entry):
    """点云的原始 PLY、坐标单位与坐标系。"""

    cloud: Text
    unit: Unit
    frame: Text


ENTRY_TYPES = dict(zip(MEDIA_TASKS, (Anomaly, Connector, RGBD, Cloud), strict=True))


class MediaManifest(MediaFields):
    """一个包对应一个任务类型；逐条校验专属字段。"""

    format_id: Literal["amvision.sample-media.v1"]
    task_type: Literal["anomaly", "connector-reference", "rgbd", "point-cloud"]
    samples: list[dict] = Field(min_length=1, max_length=100000)
