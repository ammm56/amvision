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
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowAppVersion,
    WorkflowPreviewRun,
    WorkflowRun,
    WorkflowRuntimeRevision,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
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
        scopes=(
            "tasks:read",
            "tasks:write",
            "models:read",
            "models:write",
            "workflows:read",
            "workflows:write",
        ),
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


def test_workflow_runtime_and_trigger_ids_hide_cross_project_resources(
    restricted_project_context,
) -> None:
    """Workflow 公开资源 id 在 Repository 边界按可见 Project 返回 404。"""

    context = restricted_project_context
    resource_ids = _seed_hidden_workflow_resources(context["session_factory"])

    unit_of_work = SqlAlchemyUnitOfWork(
        context["session_factory"].create_session()
    )
    try:
        # Worker 和恢复链路保留不带主体信息的原始查询。
        assert (
            unit_of_work.workflow_runtime.get_preview_run(
                resource_ids["preview_run_id"]
            )
            is not None
        )
        assert (
            unit_of_work.workflow_runtime.get_workflow_app_runtime(
                resource_ids["workflow_runtime_id"]
            )
            is not None
        )
        assert (
            unit_of_work.workflow_runtime.get_workflow_run(
                resource_ids["workflow_run_id"]
            )
            is not None
        )
        assert (
            unit_of_work.workflow_trigger_sources.get_trigger_source(
                resource_ids["trigger_source_id"]
            )
            is not None
        )
        assert (
            unit_of_work.workflow_runtime.get_visible_preview_run(
                resource_ids["preview_run_id"],
                visible_project_ids=("project-visible",),
            )
            is None
        )
        assert (
            unit_of_work.workflow_runtime.get_visible_workflow_app_runtime(
                resource_ids["workflow_runtime_id"],
                visible_project_ids=("project-visible",),
            )
            is None
        )
        assert (
            unit_of_work.workflow_runtime.get_visible_workflow_runtime_revision(
                resource_ids["workflow_runtime_id"],
                resource_ids["workflow_runtime_revision_id"],
                visible_project_ids=("project-visible",),
            )
            is None
        )
        assert (
            unit_of_work.workflow_runtime.get_visible_workflow_run(
                resource_ids["workflow_run_id"],
                visible_project_ids=("project-visible",),
            )
            is None
        )
        assert (
            unit_of_work.workflow_trigger_sources.get_visible_trigger_source(
                resource_ids["trigger_source_id"],
                visible_project_ids=("project-visible",),
            )
            is None
        )
    finally:
        unit_of_work.close()

    runtime_id = resource_ids["workflow_runtime_id"]
    revision_id = resource_ids["workflow_runtime_revision_id"]
    preview_run_id = resource_ids["preview_run_id"]
    workflow_run_id = resource_ids["workflow_run_id"]
    trigger_source_id = resource_ids["trigger_source_id"]
    headers = context["headers"]
    with context["client"] as client:
        requests = (
            client.get(
                f"/api/v1/workflows/preview-runs/{preview_run_id}",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/preview-runs/{preview_run_id}/events",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/preview-runs/{preview_run_id}/artifacts/content",
                params={"object_key": "runtime/hidden.txt"},
                headers=headers,
            ),
            client.delete(
                f"/api/v1/workflows/preview-runs/{preview_run_id}",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/events",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/health",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/instances",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions/{revision_id}",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/restart",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": resource_ids[
                        "workflow_app_version_id"
                    ],
                    "expected_generation": 1,
                },
            ),
            client.delete(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/runs",
                headers=headers,
                json={},
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/invoke",
                headers=headers,
                json={},
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/runs/upload",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/invoke/upload",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/runs/{workflow_run_id}",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/runs/{workflow_run_id}/events",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/runs/{workflow_run_id}/cancel",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/trigger-sources/{trigger_source_id}",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/trigger-sources/{trigger_source_id}/enable",
                headers=headers,
            ),
            client.post(
                f"/api/v1/workflows/trigger-sources/{trigger_source_id}/disable",
                headers=headers,
            ),
            client.get(
                f"/api/v1/workflows/trigger-sources/{trigger_source_id}/health",
                headers=headers,
            ),
            client.delete(
                f"/api/v1/workflows/trigger-sources/{trigger_source_id}",
                headers=headers,
            ),
        )
        assert {response.status_code for response in requests} == {404}

        nested_runtime_response = client.post(
            "/api/v1/workflows/trigger-sources",
            headers=headers,
            json={
                "trigger_source_id": "visible-trigger-hidden-runtime",
                "project_id": "project-visible",
                "display_name": "hidden runtime reference",
                "trigger_kind": "http-api",
                "workflow_runtime_id": runtime_id,
            },
        )
        assert nested_runtime_response.status_code == 404

        for url in (
            "/api/v1/workflows/preview-runs",
            "/api/v1/workflows/app-runtimes",
            "/api/v1/workflows/trigger-sources",
        ):
            assert (
                client.get(
                    url,
                    params={"project_id": "project-hidden"},
                    headers=headers,
                ).status_code
                == 403
            )


