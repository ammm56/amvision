"""模型版本类别文件的公开边界及缺失类别的转换提交门禁。"""

from pathlib import Path

import pytest

from backend.service.application.models.registry.model_service import (
    PretrainedRegistrationRequest,
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
)
from backend.service.application.models.catalog.rfdetr import (
    SqlAlchemyRfdetrModelService,
)
from tests.api_test_support import build_test_headers, create_api_test_context


def test_versions_expose_their_own_label_files(tmp_path: Path) -> None:
    """同一模型的多代版本不能借用 Model 顶层最新 labels 文件。"""

    context = create_api_test_context(
        tmp_path, database_name="labels.db", enable_local_buffer_broker=False
    )
    service = SqlAlchemyYolo11ModelService(session_factory=context.session_factory)
    ids = [
        service.register_training_output(
            TrainingOutputRegistration(
                project_id="project-1",
                training_task_id=f"training-{index}",
                model_name="classifier",
                model_scale="s",
                task_type="classification",
                dataset_version_id=f"dataset-{index}",
                checkpoint_file_id=f"ckpt-{index}",
                checkpoint_file_uri=f"best-{index}.pt",
                labels_file_id=f"labels-{index}",
                labels_file_uri=f"labels-{index}.txt",
                metadata={
                    "input_size": {"width": 224, "height": 224},
                    "category_names": names,
                },
            )
        )
        for index, names in enumerate((["ok", "ng"], ["rework", "pass"]))
    ]
    try:
        with context.client:
            response = context.client.get(
                "/api/v1/models/deployment-sources?project_id=project-1&task_type=classification",
                headers=build_test_headers(scopes="models:read"),
            )
            assert response.status_code == 200
            model = response.json()[0]
            detail = context.client.get(
                f"/api/v1/models/deployment-sources/{model['model_id']}?project_id=project-1",
                headers=build_test_headers(scopes="models:read"),
            ).json()
            for versions in (model["available_versions"], detail["versions"]):
                by_id = {item["model_version_id"]: item for item in versions}
                for index, version_id in enumerate(ids):
                    assert by_id[version_id]["labels_file_id"] == f"labels-{index}"
                    assert (
                        by_id[version_id]["labels_storage_uri"] == f"labels-{index}.txt"
                    )
    finally:
        context.session_factory.engine.dispose()


_STACKS = [
    ("yolox", SqlAlchemyModelService, ("detection",)),
    (
        "yolov8",
        SqlAlchemyYoloV8ModelService,
        ("detection", "classification", "segmentation", "pose", "obb"),
    ),
    (
        "yolo11",
        SqlAlchemyYolo11ModelService,
        ("detection", "classification", "segmentation", "pose", "obb"),
    ),
    (
        "yolo26",
        SqlAlchemyYolo26ModelService,
        ("detection", "classification", "segmentation", "pose", "obb"),
    ),
    ("rfdetr", SqlAlchemyRfdetrModelService, ("detection", "segmentation")),
]


@pytest.mark.parametrize(
    ("model_type", "service_cls", "task_type"),
    [(name, cls, task) for name, cls, tasks in _STACKS for task in tasks],
)
def test_checkpoint_only_reference_is_rejected_before_conversion_task_creation(
    tmp_path: Path, model_type: str, service_cls: type, task_type: str
) -> None:
    """18 个受支持组合都在创建 Task/Outbox 前拒绝没有类别映射的引用。"""

    context = create_api_test_context(
        tmp_path, database_name="missing-labels.db", enable_local_buffer_broker=False
    )
    context.dataset_storage.write_bytes("pretrained.pt", b"checkpoint")
    service = service_cls(session_factory=context.session_factory)
    version_id = service.register_pretrained(
        PretrainedRegistrationRequest(
            model_name=model_type,
            model_scale="nano",
            task_type=task_type,
            storage_uri="pretrained.pt",
        )
    )
    try:
        with context.client:
            response = context.client.post(
                f"/api/v1/models/{task_type}/conversion-tasks"
                + ("/onnx" if task_type == "detection" else ""),
                headers=build_test_headers(scopes="tasks:write models:read"),
                json={
                    "project_id": "project-1",
                    "model_type": model_type,
                    "source_model_version_id": version_id,
                    "target_formats": ["onnx"],
                },
            )
            assert response.status_code == 400, response.text
            assert response.json()["error"]["details"]["model_version_id"] == version_id
            assert "训练初始化" in response.json()["error"]["message"]
            tasks = context.client.get(
                f"/api/v1/models/{task_type}/conversion-tasks?project_id=project-1",
                headers=build_test_headers(scopes="tasks:read"),
            )
            assert tasks.status_code == 200
            assert tasks.json() == []
            assert (
                service.get_model_version(version_id).source_kind
                == "pretrained-reference"
            )
    finally:
        context.session_factory.engine.dispose()
