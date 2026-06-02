"""YOLOE / SAM3 WorkflowAppRuntime 受控接入 smoke。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.api.app import create_app
from backend.service.application.local_buffers import LocalBufferBrokerSettings
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_test_runtime


_PROJECT_ID = "project-1"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_CUSTOM_NODES_ROOT = _WORKSPACE_ROOT / "custom_nodes"
_YOLOE_MANIFEST_PATH = _CUSTOM_NODES_ROOT / "yoloe_open_vocab_nodes" / "manifest.json"
_SAM3_MANIFEST_PATH = _CUSTOM_NODES_ROOT / "sam3_segment_nodes" / "manifest.json"


def test_yoloe_text_prompt_workflow_app_runtime_controlled_enable_smoke(tmp_path: Path) -> None:
    """验证 YOLOE text-prompt 可以按受控启用路径进入 WorkflowAppRuntime。"""

    with _temporary_pack_default_enabled(
        {
            _YOLOE_MANIFEST_PATH: False,
            _SAM3_MANIFEST_PATH: False,
        }
    ):
        client, session_factory, dataset_storage = _create_runtime_api_client(
            tmp_path,
            database_name="workflow-app-runtime-yoloe-smoke.db",
        )
        headers = build_test_headers(scopes="workflows:read,workflows:write")

        try:
            with client:
                _assert_pack_catalog_disabled(
                    client=client,
                    headers=headers,
                    node_pack_id="yoloe.open-vocab-nodes",
                )
                _enable_pack_and_assert_loaded(
                    client=client,
                    headers=headers,
                    node_pack_id="yoloe.open-vocab-nodes",
                )
                _assert_pack_catalog_enabled(
                    client=client,
                    headers=headers,
                    node_pack_id="yoloe.open-vocab-nodes",
                    expected_node_type_ids=("custom.yoloe.text-prompt-detect",),
                )

                workflow_service = LocalWorkflowJsonService(
                    dataset_storage=dataset_storage,
                    node_catalog_registry=client.app.state.node_catalog_registry,
                )
                workflow_service.save_template(
                    project_id=_PROJECT_ID,
                    template=_build_yoloe_text_prompt_template(),
                )
                workflow_service.save_application(
                    project_id=_PROJECT_ID,
                    application=_build_yoloe_text_prompt_application(),
                )

                image_object_key = _write_test_image(dataset_storage, object_key="projects/project-1/inputs/yoloe-smoke.png")
                workflow_runtime_id = _create_and_start_runtime(
                    client=client,
                    headers=headers,
                    application_id="yoloe-text-prompt-smoke-app",
                    display_name="YOLOE Text Prompt Smoke Runtime",
                )
                health_response = client.get(
                    f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                    headers=headers,
                )
                invoke_response = client.post(
                    f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                    headers=headers,
                    json={
                        "input_bindings": {
                            "request_image": {
                                "object_key": image_object_key,
                                "media_type": "image/png",
                            },
                            "request_prompts": _build_text_prompts_payload(),
                        },
                        "execution_metadata": {
                            "scenario": "yoloe-workflow-app-runtime-smoke",
                            "trigger_source": "sync-api",
                        },
                    },
                )
                stop_response = client.post(
                    f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                    headers=headers,
                )
        finally:
            session_factory.engine.dispose()

    assert health_response.status_code == 200
    assert health_response.json()["observed_state"] == "running"
    assert invoke_response.status_code == 200
    assert stop_response.status_code == 200
    assert stop_response.json()["observed_state"] == "stopped"

    payload = invoke_response.json()
    assert payload["state"] == "succeeded"
    assert set(payload["outputs"]) == {"detections", "regions", "summary"}
    assert isinstance(payload["outputs"]["detections"]["items"], list)
    assert payload["outputs"]["regions"]["count"] == len(payload["outputs"]["regions"]["items"])

    summary_payload = payload["outputs"]["summary"]
    assert summary_payload["project_native"] is True
    assert summary_payload["inference_mode"] == "text-prompt"
    assert summary_payload["prompt_group_count"] == 2
    assert summary_payload["positive_prompt_count"] == 2
    assert summary_payload["negative_prompt_count"] == 2


def test_sam3_semantic_workflow_app_runtime_controlled_enable_smoke(tmp_path: Path) -> None:
    """验证 SAM3 semantic-segment 可以按受控启用路径进入 WorkflowAppRuntime。"""

    with _temporary_pack_default_enabled(
        {
            _YOLOE_MANIFEST_PATH: False,
            _SAM3_MANIFEST_PATH: False,
        }
    ):
        client, session_factory, dataset_storage = _create_runtime_api_client(
            tmp_path,
            database_name="workflow-app-runtime-sam3-smoke.db",
        )
        headers = build_test_headers(scopes="workflows:read,workflows:write")

        try:
            with client:
                _assert_pack_catalog_disabled(
                    client=client,
                    headers=headers,
                    node_pack_id="sam3.segment-nodes",
                )
                _enable_pack_and_assert_loaded(
                    client=client,
                    headers=headers,
                    node_pack_id="sam3.segment-nodes",
                )
                _assert_pack_catalog_enabled(
                    client=client,
                    headers=headers,
                    node_pack_id="sam3.segment-nodes",
                    expected_node_type_ids=("custom.sam3.semantic-segment",),
                )

                workflow_service = LocalWorkflowJsonService(
                    dataset_storage=dataset_storage,
                    node_catalog_registry=client.app.state.node_catalog_registry,
                )
                workflow_service.save_template(
                    project_id=_PROJECT_ID,
                    template=_build_sam3_semantic_template(),
                )
                workflow_service.save_application(
                    project_id=_PROJECT_ID,
                    application=_build_sam3_semantic_application(),
                )

                image_object_key = _write_test_image(dataset_storage, object_key="projects/project-1/inputs/sam3-smoke.png")
                workflow_runtime_id = _create_and_start_runtime(
                    client=client,
                    headers=headers,
                    application_id="sam3-semantic-smoke-app",
                    display_name="SAM3 Semantic Smoke Runtime",
                )
                health_response = client.get(
                    f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                    headers=headers,
                )
                invoke_response = client.post(
                    f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                    headers=headers,
                    json={
                        "input_bindings": {
                            "request_image": {
                                "object_key": image_object_key,
                                "media_type": "image/png",
                            },
                            "request_prompts": _build_text_prompts_payload(),
                        },
                        "execution_metadata": {
                            "scenario": "sam3-workflow-app-runtime-smoke",
                            "trigger_source": "sync-api",
                        },
                    },
                )
                stop_response = client.post(
                    f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                    headers=headers,
                )
        finally:
            session_factory.engine.dispose()

    assert health_response.status_code == 200
    assert health_response.json()["observed_state"] == "running"
    assert invoke_response.status_code == 200
    assert stop_response.status_code == 200
    assert stop_response.json()["observed_state"] == "stopped"

    payload = invoke_response.json()
    assert payload["state"] == "succeeded"
    assert set(payload["outputs"]) == {"regions", "summary"}
    assert payload["outputs"]["regions"]["count"] == len(payload["outputs"]["regions"]["items"])

    summary_payload = payload["outputs"]["summary"]
    assert summary_payload["project_native"] is True
    assert summary_payload["inference_mode"] == "semantic-segment"
    assert summary_payload["prompt_group_count"] == 2
    assert summary_payload["positive_prompt_count"] == 2
    assert summary_payload["negative_prompt_count"] == 2


def _create_runtime_api_client(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[TestClient, object, object]:
    """创建加载仓库 custom_nodes 的 WorkflowAppRuntime API 测试客户端。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(_CUSTOM_NODES_ROOT)),
            local_buffer_broker=LocalBufferBrokerSettings(enabled=False),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return TestClient(application), session_factory, dataset_storage


