"""workflow runtime invoke 请求体解析测试。"""

from __future__ import annotations

import pytest

from backend.service.api.rest.v1.routes.workflow_runtime_support.schemas import WorkflowRuntimeInvokeRequestBody


def test_runtime_invoke_body_accepts_top_level_public_inputs() -> None:
    """公开 App 输入 id 放在顶层时应被解析为 input_bindings。"""

    image_payload = {"image_base64": "abc", "media_type": "image/png"}
    body = WorkflowRuntimeInvokeRequestBody.model_validate(
        {
            "request_image_base64": image_payload,
            "timeout_seconds": 60,
            "execution_metadata": {"source": "direct-http"},
        }
    )

    assert body.resolve_input_bindings() == {"request_image_base64": image_payload}
    assert body.timeout_seconds == 60
    assert body.execution_metadata == {"source": "direct-http"}


def test_runtime_invoke_body_accepts_wrapped_input_bindings() -> None:
    """平台内部 input_bindings 包装字段仍应能被解析。"""

    body = WorkflowRuntimeInvokeRequestBody.model_validate(
        {
            "input_bindings": {"request_image_ref": {"object_key": "project/files/image.jpg"}},
            "execution_metadata": {"source": "web-ui-app-detail"},
        }
    )

    assert body.resolve_input_bindings() == {
        "request_image_ref": {"object_key": "project/files/image.jpg"}
    }


def test_runtime_invoke_body_rejects_mixed_input_shapes() -> None:
    """同一个请求不能同时使用包装字段和顶层公开输入。"""

    body = WorkflowRuntimeInvokeRequestBody.model_validate(
        {
            "input_bindings": {"request_image_ref": {"object_key": "project/files/image.jpg"}},
            "request_image_base64": {"image_base64": "abc", "media_type": "image/png"},
        }
    )

    with pytest.raises(ValueError, match="不能同时使用 input_bindings"):
        body.resolve_input_bindings()
