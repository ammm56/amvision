"""workflow Preview Run artifact 与上下文 helper。"""

from __future__ import annotations

import mimetypes

from backend.contracts.workflows.resource_semantics import build_workflow_preview_run_storage_dir


WORKFLOW_PREVIEW_RUN_ID_METADATA_KEY = "workflow_preview_run_id"


def read_preview_run_id(execution_metadata: dict[str, object]) -> str | None:
    """从执行元数据读取当前 Preview Run id。

    参数：
    - execution_metadata：当前 workflow 执行元数据。

    返回：
    - str | None：存在有效 Preview Run id 时返回字符串，否则返回 None。
    """

    preview_run_id = _normalize_text(execution_metadata.get(WORKFLOW_PREVIEW_RUN_ID_METADATA_KEY))
    return preview_run_id or None


def build_preview_run_artifact_object_key(
    *,
    preview_run_id: str,
    node_id: str,
    artifact_name: str,
    media_type: str,
) -> str:
    """构建属于 Preview Run 生命周期的 artifact object key。

    参数：
    - preview_run_id：所属 Preview Run id。
    - node_id：产生 artifact 的节点实例 id。
    - artifact_name：artifact 语义名称。
    - media_type：artifact 媒体类型。

    返回：
    - str：位于 workflows/runtime/preview-runs/{preview_run_id}/artifacts 下的 object key。
    """

    normalized_preview_run_id = _normalize_path_segment(preview_run_id, fallback="preview-run")
    normalized_node_id = _normalize_path_segment(node_id, fallback="node")
    normalized_artifact_name = _normalize_path_segment(artifact_name, fallback="artifact")
    extension = _infer_file_extension_from_media_type(media_type)
    return (
        f"{build_workflow_preview_run_storage_dir(normalized_preview_run_id)}/"
        f"artifacts/{normalized_node_id}/{normalized_artifact_name}{extension}"
    )


def is_preview_run_artifact_object_key(*, preview_run_id: str, object_key: str) -> bool:
    """判断 object key 是否属于指定 Preview Run 的 artifact 目录。

    参数：
    - preview_run_id：所属 Preview Run id。
    - object_key：待判断的 object key。

    返回：
    - bool：属于当前 Preview Run artifact 目录时返回 True。
    """

    normalized_preview_run_id = _normalize_path_segment(preview_run_id, fallback="preview-run")
    normalized_object_key = _normalize_text(object_key)
    artifact_prefix = f"{build_workflow_preview_run_storage_dir(normalized_preview_run_id)}/artifacts/"
    return normalized_object_key.startswith(artifact_prefix)


def _normalize_text(value: object) -> str:
    """把可选文本值规范化为去空白字符串。"""

    return value.strip() if isinstance(value, str) else ""


def _normalize_path_segment(value: str, *, fallback: str) -> str:
    """把单个 object key 片段规范化为不含路径分隔符的值。"""

    normalized_value = _normalize_text(value).replace("\\", "_").replace("/", "_")
    return normalized_value or fallback


def _infer_file_extension_from_media_type(media_type: str) -> str:
    """根据媒体类型推断 artifact 文件扩展名。"""

    if isinstance(media_type, str) and media_type.strip().lower() == "image/raw":
        return ".jpg"
    guessed_extension = mimetypes.guess_extension(media_type.strip()) if isinstance(media_type, str) else None
    if isinstance(guessed_extension, str) and guessed_extension:
        return guessed_extension
    return ".png"