def _create_and_start_runtime(
    *,
    client: TestClient,
    headers: dict[str, str],
    application_id: str,
    display_name: str,
) -> str:
    """创建并启动一个 WorkflowAppRuntime。"""

    create_response = client.post(
        "/api/v1/workflows/app-runtimes",
        headers=headers,
        json={
            "project_id": _PROJECT_ID,
            "application_id": application_id,
            "display_name": display_name,
            "request_timeout_seconds": 120,
        },
    )
    assert create_response.status_code == 201
    workflow_runtime_id = create_response.json()["workflow_runtime_id"]
    start_response = client.post(
        f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
        headers=headers,
    )
    assert start_response.status_code == 200
    return workflow_runtime_id


def _assert_pack_catalog_disabled(
    *,
    client: TestClient,
    headers: dict[str, str],
    node_pack_id: str,
) -> None:
    """断言节点包在当前 runtime 控制面中默认未进入目录。"""

    status_response = client.get(
        "/api/v1/workflows/node-pack-status",
        headers=headers,
    )
    assert status_response.status_code == 200
    status_item = _find_node_pack_status_item(status_response.json(), node_pack_id=node_pack_id)
    assert status_item["enabled"] is False

    catalog_response = client.get(
        "/api/v1/workflows/node-catalog",
        params={"node_pack_id": node_pack_id},
        headers=headers,
    )
    assert catalog_response.status_code == 200
    assert catalog_response.json()["node_definitions"] == []


