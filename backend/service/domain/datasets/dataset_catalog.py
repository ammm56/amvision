"""数据集工作区分页仓储边界；业务层不依赖具体数据库。"""

from __future__ import annotations

from typing import Protocol


class DatasetCatalog(Protocol):
    """目录编辑、固定版本和分页样本的查询能力。"""

    def count(self, project_id: str) -> int:
        """目录中的数据集数量，不把遗留空文件夹作为资源。"""
        ...

    def ensure(
        self,
        project_id: str,
        dataset_id: str,
        task_type: str,
        created_at: str = "",
        *,
        display_name: str = "",
        description: str = "",
    ) -> None:
        """首次导入或直接保存版本时登记身份；同一数据集不混合不同任务类型。"""
        ...

    def get(self, project_id: str, dataset_id: str) -> dict:
        """按项目和身份读取目录，避免跨项目同名混淆。"""
        ...

    def edit(
        self,
        project_id: str,
        dataset_id: str,
        *,
        display_name: str,
        description: str,
        revision: str,
    ) -> dict:
        """原子检查 revision 并更新信息，不更改版本或正在使用的引用。"""
        ...

    def list(
        self,
        project_id: str,
        *,
        q: str = "",
        task_type: str = "",
        state: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """目录分页；最新版本按创建时间排序，不能按随机 id 推断时间。"""
        ...

    def versions(
        self,
        project_id: str,
        *,
        dataset_id: str = "",
        q: str = "",
        task_type: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """读取版本列表，单页最多由 API 限制为 100 条。"""
        ...

    def version_summaries(self, ids: list[str]) -> list[dict]:
        """仅聚合当前页版本的计数，不读取样本数组。"""
        ...

    def version(self, dataset_id: str, version_id: str) -> dict:
        """读取单版本身份与轻量统计，供路由校验项目权限。"""
        ...

    def category_statistics(self, version_id: str) -> dict:
        """按真实标注聚合图像数及对象数；一张图可归属多个类别。"""
        ...

    def import_report(self, version_id: str) -> dict:
        """读取真实导入检查报告；记录已删时不伪造通过结果。"""
        ...

    def version_identity(self, dataset_id: str, version_id: str) -> dict:
        """媒体及分页请求只读取身份，不重复聚合整版本计数。"""
        ...

    def samples(
        self,
        version_id: str,
        *,
        q: str = "",
        split: str = "",
        category_id: int | None = None,
        annotation_state: str = "",
        sort: str = "image_id",
        offset: int = 0,
        limit: int = 24,
    ) -> dict:
        """过滤样本后分页，仅加载本页标注；exists 避免多对象重复计数。"""
        ...

    def sample(self, version_id: str, sample_id: str) -> dict:
        """精确读取当前版本内样本，不能用其他版本的样本 ID 绕过边界。"""
        ...

    def records(
        self,
        project_id: str,
        kind: str,
        *,
        q: str = "",
        status: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """导入导出执行记录独立分页，终态历史不会挤占全部页面。"""
        ...

    def selection_summary(self, version_id: str, raw: dict) -> dict:
        """统计固定版本内选择的样本和划分数量。"""
        ...

    def selected_ids(self, version_id: str, raw: dict) -> set[str]:
        """后台操作使用同一查询语义取得样本身份。"""
        ...

    def jobs(
        self, project_id: str, version_id: str, *, offset: int = 0, limit: int = 20
    ) -> dict:
        """分页读取固定版本的工作区检查与操作。"""
        ...

    def file_samples(
        self, version_id: str, path: str, *, offset: int = 0, limit: int = 20
    ) -> dict:
        """查询受管文件与样本的真实关系。"""
        ...
