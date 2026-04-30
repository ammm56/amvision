"""Model 聚合仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.models.model_records import Model, ModelBuild, ModelScopeKind, ModelVersion


class ModelRepository(Protocol):
    """描述 Model、ModelVersion、ModelBuild 的持久化边界。"""

    def list_models(
        self,
        *,
        scope_kind: ModelScopeKind | None = None,
        model_name: str | None = None,
        model_scale: str | None = None,
        task_type: str | None = None,
        limit: int | None = None,
    ) -> tuple[Model, ...]:
        """按公开筛选条件列出 Model。

        参数：
        - scope_kind：模型作用域类型；为空时不过滤。
        - model_name：模型名；为空时不过滤。
        - model_scale：模型 scale；为空时不过滤。
        - task_type：任务类型；为空时不过滤。
        - limit：最大返回数量；为空时不限制。

        返回：
        - 满足条件的 Model 列表。
        """

        ...

    def find_model(
        self,
        *,
        project_id: str | None,
        scope_kind: ModelScopeKind,
        model_name: str,
        model_scale: str,
        task_type: str,
    ) -> Model | None:
        """按自然键查找一个 Model。

        参数：
    - project_id：所属项目 id；平台基础模型时为空。
        - scope_kind：模型作用域类型。
        - model_name：模型名。
        - model_scale：模型 scale。
        - task_type：任务类型。

        返回：
        - 读取到的 Model；不存在时返回 None。
        """

        ...

    def save_model(self, model: Model) -> None:
        """保存一个 Model。

        参数：
        - model：要保存的 Model。
        """

        ...

    def get_model(self, model_id: str) -> Model | None:
        """按 id 读取 Model。

        参数：
        - model_id：Model id。

        返回：
        - 读取到的 Model；不存在时返回 None。
        """

        ...

    def save_model_version(self, model_version: ModelVersion) -> None:
        """保存一个 ModelVersion。

        参数：
        - model_version：要保存的 ModelVersion。
        """

        ...

    def get_model_version(self, model_version_id: str) -> ModelVersion | None:
        """按 id 读取 ModelVersion。

        参数：
        - model_version_id：ModelVersion id。

        返回：
        - 读取到的 ModelVersion；不存在时返回 None。
        """

        ...

    def list_model_versions(self, model_id: str) -> tuple[ModelVersion, ...]:
        """按 Model id 列出所有 ModelVersion。

        参数：
        - model_id：Model id。

        返回：
        - 该 Model 下的 ModelVersion 列表。
        """

        ...

    def save_model_build(self, model_build: ModelBuild) -> None:
        """保存一个 ModelBuild。

        参数：
        - model_build：要保存的 ModelBuild。
        """

        ...

    def get_model_build(self, model_build_id: str) -> ModelBuild | None:
        """按 id 读取 ModelBuild。

        参数：
        - model_build_id：ModelBuild id。

        返回：
        - 读取到的 ModelBuild；不存在时返回 None。
        """

        ...

    def list_model_builds(self, model_id: str) -> tuple[ModelBuild, ...]:
        """按 Model id 列出所有 ModelBuild。

        参数：
        - model_id：Model id。

        返回：
        - 该 Model 下的 ModelBuild 列表。
        """

        ...