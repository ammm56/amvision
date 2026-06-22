"""classification evaluation 路由服务装配。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.classification_evaluation_tasks.responses import (
    ClassificationEvaluationDetailResponse,
    ClassificationEvaluationSubmissionResponse,
    ClassificationEvaluationSummaryResponse,
    build_classification_evaluation_detail_response,
    build_classification_evaluation_summary_response,
)
from backend.service.api.rest.v1.routes.classification_evaluation_tasks.schemas import (
    ClassificationEvaluationCreateBody,
)
from backend.service.api.rest.v1.routes.task_evaluation.services import (
    delete_finished_evaluation_task,
    get_evaluation_task_record,
    list_evaluation_task_records,
    require_evaluation_project_access,
)
from backend.service.application.models.evaluation.yolo_primary_classification_evaluation_task_service import (
    CLASSIFICATION_EVALUATION_TASK_KIND,
    SqlAlchemyYoloPrimaryClassificationEvaluationTaskService,
    YoloPrimaryClassificationEvaluationTaskRequest,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def create_classification_evaluation_task_response(
    *,
    body: ClassificationEvaluationCreateBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> ClassificationEvaluationSubmissionResponse:
    """创建 classification evaluation 任务并返回提交响应。"""

    require_evaluation_project_access(principal=principal, project_id=body.project_id)
    service = SqlAlchemyYoloPrimaryClassificationEvaluationTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_evaluation_task(
        YoloPrimaryClassificationEvaluationTaskRequest(
            project_id=body.project_id,
            model_version_id=body.model_version_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            top_k=body.top_k,
            save_result_package=body.save_result_package,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return ClassificationEvaluationSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        dataset_export_id=submission.dataset_export_id,
        dataset_version_id=submission.dataset_version_id,
        model_version_id=submission.model_version_id,
    )


def list_classification_evaluation_task_responses(
    *,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    project_id: str,
    state: str | None,
    limit: int,
) -> list[ClassificationEvaluationSummaryResponse]:
    """列出 classification evaluation 任务响应。"""

    require_evaluation_project_access(principal=principal, project_id=project_id)
    tasks = list_evaluation_task_records(
        session_factory=session_factory,
        project_id=project_id,
        task_kind=CLASSIFICATION_EVALUATION_TASK_KIND,
        state=state,
        limit=limit,
    )
    return [build_classification_evaluation_summary_response(task) for task in tasks]


def get_classification_evaluation_task_response(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> ClassificationEvaluationDetailResponse:
    """读取 classification evaluation 任务详情响应。"""

    task = get_evaluation_task_record(
        session_factory=session_factory,
        task_id=task_id,
        expected_task_kind=CLASSIFICATION_EVALUATION_TASK_KIND,
    )
    return build_classification_evaluation_detail_response(task)


def delete_classification_evaluation_task_response(
    *,
    session_factory: SessionFactory,
    task_id: str,
):
    """删除已完成的 classification evaluation 任务。"""

    return delete_finished_evaluation_task(
        session_factory=session_factory,
        task_id=task_id,
        expected_task_kind=CLASSIFICATION_EVALUATION_TASK_KIND,
    )