def _enable_pack_and_assert_loaded(
    *,
    client: TestClient,
    headers: dict[str, str],
    node_pack_id: str,
) -> None:
    """启用指定节点包并断言 loader 状态为 loaded。"""

    response = client.post(
        f"/api/v1/workflows/node-packs/{node_pack_id}/enable",
        headers=headers,
    )
    assert response.status_code == 200
    status_item = _find_node_pack_status_item(response.json(), node_pack_id=node_pack_id)
    assert status_item["enabled"] is True
    assert status_item["state"] == "loaded"


def _assert_pack_catalog_enabled(
    *,
    client: TestClient,
    headers: dict[str, str],
    node_pack_id: str,
    expected_node_type_ids: tuple[str, ...],
) -> None:
    """断言启用后的节点包已经进入 node catalog。"""

    response = client.get(
        "/api/v1/workflows/node-catalog",
        params={"node_pack_id": node_pack_id},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    node_type_ids = {item["node_type_id"] for item in payload["node_definitions"]}
    for node_type_id in expected_node_type_ids:
        assert node_type_id in node_type_ids


def _find_node_pack_status_item(
    payload: dict[str, object],
    *,
    node_pack_id: str,
) -> dict[str, object]:
    """从节点包状态响应中读取指定 pack 的状态项。"""

    items = payload.get("items")
    if not isinstance(items, list):
        raise AssertionError("node pack status 响应缺少 items")
    for item in items:
        if isinstance(item, dict) and item.get("node_pack_id") == node_pack_id:
            return item
    raise AssertionError(f"未找到 node pack 状态项: {node_pack_id}")


def _build_yoloe_text_prompt_template() -> WorkflowGraphTemplate:
    """构造 YOLOE text-prompt 的最小 workflow 模板。"""

    return WorkflowGraphTemplate(
        template_id="yoloe-text-prompt-smoke-template",
        template_version="1.0.0",
        display_name="YOLOE Text Prompt Smoke Template",
        nodes=(
            WorkflowGraphNode(
                node_id="yoloe_text",
                node_type_id="custom.yoloe.text-prompt-detect",
                parameters={
                    "model_family": "v8",
                    "model_scale": "s",
                    "confidence_threshold": 0.05,
                    "iou_threshold": 0.5,
                    "max_detections": 8,
                    "device": "cpu",
                    "precision": "fp32",
                },
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="yoloe_text",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_prompts",
                display_name="Request Prompts",
                payload_type_id="text-prompts.v1",
                target_node_id="yoloe_text",
                target_port="prompts",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
                source_node_id="yoloe_text",
                source_port="detections",
            ),
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="yoloe_text",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="yoloe_text",
                source_port="summary",
            ),
        ),
    )


