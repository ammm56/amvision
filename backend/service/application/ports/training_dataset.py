"""训练数据的已准备文件视图；对象存储负责在执行前完成下载或本地化。"""

from pathlib import Path
from typing import Protocol


class TrainingDatasetFiles(Protocol):
    """只暴露训练读取所需的已准备文件，不暴露上传、删除或元数据登记。"""

    def resolve_filesystem_path(self, relative_path: str) -> Path:
        """把 manifest 中的相对文件键解析为本次执行可读取的路径。"""
        ...

    def read_json(self, relative_path: str) -> dict[str, object]:
        """读取相对文件键对应的 JSON 标注，路径与资源约束由适配器负责。"""
        ...