def test_validation_session_ids_hide_cross_project_before_prediction(
    restricted_project_context,
) -> None:
    """五类 validation session 的详情和 predict 都按不可探测语义返回 404。"""

    context = restricted_project_context
    session_ids = _seed_hidden_validation_sessions(context["dataset_storage"])
    with context["client"] as client:
        for task_type, session_id in session_ids.items():
            base_url = f"/api/v1/models/{task_type}/validation-sessions/{session_id}"
            detail_response = client.get(base_url, headers=context["headers"])
            predict_response = client.post(
                f"{base_url}/predict",
                headers=context["headers"],
                json={"input_uri": "missing-input.jpg"},
            )
            assert detail_response.status_code == 404
            assert predict_response.status_code == 404

            # 越权 predict 不得进入输入解析、runtime 推理或结果写入阶段。
            prediction_dir = context["dataset_storage"].resolve(
                f"runtime/validation-sessions-{task_type}/{session_id}/predictions"
            )
            if task_type == "detection":
                prediction_dir = context["dataset_storage"].resolve(
                    f"runtime/validation/{session_id}/pred"
                )
            assert not prediction_dir.exists()


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


def _seed_hidden_workflow_resources(session_factory) -> dict[str, str]:
    """写入 Project B 的 Workflow/Trigger 资源供负向边界测试使用。"""

    resource_ids = {
        "workflow_app_version_id": "hidden-workflow-app-version",
        "workflow_runtime_id": "hidden-workflow-runtime",
        "workflow_runtime_revision_id": "hidden-workflow-runtime-revision",
        "preview_run_id": "hidden-workflow-preview-run",
        "workflow_run_id": "hidden-workflow-run",
        "trigger_source_id": "hidden-workflow-trigger-source",
    }
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.add_workflow_app_version(
            WorkflowAppVersion(
                workflow_app_version_id=resource_ids["workflow_app_version_id"],
                project_id="project-hidden",
                application_id="hidden-workflow-app",
                version_number=1,
                display_version="1.0.0",
                release_notes="",
                application_snapshot_object_key="workflows/hidden/application.json",
                template_snapshot_object_key="workflows/hidden/template.json",
                contract_snapshot_object_key="workflows/hidden/contract.json",
                dependency_manifest_object_key="workflows/hidden/dependencies.json",
                content_fingerprint="hidden-content-fingerprint",
                contract_fingerprint="hidden-contract-fingerprint",
                state="published",
                created_at="2026-08-22T00:00:00Z",
                completed_at="2026-08-22T00:00:00Z",
            )
        )
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id=resource_ids["workflow_runtime_id"],
                project_id="project-hidden",
                application_id="hidden-workflow-app",
                display_name="Hidden Runtime",
                application_snapshot_object_key="workflows/hidden/application.json",
                template_snapshot_object_key="workflows/hidden/template.json",
                active_revision_id=resource_ids["workflow_runtime_revision_id"],
                desired_revision_id=resource_ids["workflow_runtime_revision_id"],
                revision_generation=1,
                desired_state="stopped",
                observed_state="stopped",
                created_at="2026-08-22T00:00:00Z",
                updated_at="2026-08-22T00:00:00Z",
            )
        )
        unit_of_work.workflow_runtime.add_workflow_runtime_revision(
            WorkflowRuntimeRevision(
                workflow_runtime_revision_id=resource_ids[
                    "workflow_runtime_revision_id"
                ],
                workflow_runtime_id=resource_ids["workflow_runtime_id"],
                generation=1,
                workflow_app_version_id=resource_ids["workflow_app_version_id"],
                execution_policy_snapshot_object_key=None,
                expected_snapshot_fingerprint="hidden-content-fingerprint",
                state="active",
                created_at="2026-08-22T00:00:00Z",
                activated_at="2026-08-22T00:00:00Z",
            )
        )
        unit_of_work.workflow_runtime.save_preview_run(
            WorkflowPreviewRun(
                preview_run_id=resource_ids["preview_run_id"],
                project_id="project-hidden",
                application_id="hidden-workflow-app",
                source_kind="inline-snapshot",
                application_snapshot_object_key="workflows/hidden/preview-app.json",
                template_snapshot_object_key="workflows/hidden/preview-template.json",
                state="succeeded",
                created_at="2026-08-22T00:00:00Z",
                finished_at="2026-08-22T00:00:01Z",
            )
        )
        unit_of_work.workflow_runtime.save_workflow_run(
            WorkflowRun(
                workflow_run_id=resource_ids["workflow_run_id"],
                workflow_runtime_id=resource_ids["workflow_runtime_id"],
                project_id="project-hidden",
                application_id="hidden-workflow-app",
                workflow_runtime_revision_id=resource_ids[
                    "workflow_runtime_revision_id"
                ],
                workflow_app_version_id=resource_ids["workflow_app_version_id"],
                runtime_generation=1,
                snapshot_fingerprint="hidden-content-fingerprint",
                state="succeeded",
                created_at="2026-08-22T00:00:00Z",
                finished_at="2026-08-22T00:00:01Z",
            )
        )
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id=resource_ids["trigger_source_id"],
                project_id="project-hidden",
                display_name="Hidden Trigger",
                trigger_kind="http-api",
                workflow_runtime_id=resource_ids["workflow_runtime_id"],
                enabled=False,
                created_at="2026-08-22T00:00:00Z",
                updated_at="2026-08-22T00:00:00Z",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
    return resource_ids