def _build_yoloe_text_prompt_application() -> FlowApplication:
    """构造 YOLOE text-prompt 的最小流程应用。"""

    return FlowApplication(
        application_id="yoloe-text-prompt-smoke-app",
        display_name="YOLOE Text Prompt Smoke App",
        template_ref=FlowTemplateReference(
            template_id="yoloe-text-prompt-smoke-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image",
                direction="input",
                template_port_id="request_image",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "image-ref.v1"},
            ),
            FlowApplicationBinding(
                binding_id="request_prompts",
                direction="input",
                template_port_id="request_prompts",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "text-prompts.v1"},
            ),
            FlowApplicationBinding(
                binding_id="detections",
                direction="output",
                template_port_id="detections",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "detections.v1"},
            ),
            FlowApplicationBinding(
                binding_id="regions",
                direction="output",
                template_port_id="regions",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "regions.v1"},
            ),
            FlowApplicationBinding(
                binding_id="summary",
                direction="output",
                template_port_id="summary",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
            ),
        ),
    )


def _build_sam3_semantic_template() -> WorkflowGraphTemplate:
    """构造 SAM3 semantic-segment 的最小 workflow 模板。"""

    return WorkflowGraphTemplate(
        template_id="sam3-semantic-smoke-template",
        template_version="1.0.0",
        display_name="SAM3 Semantic Smoke Template",
        nodes=(
            WorkflowGraphNode(
                node_id="sam3_semantic",
                node_type_id="custom.sam3.semantic-segment",
                parameters={
                    "model_scale": "l",
                    "device": "cpu",
                    "precision": "fp32",
                },
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="sam3_semantic",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_prompts",
                display_name="Request Prompts",
                payload_type_id="text-prompts.v1",
                target_node_id="sam3_semantic",
                target_port="prompts",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="sam3_semantic",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="sam3_semantic",
                source_port="summary",
            ),
        ),
    )


def _build_sam3_semantic_application() -> FlowApplication:
    """构造 SAM3 semantic-segment 的最小流程应用。"""

    return FlowApplication(
        application_id="sam3-semantic-smoke-app",
        display_name="SAM3 Semantic Smoke App",
        template_ref=FlowTemplateReference(
            template_id="sam3-semantic-smoke-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image",
                direction="input",
                template_port_id="request_image",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "image-ref.v1"},
            ),
            FlowApplicationBinding(
                binding_id="request_prompts",
                direction="input",
                template_port_id="request_prompts",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "text-prompts.v1"},
            ),
            FlowApplicationBinding(
                binding_id="regions",
                direction="output",
                template_port_id="regions",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "regions.v1"},
            ),
            FlowApplicationBinding(
                binding_id="summary",
                direction="output",
                template_port_id="summary",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
            ),
        ),
    )


def _build_text_prompts_payload() -> dict[str, object]:
    """构造同时包含 positive / negative 的 grouped text-prompts.v1 输入。"""

    return {
        "items": [
            {
                "prompt_id": "foreground",
                "display_name": "Foreground",
                "text": "foreground object",
            },
            {
                "prompt_id": "foreground",
                "display_name": "Foreground",
                "text": "background clutter",
                "negative": True,
            },
            {
                "prompt_id": "target",
                "display_name": "Target",
                "text": "industrial part",
            },
            {
                "prompt_id": "target",
                "display_name": "Target",
                "text": "empty background",
                "negative": True,
            },
        ]
    }


def _write_test_image(dataset_storage: object, *, object_key: str) -> str:
    """写入一张本地 smoke 图片并返回 object key。"""

    dataset_storage.write_bytes(object_key, _build_test_png_bytes())
    return object_key


def _build_test_png_bytes() -> bytes:
    """构造一张稍大于最小像素的本地测试图片。"""

    image = Image.new("RGB", (160, 112), color=(30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 80, 72), fill=(220, 70, 70))
    draw.ellipse((96, 28, 144, 76), fill=(70, 180, 90))
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@contextmanager
def _temporary_pack_default_enabled(
    desired_flags: dict[Path, bool],
) -> Iterator[None]:
    """临时改写指定 node pack manifest 的 enabledByDefault，并在退出时恢复。"""

    original_texts = {
        manifest_path: manifest_path.read_text(encoding="utf-8")
        for manifest_path in desired_flags
    }
    try:
        for manifest_path, enabled in desired_flags.items():
            payload = json.loads(original_texts[manifest_path])
            payload["enabledByDefault"] = enabled
            manifest_path.write_bytes(
                (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            )
        yield
    finally:
        for manifest_path, original_text in original_texts.items():
            manifest_path.write_bytes(original_text.encode("utf-8"))
