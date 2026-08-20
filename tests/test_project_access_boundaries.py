"""Project 资源访问边界负向测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.service.api.app import create_app
from backend.service.api.rest.v1.routes.task_training.catalog import (
    TASK_TYPE_TO_TASK_KIND,
)
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.local_buffers.broker_settings import (
    LocalBufferBrokerSettings,
)
from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration,
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetResolveRequest,
    SqlAlchemyRuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.settings import BackendServiceAuthConfig, BackendServiceSettings
from tests.api_test_support import (
    build_bearer_headers,
    create_test_runtime,
    issue_test_user_token,
)


@pytest.fixture
def restricted_project_context(tmp_path: Path):
    """创建只能访问 project-visible 的 API 测试上下文。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="project-access-boundaries.db",
    )
    token = issue_test_user_token(
        session_factory,
        username="project-boundary-viewer",
        scopes=("tasks:read", "tasks:write", "models:read", "models:write"),
        project_ids=("project-visible",),
    )
    application = create_app(
        settings=BackendServiceSettings(
            auth=BackendServiceAuthConfig(websocket_query_token_enabled=True),
            local_buffer_broker=LocalBufferBrokerSettings(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    context = {
        "client": TestClient(application),
        "session_factory": session_factory,
        "dataset_storage": dataset_storage,
        "headers": build_bearer_headers(token),
        "token": token,
    }
    try:
        yield context
    finally:
        session_factory.engine.dispose()


def test_non_detection_training_routes_hide_cross_project_task_before_checks(
    restricted_project_context,
) -> None:
    """详情、输出、控制、恢复和删除都必须先执行 task 可见性查询。"""

    context = restricted_project_context
    task_service = SqlAlchemyTaskService(context["session_factory"])
    route_by_task_type = {
        "classification": "classification",
        "segmentation": "segmentation",
        "pose": "pose",
        "obb": "obb",
    }
    task_ids: dict[str, str] = {}
    for task_type in route_by_task_type:
        task = task_service.create_task(
            CreateTaskRequest(
                task_id=f"cross-project-{task_type}",
                project_id="project-hidden",
                task_kind=TASK_TYPE_TO_TASK_KIND[task_type],
                display_name=f"hidden {task_type}",
                state="queued",
            )
        )
        task_ids[task_type] = task.task_id

    with context["client"] as client:
        for task_type, route_segment in route_by_task_type.items():
            task_id = task_ids[task_type]
            base_path = f"/api/v1/models/{route_segment}/training-tasks/{task_id}"
            responses = (
                client.get(base_path, headers=context["headers"]),
                client.get(f"{base_path}/output-files", headers=context["headers"]),
                client.get(
                    f"{base_path}/output-files/best-checkpoint",
                    headers=context["headers"],
                ),
                client.post(f"{base_path}/terminate", headers=context["headers"]),
                client.post(f"{base_path}/resume", headers=context["headers"]),
                client.delete(base_path, headers=context["headers"]),
            )
            assert [response.status_code for response in responses] == [
                404,
                404,
                404,
                404,
                404,
                404,
            ]

            explicit_project_response = client.get(
                f"/api/v1/models/{route_segment}/training-tasks",
                params={"project_id": "project-hidden"},
                headers=context["headers"],
            )
            assert explicit_project_response.status_code == 403


def test_generic_task_rest_and_websocket_hide_cross_project_task(
    restricted_project_context,
) -> None:
    """通用 Task REST 与两类 task WebSocket 使用同一不可探测语义。"""

    context = restricted_project_context
    task = SqlAlchemyTaskService(context["session_factory"]).create_task(
        CreateTaskRequest(
            task_id="cross-project-generic-task",
            project_id="project-hidden",
            task_kind="dataset-import",
            state="queued",
        )
    )

    with context["client"] as client:
        assert (
            client.get(
                f"/api/v1/tasks/{task.task_id}", headers=context["headers"]
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/tasks/{task.task_id}/events",
                headers=context["headers"],
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/tasks/{task.task_id}/cancel",
                headers=context["headers"],
            ).status_code
            == 404
        )
        with pytest.raises(WebSocketDisconnect) as task_socket_error:
            with client.websocket_connect(
                f"/ws/v1/tasks/events?task_id={task.task_id}"
                f"&access_token={context['token']}"
            ):
                pass
        assert task_socket_error.value.code == 4404

        with pytest.raises(WebSocketDisconnect) as telemetry_socket_error:
            with client.websocket_connect(
                f"/ws/v1/training/telemetry?task_id={task.task_id}"
                f"&access_token={context['token']}"
            ):
                pass
        assert telemetry_socket_error.value.code == 4404


def test_model_version_build_and_file_are_filtered_by_project_at_repository_boundary(
    restricted_project_context,
) -> None:
    """ModelVersion、ModelBuild 和 ModelFile 不能通过已知 id 跨 Project 解析。"""

    context = restricted_project_context
    service = SqlAlchemyModelService(context["session_factory"])
    model_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-hidden",
            training_task_id="training-hidden",
            model_name="hidden-yolox",
            model_scale="s",
            dataset_version_id="dataset-version-hidden",
            checkpoint_file_id="hidden-checkpoint-file",
            checkpoint_file_uri="models/hidden/checkpoint.pth",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )
    model_build_id = service.register_build(
        ModelBuildRegistration(
            project_id="project-hidden",
            source_model_version_id=model_version_id,
            build_format="onnx",
            runtime_backend="onnxruntime",
            runtime_precision="fp32",
            build_file_id="hidden-build-file",
            build_file_uri="models/hidden/model.onnx",
            metadata={"input_tensor": {"shape": [1, 3, 640, 640]}},
        )
    )
    model_version = service.get_model_version(model_version_id)
    assert model_version is not None

    assert (
        service.get_visible_model_version(
            model_version_id,
            visible_project_ids=("project-visible",),
        )
        is None
    )
    assert (
        service.get_visible_model_build(
            model_build_id,
            visible_project_ids=("project-visible",),
        )
        is None
    )
    assert (
        service.get_visible_model_file(
            "hidden-checkpoint-file",
            visible_project_ids=("project-visible",),
        )
        is None
    )
    assert (
        service.list_visible_model_files(
            visible_project_ids=("project-visible",),
            model_version_id=model_version_id,
        )
        == ()
    )

    resolver = SqlAlchemyRuntimeTargetResolver(
        session_factory=context["session_factory"],
        dataset_storage=context["dataset_storage"],
    )
    with pytest.raises(ResourceNotFoundError, match="ModelVersion"):
        resolver.resolve_target(
            RuntimeTargetResolveRequest(
                project_id="project-visible",
                model_version_id=model_version_id,
            )
        )
    with pytest.raises(ResourceNotFoundError, match="ModelBuild"):
        resolver.resolve_target(
            RuntimeTargetResolveRequest(
                project_id="project-visible",
                model_build_id=model_build_id,
            )
        )

    with context["client"] as client:
        detail_response = client.get(
            f"/api/v1/models/deployment-sources/{model_version.model_id}",
            params={"project_id": "project-visible"},
            headers=context["headers"],
        )
        explicit_project_response = client.get(
            "/api/v1/models/deployment-sources",
            params={"project_id": "project-hidden"},
            headers=context["headers"],
        )
    assert detail_response.status_code == 404
    assert explicit_project_response.status_code == 403
