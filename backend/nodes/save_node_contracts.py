"""所有 Save 节点共用的保存目标端口和参数 schema。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.service.application.errors import InvalidRequestError


def read_save_overwrite(
    raw_value: object,
    *,
    node_label: str,
    default: bool = False,
) -> bool:
    """严格读取 Save 节点统一的覆盖开关。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(f"{node_label} 的 overwrite 必须是布尔值")


def build_save_target_input_ports(
    *,
    include_overwrite: bool,
) -> tuple[NodePortDefinition, ...]:
    """构造保存目录、文件名及可选覆盖参数端口。"""

    ports = [
        NodePortDefinition(
            name="save_directory",
            display_name="Save Directory",
            payload_type_id="value.v1",
            required=False,
        ),
        NodePortDefinition(
            name="file_name",
            display_name="File Name",
            payload_type_id="value.v1",
            required=False,
        ),
    ]
    if include_overwrite:
        ports.append(
            NodePortDefinition(
                name="overwrite",
                display_name="Overwrite",
                payload_type_id="value.v1",
                required=False,
            )
        )
    return tuple(ports)


def build_save_target_parameter_input_bindings(
    *,
    include_overwrite: bool,
) -> tuple[NodeParameterInputBinding, ...]:
    """构造与保存目标端口一一对应的动态参数绑定。"""

    parameter_names = ["save_directory", "file_name"]
    if include_overwrite:
        parameter_names.append("overwrite")
    return tuple(
        NodeParameterInputBinding(
            parameter_name=parameter_name,
            input_port_name=parameter_name,
        )
        for parameter_name in parameter_names
    )


def build_save_target_parameter_properties(
    *,
    overwrite_default: bool | None,
    file_name_example: str,
) -> dict[str, object]:
    """构造统一保存目录、文件名和覆盖参数 schema。"""

    file_name_description = (
        f"完整单级文件名；支持自由组合的通用日期时间块，例如 {file_name_example}。"
    )
    file_name_description_en = (
        "Complete single-level file name. Shared date-time fields can be "
        f"combined freely, for example {file_name_example}."
    )

    properties: dict[str, object] = {
        "save_directory": {
            "type": "string",
            "title": "保存目录",
            "description": "相对目录保存到 ObjectStore，绝对目录保存到 runtime 主机磁盘；支持 workflow 上下文和通用日期时间块。",
            "x-amvision-i18n": {
                "title": {
                    "zh-CN": "保存目录",
                    "en-US": "Save directory",
                },
                "description": {
                    "zh-CN": "相对目录保存到 ObjectStore，绝对目录保存到 runtime 主机磁盘；支持 workflow 上下文和通用日期时间块。",
                    "en-US": "A relative directory saves to ObjectStore; an absolute directory saves to the runtime host filesystem. Workflow context and shared date-time blocks are supported.",
                },
            },
            "x-amvision-ui": {"order": 10},
        },
        "file_name": {
            "type": "string",
            "title": "文件名",
            "description": file_name_description,
            "x-amvision-i18n": {
                "title": {
                    "zh-CN": "文件名",
                    "en-US": "File name",
                },
                "description": {
                    "zh-CN": file_name_description,
                    "en-US": file_name_description_en,
                },
            },
            "x-amvision-ui": {"order": 20},
        },
    }
    if overwrite_default is not None:
        properties["overwrite"] = {
            "type": "boolean",
            "title": "覆盖已有文件",
            "description": "启用时覆盖精确文件名；关闭时在重名文件后自动追加 _001、_002。",
            "default": overwrite_default,
            "x-amvision-i18n": {
                "title": {
                    "zh-CN": "覆盖已有文件",
                    "en-US": "Overwrite existing file",
                },
                "description": {
                    "zh-CN": "启用时覆盖精确文件名；关闭时在重名文件后自动追加 _001、_002。",
                    "en-US": "Overwrite the exact name when enabled; otherwise append _001, _002 on conflicts.",
                },
            },
            "x-amvision-ui": {"order": 30},
        }
    return properties


def build_save_target_required_parameters(
    *,
    include_overwrite: bool,
) -> list[str]:
    """返回保存节点需要具备固定值或动态连接的参数名称。"""

    required = ["save_directory", "file_name"]
    if include_overwrite:
        required.append("overwrite")
    return required
