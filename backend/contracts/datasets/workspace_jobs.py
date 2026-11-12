"""数据集工作区后台操作的 v1 请求契约。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.datasets.sample_selection import DatasetSampleSelection


class DatasetDerivation(BaseModel):
    """版本操作配置：样本选择、类别改名、可复现划分和版本说明。"""

    model_config = ConfigDict(extra="forbid")
    selection: DatasetSampleSelection | None = None
    exclude_selection: DatasetSampleSelection | None = None
    category_names: dict[int, str] = Field(default_factory=dict, max_length=1000)
    description: str = Field(default="", max_length=500)
    split_ratios: tuple[int, int, int] | None = None
    seed: int = Field(default=42, ge=0, le=2147483647)
    group_key: str = Field(default="", max_length=100, pattern=r"^[\w.-]*$")
    handoff_export_id: str | None = Field(default=None, max_length=255)
    returned_version_id: str | None = Field(default=None, max_length=255)
    keep_missing: bool = False
    accept_image_changes: bool = False

    @model_validator(mode="after")
    def validate_rules(self):
        """禁止空名称、隐式合并类别和无效划分。"""
        if any(
            not value.strip() or len(value) > 255
            for value in self.category_names.values()
        ):
            raise ValueError("类别名称不能为空且不能超过 255 字符")
        if self.split_ratios is not None and (
            sum(self.split_ratios) != 100
            or any(n < 0 or n > 100 for n in self.split_ratios)
        ):
            raise ValueError("train、val、test 比例必须为非负整数且合计 100%")
        if self.group_key and self.split_ratios is None:
            raise ValueError("分组键仅用于重新划分")
        return self


class DatasetWorkspaceJobRequest(BaseModel):
    """客户端请求身份用于查询未知提交结果，不自动重放写入。"""

    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    operation: Literal[
        "quality",
        "derive-check",
        "derive",
        "compare",
        "revise",
        "return-check",
        "return-apply",
    ]
    config: DatasetDerivation = Field(default_factory=DatasetDerivation)
    compare_version_id: str | None = Field(default=None, max_length=255)
    checked_task_id: str | None = Field(default=None, max_length=255)
    expected_content_revision: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_operation(self):
        """实际创建必须基于已完成的预检查，比较必须有目标。"""
        if self.operation == "compare" and not self.compare_version_id:
            raise ValueError("请选择比较版本")
        if self.config.selection and self.config.exclude_selection:
            raise ValueError("不能同时保留所选和删除所选")
        if self.operation == "revise" and not self.config.exclude_selection:
            raise ValueError("请选择要从当前版本删除的样本")
        if self.operation in {"derive", "return-apply"} and not self.checked_task_id:
            raise ValueError("请先检查新版本配置")
        if self.operation.startswith("return-") and (
            not self.config.handoff_export_id or not self.config.returned_version_id
        ):
            raise ValueError("请选择交接导出和已导入的回传版本")
        return self
