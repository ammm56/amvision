"""Project 公开文件 file_id 解析 helper。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.object_store.object_key_layout import parse_public_project_file_id


@dataclass(frozen=True)
class PublicProjectFileReference:
    """描述一次 Project 公开文件解析结果。

    字段：
    - project_id：公开文件所属 Project id。
    - object_key：公开文件在 ObjectStore 中的 object key。
    """

    project_id: str
    object_key: str


def resolve_public_project_file_reference(
    *,
    dataset_storage: LocalDatasetStorage,
    file_id: str,
    expected_project_id: str | None = None,
    field_name: str = "input_file_id",
) -> PublicProjectFileReference:
    """解析并校验一个 Project 公开文件 id。

    参数：
    - dataset_storage：本地文件存储服务。
    - file_id：待解析的公开文件 id。
    - expected_project_id：可选 Project 约束；提供后必须与 file_id 中的 Project 一致。
    - field_name：错误消息中使用的字段名。

    返回：
    - PublicProjectFileReference：解析后的 Project 与 object key 信息。
    """

    normalized_file_id = file_id.strip() if isinstance(file_id, str) else ""
    if not normalized_file_id:
        raise InvalidRequestError(f"{field_name} 不能为空")
    try:
        project_id, object_key = parse_public_project_file_id(normalized_file_id)
    except ValueError as error:
        raise InvalidRequestError(
            f"{field_name} 不是合法的 Project 公开文件 id",
            details={field_name: normalized_file_id},
        ) from error
    if expected_project_id is not None and project_id != expected_project_id:
        raise InvalidRequestError(
            f"{field_name} 与当前 Project 不匹配",
            details={
                field_name: normalized_file_id,
                "expected_project_id": expected_project_id,
                "project_id": project_id,
            },
        )
    if not dataset_storage.resolve(object_key).is_file():
        raise InvalidRequestError(
            f"{field_name} 对应的本地文件不存在",
            details={field_name: normalized_file_id, "object_key": object_key},
        )
    return PublicProjectFileReference(project_id=project_id, object_key=object_key)