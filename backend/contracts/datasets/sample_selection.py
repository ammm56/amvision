"""固定版本内样本选择；全部筛选保存条件，不向浏览器传输整套 ID。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetSampleSelection(BaseModel):
    """mode 区分显式样本和筛选快照；筛选不改变标注对象。"""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["ids", "filter"]
    sample_ids: list[str] = Field(default_factory=list, max_length=1000)
    q: str = Field(default="", max_length=200)
    split: Literal["", "train", "val", "test"] = ""
    category_id: int | None = None
    annotation_state: Literal["", "annotated", "empty"] = ""

    @model_validator(mode="after")
    def validate_scope(self):
        """拒绝空选择、重复 ID 和相互矛盾的选择规则。"""
        if self.mode == "ids":
            if not self.sample_ids or any(
                not s or len(s) > 255 for s in self.sample_ids
            ):
                raise ValueError("请选择至少一个有效样本")
            if len(set(self.sample_ids)) != len(self.sample_ids):
                raise ValueError("样本 ID 不能重复")
            if (
                self.q
                or self.split
                or self.category_id is not None
                or self.annotation_state
            ):
                raise ValueError("显式样本选择不能同时指定筛选条件")
        elif self.sample_ids:
            raise ValueError("全部筛选选择不能同时指定样本 ID")
        return self
