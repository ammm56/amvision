"""迁移已保存 Workflow 的旧输出参数和 Save 节点保存契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


WORKFLOW_SAVE_LOCATION_MIGRATION_COMMAND = "migrate-workflow-save-locations"
_OLD_PARAMETER_NAMES = ("output_dir", "output_object_key")
_NODE_OLD_PARAMETER_NAMES = {
    "core.output.json-save-local": ("local_path",),
    "core.output.csv-append-local": ("local_path",),
    "core.io.batch-files-relocate": ("target_directory",),
}
_SPLIT_SAVE_TARGET_NODE_TYPES = frozenset(
    {
        "core.io.image-save",
        "core.io.video-save",
        "core.output.json-save-local",
        "core.output.text-save-local",
    }
)
_SAVE_LOCATION_INPUT_NODE_TYPES = frozenset(
    {
        "core.output.csv-append-local",
        "core.io.batch-files-relocate",
    }
)


@dataclass(frozen=True)
class WorkflowSaveLocationMigrationResult:
    """描述一次 Workflow 保存位置字段迁移结果。"""

    scanned_files: int
    changed_files: tuple[str, ...]
    changed_nodes: int
    confirmed: bool


def migrate_workflow_save_locations(
    *,
    dataset_storage: LocalDatasetStorage,
    confirm: bool,
) -> WorkflowSaveLocationMigrationResult:
    """迁移正式模板和当前 App Runtime 快照，不改写历史 Preview 审计快照。"""

    candidate_paths = _list_candidate_paths(dataset_storage)
    changed_payloads: list[tuple[str, dict[str, object]]] = []
    changed_nodes = 0
    for object_key in candidate_paths:
        raw_payload = dataset_storage.read_json(object_key)
        if not isinstance(raw_payload, dict):
            raise InvalidRequestError(
                "Workflow 模板必须是 JSON 对象",
                details={"object_key": object_key},
            )
        payload = dict(raw_payload)
        current_changed_nodes = migrate_workflow_template_payload(payload)
        if current_changed_nodes:
            changed_payloads.append((object_key, payload))
            changed_nodes += current_changed_nodes

    if confirm:
        for object_key, payload in changed_payloads:
            dataset_storage.write_json(object_key, payload)
    return WorkflowSaveLocationMigrationResult(
        scanned_files=len(candidate_paths),
        changed_files=tuple(object_key for object_key, _ in changed_payloads),
        changed_nodes=changed_nodes,
        confirmed=confirm,
    )


def migrate_workflow_template_payload(payload: dict[str, object]) -> int:
    """原地迁移单份 Workflow 模板，返回发生变化的节点数。"""

    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raise InvalidRequestError("Workflow 模板缺少 nodes 数组")
    raw_edges = payload.get("edges")
    if raw_edges is not None and not isinstance(raw_edges, list):
        raise InvalidRequestError("Workflow 模板 edges 必须是 JSON 数组")

    split_save_target_node_ids = {
        str(raw_node.get("node_id") or "")
        for raw_node in raw_nodes
        if isinstance(raw_node, dict)
        and raw_node.get("node_type_id") in _SPLIT_SAVE_TARGET_NODE_TYPES
        and raw_node.get("node_id")
    }
    for raw_edge in raw_edges or []:
        if not isinstance(raw_edge, dict):
            raise InvalidRequestError("Workflow edge 必须是 JSON 对象")
        if str(
            raw_edge.get("target_node_id") or ""
        ) in split_save_target_node_ids and raw_edge.get("target_port") in {
            "path",
            "save_location",
        }:
            raise InvalidRequestError(
                "旧动态保存位置不能自动拆分为保存目录和文件名",
                details={"edge_id": raw_edge.get("edge_id")},
            )

    changed_node_indexes: set[int] = set()
    node_indexes_by_id: dict[str, int] = {}
    save_location_input_node_ids: set[str] = set()
    for node_index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise InvalidRequestError("Workflow 节点必须是 JSON 对象")
        node_id = str(raw_node.get("node_id") or "")
        if node_id:
            node_indexes_by_id[node_id] = node_index
            if raw_node.get("node_type_id") in _SAVE_LOCATION_INPUT_NODE_TYPES:
                save_location_input_node_ids.add(node_id)
        raw_parameters = raw_node.get("parameters")
        if raw_parameters is None:
            continue
        if not isinstance(raw_parameters, dict):
            raise InvalidRequestError(
                "Workflow 节点 parameters 必须是 JSON 对象",
                details={"node_id": raw_node.get("node_id")},
            )
        node_type_id = str(raw_node.get("node_type_id") or "")
        legacy_video_changed = False
        if node_type_id == "core.io.video-save":
            legacy_video_changed = _migrate_video_save_parameters(
                raw_node,
                raw_parameters,
            )
        if node_type_id in _SPLIT_SAVE_TARGET_NODE_TYPES:
            split_target_changed = _migrate_split_save_target_parameters(
                raw_node,
                raw_parameters,
                node_type_id=node_type_id,
            )
            if legacy_video_changed or split_target_changed:
                changed_node_indexes.add(node_index)
            continue
        old_parameter_names = (
            *_OLD_PARAMETER_NAMES,
            *_NODE_OLD_PARAMETER_NAMES.get(node_type_id, ()),
        )
        old_values = [
            raw_parameters[name]
            for name in old_parameter_names
            if name in raw_parameters
        ]
        if not old_values:
            continue
        distinct_values = {repr(value) for value in old_values}
        if "save_location" in raw_parameters:
            distinct_values.add(repr(raw_parameters["save_location"]))
        if len(distinct_values) > 1:
            raise InvalidRequestError(
                "Workflow 节点包含冲突的保存位置参数",
                details={"node_id": raw_node.get("node_id")},
            )
        raw_parameters["save_location"] = old_values[0]
        for parameter_name in old_parameter_names:
            raw_parameters.pop(parameter_name, None)
        changed_node_indexes.add(node_index)

    for raw_edge in raw_edges or []:
        target_node_id = str(raw_edge.get("target_node_id") or "")
        if (
            target_node_id in save_location_input_node_ids
            and raw_edge.get("target_port") == "path"
        ):
            raw_edge["target_port"] = "save_location"
            changed_node_indexes.add(node_indexes_by_id[target_node_id])
    return len(changed_node_indexes)


def _migrate_split_save_target_parameters(
    raw_node: dict[str, object],
    parameters: dict[str, object],
    *,
    node_type_id: str,
) -> bool:
    """把 Save 节点的单文件路径拆成保存目录和文件名。"""

    old_parameter_names = (
        "save_location",
        "object_key",
        *_OLD_PARAMETER_NAMES,
        *_NODE_OLD_PARAMETER_NAMES.get(node_type_id, ()),
    )
    old_values = [
        parameters[name] for name in old_parameter_names if name in parameters
    ]
    if not old_values:
        new_names = ("save_directory", "file_name")
        if any(name in parameters for name in new_names) and not all(
            name in parameters for name in new_names
        ):
            raise InvalidRequestError(
                "Workflow Save 节点的新保存参数不完整",
                details={"node_id": raw_node.get("node_id")},
            )
        return False

    if len({repr(value) for value in old_values}) > 1:
        raise InvalidRequestError(
            "Workflow Save 节点包含冲突的旧保存位置参数",
            details={"node_id": raw_node.get("node_id")},
        )
    save_directory, file_name = _split_save_location(old_values[0])
    save_directory = save_directory.replace(
        "{timestamp}",
        "{YYYYMMDDhhmmssSSS}",
    )
    file_name = file_name.replace("{timestamp}", "{YYYYMMDDhhmmssSSS}")

    existing_directory = parameters.get("save_directory")
    existing_file_name = parameters.get("file_name")
    if existing_directory not in (None, save_directory) or existing_file_name not in (
        None,
        file_name,
    ):
        raise InvalidRequestError(
            "Workflow Save 节点包含冲突的新旧保存参数",
            details={"node_id": raw_node.get("node_id")},
        )

    parameters["save_directory"] = save_directory
    parameters["file_name"] = file_name
    if node_type_id != "core.output.text-save-local":
        parameters.setdefault("overwrite", True)
    for parameter_name in old_parameter_names:
        parameters.pop(parameter_name, None)
    return True


def _split_save_location(value: object) -> tuple[str, str]:
    """把旧单文件保存位置拆成目录与文件名。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError("Workflow Save 旧保存位置不能为空")

    windows_path = PureWindowsPath(normalized_value)
    if windows_path.drive or "\\" in normalized_value:
        directory = str(windows_path.parent)
        file_name = windows_path.name
    else:
        posix_path = PurePosixPath(normalized_value)
        directory = posix_path.parent.as_posix()
        file_name = posix_path.name
    if directory in {"", "."} or not file_name:
        raise InvalidRequestError(
            "Workflow Save 旧保存位置必须同时包含目录和文件名",
            details={"save_location": value},
        )
    return directory, file_name