def _seed_hidden_validation_sessions(dataset_storage) -> dict[str, str]:
    """写入五类 Project B validation session，不创建任何预测产物。"""

    session_ids = {
        "detection": "hidden-detection-session",
        "classification": "hidden-classification-session",
        "segmentation": "hidden-segmentation-session",
        "pose": "hidden-pose-session",
        "obb": "hidden-obb-session",
    }
    storage_dirs = {
        "detection": "validation-sessions",
        "classification": "validation-sessions-classification",
        "segmentation": "validation-sessions-segmentation",
        "pose": "validation-sessions-pose",
        "obb": "validation-sessions-obb",
    }
    for task_type, session_id in session_ids.items():
        payload: dict[str, object] = {
            "session_id": session_id,
            "project_id": "project-hidden",
            "model_type": "yolo11",
            "model_id": f"hidden-{task_type}-model",
            "model_version_id": f"hidden-{task_type}-model-version",
            "model_name": f"hidden-{task_type}",
            "model_scale": "s",
            "source_kind": "training-output",
            "status": "ready",
            "model_build_id": None,
            "runtime_profile_id": None,
            "runtime_backend": "pytorch",
            "device_name": "cpu",
            "runtime_precision": "fp32",
            "score_threshold": 0.3,
            "mask_threshold": 0.5,
            "keypoint_confidence_threshold": 0.3,
            "top_k": 5,
            "save_result_image": True,
            "input_size": {"width": 640, "height": 640},
            "labels": ["part"],
            "runtime_artifact_file_id": f"hidden-{task_type}-artifact",
            "runtime_artifact_storage_uri": f"models/hidden/{task_type}/model.pt",
            "runtime_artifact_file_type": "pytorch-checkpoint",
            "checkpoint_file_id": f"hidden-{task_type}-checkpoint",
            "checkpoint_storage_uri": f"models/hidden/{task_type}/model.pt",
            "labels_storage_uri": None,
            "extra_options": {},
            "created_at": "2026-08-22T00:00:00Z",
            "updated_at": "2026-08-22T00:00:00Z",
            "created_by": "hidden-user",
            "last_prediction": None,
        }
        dataset_storage.write_json(
            f"runtime/{storage_dirs[task_type]}/{session_id}/session.json",
            payload,
        )
    return session_ids
