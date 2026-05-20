"""workflow preview run 即时显示输出 helper。"""

from __future__ import annotations

import mimetypes

from backend.contracts.workflows.resource_semantics import build_workflow_preview_run_storage_dir


WORKFLOW_PREVIEW_RUN_ID_METADATA_KEY = "workflow_preview_run_id"
WORKFLOW_PREVIEW_DISPLAY_OUTPUTS_KEY = "workflow_preview_display_outputs"


def register_preview_display_output(
    execution_metadata: dict[str, object],
    *,
    node_id: str,
    node_type_id: str,
    output_name: str,
    payload: dict[str, object],
) -> None:
    """登记一次只用于本次 Preview Run 响应的节点显示输出。

    参数：
    - execution_metadata：当前 workflow 执行元数据。
    - node_id：产生显示输出的节点实例 id。
    - node_type_id：产生显示输出的节点类型 id。
    - output_name：产生显示输出的节点输出端口名称。
    - payload：直接返回给前端显示的 JSON payload；该值不进入持久化记录。
    """

    normalized_node_id = _normalize_text(node_id)
    normalized_node_type_id = _normalize_text(node_type_id)
    normalized_output_name = _normalize_text(output_name)
    if not normalized_node_id or not normalized_node_type_id or not normalized_output_name:
        return
    raw_outputs = execution_metadata.get(WORKFLOW_PREVIEW_DISPLAY_OUTPUTS_KEY)
    if not isinstance(raw_outputs, list):
        raw_outputs = []
        execution_metadata[WORKFLOW_PREVIEW_DISPLAY_OUTPUTS_KEY] = raw_outputs
    raw_outputs.append(
        {
            "node_id": normalized_node_id,
            "node_type_id": normalized_node_type_id,
            "output_name": normalized_output_name,
            "payload": dict(payload),
        }
    )


def list_preview_display_outputs(execution_metadata: dict[str, object]) -> tuple[dict[str, object], ...]:
    """读取执行期登记的 Preview Run 即时显示输出。

    参数：
    - execution_metadata：当前 workflow 执行元数据。

    返回：
    - tuple[dict[str, object], ...]：可直接进入本次响应的显示输出列表。
    """

    raw_outputs = execution_metadata.get(WORKFLOW_PREVIEW_DISPLAY_OUTPUTS_KEY)
    if not isinstance(raw_outputs, list):
        return ()
    normalized_outputs: list[dict[str, object]] = []
    for raw_output in raw_outputs:
        if not isinstance(raw_output, dict):
            continue
        node_id = _normalize_text(raw_output.get("node_id"))
        node_type_id = _normalize_text(raw_output.get("node_type_id"))
        output_name = _normalize_text(raw_output.get("output_name"))
        payload = raw_output.get("payload")
        if not node_id or not node_type_id or not output_name or not isinstance(payload, dict):
            continue
        normalized_outputs.append(
            {
                "node_id": node_id,
                "node_type_id": node_type_id,
                "output_name": output_name,
                "payload": dict(payload),
            }
        )
    return tuple(normalized_outputs)


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

    guessed_extension = mimetypes.guess_extension(media_type.strip()) if isinstance(media_type, str) else None
    if isinstance(guessed_extension, str) and guessed_extension:
        return guessed_extension
    return ".png"