def _migrate_video_save_parameters(
    raw_node: dict[str, object],
    parameters: dict[str, object],
) -> bool:
    """把 Video Save 的 transport/object_key/local_path 三字段收敛为 save_location。"""

    old_names = ("output_transport_kind", "object_key", "local_path")
    if not any(name in parameters for name in old_names):
        return False
    transport_kind = parameters.get("output_transport_kind", "storage")
    old_value = (
        parameters.get("local_path")
        if transport_kind == "local-path"
        else parameters.get("object_key")
    )
    if old_value in (None, ""):
        old_value = ""
    if "save_location" in parameters and parameters["save_location"] != old_value:
        raise InvalidRequestError(
            "Workflow Video Save 节点包含冲突的保存位置参数",
            details={"node_id": raw_node.get("node_id")},
        )
    parameters["save_location"] = old_value
    for parameter_name in old_names:
        parameters.pop(parameter_name, None)
    return True


def _list_candidate_paths(dataset_storage: LocalDatasetStorage) -> tuple[str, ...]:
    """列出正式模板和生产 App Runtime 快照。"""

    patterns = (
        "workflows/projects/**/template.json",
        "workflows/runtime/app-runtimes/**/template.snapshot.json",
    )
    paths: set[str] = set()
    for pattern in patterns:
        for path in dataset_storage.root_dir.glob(pattern):
            if path.is_file():
                paths.add(_to_object_key(dataset_storage, path))
    return tuple(sorted(paths))


def _to_object_key(dataset_storage: LocalDatasetStorage, path: Path) -> str:
    """把 ObjectStore 根目录下的文件转为稳定 object key。"""

    return path.relative_to(dataset_storage.root_dir).as_posix()
