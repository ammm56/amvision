"""ModelFile 仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.files.model_file import ModelFile


class ModelFileRepository(Protocol):
    """描述 ModelFile 的持久化边界。"""

    def save_model_file(self, model_file: ModelFile) -> None:
        """保存一个 ModelFile。

        参数：
        - model_file：要保存的 ModelFile。
        """

        ...

    def get_model_file(self, file_id: str) -> ModelFile | None:
        """按 id 读取一个 ModelFile。

        参数：
        - file_id：ModelFile id。

        返回：
        - 读取到的 ModelFile；不存在时返回 None。
        """

        ...

    def list_model_files(
        self,
        *,
        model_version_id: str | None = None,
        model_build_id: str | None = None,
    ) -> tuple[ModelFile, ...]:
        """按模型版本或 build 列出关联文件。

        参数：
        - model_version_id：可选的 ModelVersion id 过滤条件。
        - model_build_id：可选的 ModelBuild id 过滤条件。

        返回：
        - 满足过滤条件的 ModelFile 列表。
        """

        ...