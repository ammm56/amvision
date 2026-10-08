"""节点只借用执行准备层提供的计量资源，不扫描磁盘或数据库。"""

from collections.abc import Mapping

from backend.contracts.workflows.metrology import ResourceReference
from backend.service.application.errors import InvalidRequestError


def require_prepared_measurement_resource(request, parameter: str, kind: str):
    """验证引用与项目后取得只读资源；不能把客户端 metadata 视为可信资源。"""
    try:
        reference = ResourceReference.model_validate(request.parameters.get(parameter))
    except ValueError as exc:
        raise InvalidRequestError("计量节点缺少有效的资源版本引用") from exc
    if reference.kind != kind or reference.project_id != request.execution_metadata.get(
        "project_id"
    ):
        raise InvalidRequestError("计量资源类型或项目不匹配")
    resources = request.execution_metadata.get("prepared_measurement_resources")
    item = (
        resources.get(reference.model_dump_json())
        if isinstance(resources, Mapping)
        else None
    )
    if item is None:
        raise InvalidRequestError("计量资源尚未通过执行准备校验")
    return item
