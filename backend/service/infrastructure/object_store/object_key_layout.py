"""ObjectStore 对象路径布局 helper。"""

from __future__ import annotations

from pathlib import PurePosixPath


RUNTIME_INPUTS_STORAGE_ROOT = "runtime/inputs"


def build_project_workflow_application_results_dir(
    *,
    project_id: str,
    application_id: str,
    workflow_run_id: str,
) -> str:
    """返回单个 workflow app run 的正式结果目录。

    参数：
    - project_id：所属 Project id。
    - application_id：流程应用 id。
    - workflow_run_id：当前 workflow run id。

    返回：
    - str：Project 结果域中的 workflow app run 根目录。
    """

    normalized_project_id = _normalize_segment(project_id, field_name="project_id")
    normalized_application_id = _normalize_segment(application_id, field_name="application_id")
    normalized_workflow_run_id = _normalize_segment(workflow_run_id, field_name="workflow_run_id")
    return (
        f"projects/{normalized_project_id}/results/workflow-applications/"
        f"{normalized_application_id}/runs/{normalized_workflow_run_id}"
    )


def build_runtime_inputs_dir(*, consumer: str, request_id: str) -> str:
    """返回运行时临时输入目录。

    参数：
    - consumer：输入消费方名称，例如 inference、validation、workflow-invoke。
    - request_id：当前请求 id。

    返回：
    - str：运行时临时输入目录。
    """

    normalized_consumer = _normalize_segment(consumer, field_name="consumer")
    normalized_request_id = _normalize_segment(request_id, field_name="request_id")
    return f"{RUNTIME_INPUTS_STORAGE_ROOT}/{normalized_consumer}/{normalized_request_id}"


def build_runtime_input_object_key(*, consumer: str, request_id: str, file_name: str) -> str:
    """返回运行时临时输入文件 object key。

    参数：
    - consumer：输入消费方名称。
    - request_id：当前请求 id。
    - file_name：目标文件名。

    返回：
    - str：运行时临时输入文件 object key。
    """

    normalized_file_name = _normalize_file_name(file_name)
    return f"{build_runtime_inputs_dir(consumer=consumer, request_id=request_id)}/{normalized_file_name}"


def build_public_project_object_namespace_patterns(*, project_id: str) -> tuple[str, ...]:
    """返回 Project 文件公开读取允许的命名空间模式。

    参数：
    - project_id：所属 Project id。

    返回：
    - tuple[str, ...]：公开读取允许的命名空间模式列表。
    """

    normalized_project_id = _normalize_segment(project_id, field_name="project_id")
    return (
        f"projects/{normalized_project_id}/inputs/**",
        f"projects/{normalized_project_id}/results/**",
        f"projects/{normalized_project_id}/datasets/*/versions/**",
        f"projects/{normalized_project_id}/datasets/*/exports/**",
    )


def is_public_project_object_key(*, project_id: str, object_key: str) -> bool:
    """判断 object key 是否属于 Project 文件公开读取面。

    参数：
    - project_id：所属 Project id。
    - object_key：待判断的 object key。

    返回：
    - bool：当前 object key 是否允许通过 Project 文件接口公开读取。
    """

    normalized_project_id = _normalize_segment(project_id, field_name="project_id")
    normalized_object_key = object_key.strip() if isinstance(object_key, str) else ""
    if not normalized_object_key:
        return False
    path_parts = PurePosixPath(normalized_object_key).parts
    if len(path_parts) < 3 or path_parts[:2] != ("projects", normalized_project_id):
        return False
    if path_parts[2] in {"inputs", "results"}:
        return True
    if len(path_parts) < 5 or path_parts[2] != "datasets":
        return False
    return path_parts[4] in {"versions", "exports"}


def _normalize_segment(value: str, *, field_name: str) -> str:
    """规范化单段路径标识。

    参数：
    - value：原始标识值。
    - field_name：字段名称。

    返回：
    - str：去空白后的单段路径标识。

    异常：
    - ValueError：当值为空或包含路径分隔符时抛出。
    """

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    if "/" in normalized_value or "\\" in normalized_value:
        raise ValueError(f"{field_name} 不能包含路径分隔符")
    return normalized_value


def _normalize_file_name(value: str) -> str:
    """规范化文件名或相对文件尾段。

    参数：
    - value：原始文件名。

    返回：
    - str：规范化后的文件名。

    异常：
    - ValueError：当文件名为空时抛出。
    """

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise ValueError("file_name 不能为空")
    return PurePosixPath(normalized_value).name