"""Barcode Display 节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.nodes.runtime_support import build_response_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.barcode_protocol_nodes.backend.support import build_barcode_results_summary


NODE_PACK_ID = "barcode.display-nodes"
NODE_TYPE_ID = "custom.barcode.display-response"
RESULT_SOURCE_NODE_PACK_ID = "barcode.protocol-nodes"


def _handle_display_response_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把条码结果摘要和标注图片组装成 response-body.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 body 输出的 response-body.v1 payload。
    """

    summary = build_barcode_results_summary(request.input_values.get("results"))
    response_body: dict[str, object] = {
        "code": _read_response_code(request.parameters.get("code")),
        "message": _read_response_message(request.parameters.get("message")),
        "data": _build_response_data(request=request, summary=summary),
        "meta": _build_response_meta(request.input_values.get("meta")),
    }
    return {"body": response_body}


def _build_response_data(
    *,
    request: WorkflowNodeExecutionRequest,
    summary: dict[str, object],
) -> dict[str, object]:
    """构造 display-response 的 data 对象。

    参数：
    - request：当前 workflow 节点执行请求。
    - summary：来自 barcode.protocol-nodes 的结果摘要。

    返回：
    - dict[str, object]：最终写入 response body 的 data 对象。
    """

    data: dict[str, object] = {
        "requested_format": summary.get("requested_format"),
        "count": summary.get("count"),
        "matched_formats": list(summary.get("matched_formats", [])),
        "result_table": _build_result_table(summary=summary, request=request),
    }
    annotated_image_payload = request.input_values.get("annotated_image")
    if annotated_image_payload is not None:
        data["annotated_image"] = _build_image_preview(request=request, image_payload=annotated_image_payload)
    return data


def _build_image_preview(*, request: WorkflowNodeExecutionRequest, image_payload: object) -> dict[str, object]:
    """把标注图片转换成响应里的 image-preview 结构。

    参数：
    - request：当前 workflow 节点执行请求。
    - image_payload：输入端口上的 image-ref.v1 payload。

    返回：
    - dict[str, object]：可直接进入 response body 的 image-preview 对象。
    """

    output_object_key = request.parameters.get("output_object_key")
    normalized_output_object_key = (
        output_object_key.strip()
        if isinstance(output_object_key, str) and output_object_key.strip()
        else None
    )
    response_image = build_response_image_payload(
        request,
        image_payload=image_payload,
        response_transport_mode=_read_response_transport_mode(
            request.parameters.get("response_transport_mode"),
        ),
        object_key=normalized_output_object_key,
        variant_name="barcode-display-response",
    )
    return {
        "type": "image-preview",
        "title": _read_non_empty_string_parameter(
            request.parameters.get("image_title"),
            field_name="image_title",
            default_value="Detected Barcode Image",
        ),
        "image": response_image,
    }


def _build_result_table(
    *,
    summary: dict[str, object],
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把条码结果摘要投影成固定列的表格预览对象。

    参数：
    - summary：条码结果摘要。
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：table-preview 结构。
    """

    rows = [dict(item) for item in summary.get("items", []) if isinstance(item, dict)]
    return {
        "type": "table-preview",
        "title": _read_non_empty_string_parameter(
            request.parameters.get("table_title"),
            field_name="table_title",
            default_value="Barcode Results",
        ),
        "columns": [
            {"key": "index", "label": "Index"},
            {"key": "format", "label": "Format"},
            {"key": "text", "label": "Text"},
            {"key": "valid", "label": "Valid"},
        ],
        "rows": rows,
        "row_count": len(rows),
    }


def _build_response_meta(meta_payload: object) -> dict[str, object]:
    """构造 response body 中的 meta 对象。

    参数：
    - meta_payload：可选的 value.v1 meta 输入 payload。

    返回：
    - dict[str, object]：最终 meta 对象。
    """

    meta: dict[str, object] = {
        "node_pack": NODE_PACK_ID,
        "result_source_pack": RESULT_SOURCE_NODE_PACK_ID,
    }
    if meta_payload is None:
        return meta
    if not isinstance(meta_payload, dict):
        raise InvalidRequestError("barcode display 节点的 meta 输入必须是 value.v1 对象")
    meta_value = meta_payload.get("value")
    if meta_value is None:
        return meta
    if not isinstance(meta_value, dict):
        raise InvalidRequestError("barcode display 节点的 meta.value 必须是对象")
    normalized_meta = dict(meta_value)
    normalized_meta["node_pack"] = NODE_PACK_ID
    normalized_meta["result_source_pack"] = RESULT_SOURCE_NODE_PACK_ID
    return normalized_meta


def _read_response_code(raw_value: object) -> int:
    """读取静态响应 code。

    参数：
    - raw_value：节点参数中的 code 值。

    返回：
    - int：最终响应 code。
    """

    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("barcode display 节点的 code 参数必须是整数")
    return raw_value


def _read_response_message(raw_value: object) -> str:
    """读取静态响应 message。

    参数：
    - raw_value：节点参数中的 message 值。

    返回：
    - str：最终响应 message。
    """

    return _read_non_empty_string_parameter(raw_value, field_name="message", default_value="decoded")


def _read_response_transport_mode(raw_value: object) -> str:
    """读取图片响应传输模式。

    参数：
    - raw_value：节点参数中的 response_transport_mode 值。

    返回：
    - str：规范化后的图片响应传输模式。
    """

    if raw_value is None:
        return "inline-base64"
    if raw_value not in {"inline-base64", "storage-ref"}:
        raise InvalidRequestError(
            "barcode display 节点的 response_transport_mode 只能是 inline-base64 或 storage-ref"
        )
    return str(raw_value)


def _read_non_empty_string_parameter(raw_value: object, *, field_name: str, default_value: str) -> str:
    """读取非空字符串参数。

    参数：
    - raw_value：原始参数值。
    - field_name：参数名。
    - default_value：缺省时返回的默认值。

    返回：
    - str：规范化后的字符串参数。
    """

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"barcode display 节点的 {field_name} 参数必须是非空字符串")
    return raw_value.strip()


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 Barcode Display 节点包中的 python-callable 节点。

    参数：
    - context：当前 node pack 的注册上下文。
    """

    context.register_python_callable(NODE_TYPE_ID, _handle_display_response_node)