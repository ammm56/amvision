"""YOLOX conversion task API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.files.yolox_file_types import (
    YOLOX_ONNX_FILE,
    YOLOX_ONNX_OPTIMIZED_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.conversion.yolox_conversion_queue_worker import YoloXConversionQueueWorker
from backend.workers.conversion.yolox_conversion_runner import (
    YoloXConversionOutput,
    YoloXConversionRunRequest,
    YoloXConversionRunResult,
)
from tests.api_test_support import build_test_headers
from tests.yolox_test_support import (
    create_yolox_api_test_context,
    seed_yolox_model_version,
)

import pytest


@pytest.mark.parametrize(
    (
        "create_path",
        "expected_target_formats",
        "expected_produced_formats",
        "expected_phase",
        "expected_conversion_options",
    ),
    [
        (
            "/api/v1/models/yolox/conversion-tasks/onnx",
            ["onnx"],
            ["onnx"],
            "phase-1-onnx",
            {},
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/onnx-optimized",
            ["onnx-optimized"],
            ["onnx", "onnx-optimized"],
            "phase-1-onnx",
            {},
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/openvino-ir-fp32",
            ["openvino-ir"],
            ["onnx", "onnx-optimized", "openvino-ir"],
            "phase-2-openvino-ir",
            {"openvino_ir_precision": "fp32"},
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/openvino-ir-fp16",
            ["openvino-ir"],
            ["onnx", "onnx-optimized", "openvino-ir"],
            "phase-2-openvino-ir",
            {"openvino_ir_precision": "fp16"},
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/tensorrt-engine-fp32",
            ["tensorrt-engine"],
            ["onnx", "onnx-optimized", "tensorrt-engine"],
            "phase-2-tensorrt-engine",
            {"tensorrt_engine_precision": "fp32"},
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/tensorrt-engine-fp16",
            ["tensorrt-engine"],
            ["onnx", "onnx-optimized", "tensorrt-engine"],
            "phase-2-tensorrt-engine",
            {"tensorrt_engine_precision": "fp16"},
        ),
    ],
)
def test_create_yolox_conversion_task_and_read_result_after_worker(
    tmp_path: Path,
    create_path: str,
    expected_target_formats: list[str],
    expected_produced_formats: list[str],
    expected_phase: str,
    expected_conversion_options: dict[str, object],
) -> None:
    """验证 conversion task 可以创建、执行，并返回 detail、list 和 result。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    source_model_version_id = _seed_placeholder_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    worker = YoloXConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_FakeYoloXConversionRunner(dataset_storage=dataset_storage),
        worker_id="test-yolox-conversion-worker",
    )

    try:
        with client:
            create_response = client.post(
                create_path,
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "source_model_version_id": source_model_version_id,
                    "runtime_profile_id": None,
                    "extra_options": {},
                    "display_name": "conversion api test",
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]
            assert submission["target_formats"] == expected_target_formats

            pending_result_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}/result",
                headers=_build_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            pending_detail_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}",
                headers=_build_headers(),
            )
            assert pending_detail_response.status_code == 200
            assert pending_detail_response.json()["state"] == "queued"

            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["source_model_version_id"] == source_model_version_id
            assert detail_payload["requested_target_formats"] == expected_target_formats
            assert detail_payload["produced_formats"] == expected_produced_formats
            assert len(detail_payload["builds"]) == len(expected_produced_formats)
            assert detail_payload["report_summary"]["validation_summary"]["allclose"] is True
            assert detail_payload["report_summary"]["phase"] == expected_phase
            assert detail_payload["report_summary"]["conversion_options"] == expected_conversion_options
            if "openvino_ir_precision" in expected_conversion_options:
                openvino_builds = [
                    item for item in detail_payload["builds"] if item["build_format"] == "openvino-ir"
                ]
                assert len(openvino_builds) == 1
                assert openvino_builds[0]["metadata"]["build_precision"] == expected_conversion_options[
                    "openvino_ir_precision"
                ]
                assert openvino_builds[0]["metadata"]["compress_to_fp16"] is (
                    expected_conversion_options["openvino_ir_precision"] == "fp16"
                )
            if "tensorrt_engine_precision" in expected_conversion_options:
                tensorrt_builds = [
                    item for item in detail_payload["builds"] if item["build_format"] == "tensorrt-engine"
                ]
                assert len(tensorrt_builds) == 1
                assert tensorrt_builds[0]["metadata"]["build_precision"] == expected_conversion_options[
                    "tensorrt_engine_precision"
                ]

            result_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}/result",
                headers=_build_headers(),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["file_status"] == "ready"
            assert result_payload["payload"]["phase"] == expected_phase
            assert result_payload["payload"]["planned_target_formats"] == expected_target_formats
            assert result_payload["payload"]["validation_summary"]["allclose"] is True
            assert result_payload["payload"]["conversion_options"] == expected_conversion_options

            list_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks?project_id=project-1&source_model_version_id={source_model_version_id}",
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert len(list_payload) == 1
            assert list_payload[0]["produced_formats"] == expected_produced_formats

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "yolox conversion started" for event in task_detail.events)
        assert any(event.message == "yolox conversion succeeded" for event in task_detail.events)
        assert dataset_storage.resolve(detail_payload["report_object_key"]).is_file() is True
        for build_item in detail_payload["builds"]:
            build_path = dataset_storage.resolve(build_item["build_file_uri"])
            assert build_path.is_file() is True
            if build_item["build_format"] == "openvino-ir":
                assert build_path.suffix == ".xml"
                assert build_path.with_suffix(".bin").is_file() is True
            if build_item["build_format"] == "tensorrt-engine":
                assert build_path.suffix == ".engine"
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的 conversion API 测试客户端。"""

    context = create_yolox_api_test_context(
        tmp_path,
        database_name="amvision-conversion-api.db",
    )
    return context.client, context.session_factory, context.dataset_storage, context.queue_backend


def _seed_placeholder_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个仅用于逻辑测试的最小训练输出 ModelVersion。"""

    return seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="conversion-api-source-1",
        training_task_id="training-conversion-api-source-1",
        model_name="yolox-nano-conversion-api",
        dataset_version_id="dataset-version-conversion-api-source-1",
        checkpoint_file_id="checkpoint-file-conversion-api-1",
        labels_file_id="labels-file-conversion-api-1",
    )


def _build_headers() -> dict[str, str]:
    """构建 conversion API 所需请求头。"""

    return build_test_headers(scopes="models:read,tasks:read,tasks:write")


class _FakeYoloXConversionRunner:
    """为 conversion API 与 worker 测试提供轻量输出的 stub runner。

    属性：
    - dataset_storage：测试使用的本地文件存储。
    """

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化轻量 conversion runner。

        参数：
        - dataset_storage：测试使用的本地文件存储。
        """

        self.dataset_storage = dataset_storage

    def run_conversion(self, request: YoloXConversionRunRequest) -> YoloXConversionRunResult:
        """按目标格式写入最小占位产物并返回转换结果。

        参数：
        - request：转换执行请求。

        返回：
        - YoloXConversionRunResult：轻量转换结果。
        """

        base_name = _build_test_output_base_name(request)
        outputs: list[YoloXConversionOutput] = []
        validation_summary = {
            "allclose": True,
            "max_abs_diff": 0.0,
            "mean_abs_diff": 0.0,
            "output_count": 1,
        }

        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        openvino_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.openvino.xml"
        tensorrt_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.tensorrt.engine"

        self._write_file(onnx_object_key, b"fake-onnx")
        outputs.append(
            YoloXConversionOutput(
                target_format="onnx",
                object_uri=onnx_object_key,
                file_type=YOLOX_ONNX_FILE,
                metadata={
                    "stage": "export-onnx",
                    "object_uri": onnx_object_key,
                },
            )
        )

        if any(item in request.target_formats for item in ("onnx-optimized", "openvino-ir", "tensorrt-engine")):
            self._write_file(optimized_object_key, b"fake-optimized-onnx")
            outputs.append(
                YoloXConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                    metadata={
                        "stage": "optimize-onnx",
                        "object_uri": optimized_object_key,
                        "source_object_uri": onnx_object_key,
                        "validation_summary": validation_summary,
                    },
                )
            )

        if "openvino-ir" in request.target_formats:
            build_precision = str(request.metadata.get("openvino_ir_precision") or "fp32")
            self._write_file(openvino_object_key, b"<xml />")
            self._write_file(openvino_object_key.replace(".xml", ".bin"), b"fake-openvino-bin")
            outputs.append(
                YoloXConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=YOLOX_OPENVINO_IR_FILE,
                    metadata={
                        "stage": "build-openvino-ir",
                        "object_uri": openvino_object_key,
                        "source_object_uri": optimized_object_key,
                        "weights_object_uri": openvino_object_key.replace(".xml", ".bin"),
                        "build_precision": build_precision,
                        "compress_to_fp16": build_precision == "fp16",
                        "execution_mode": "stub-openvino-build",
                    },
                )
            )

        if "tensorrt-engine" in request.target_formats:
            build_precision = str(request.metadata.get("tensorrt_engine_precision") or "fp32")
            self._write_file(tensorrt_object_key, b"fake-tensorrt-engine")
            outputs.append(
                YoloXConversionOutput(
                    target_format="tensorrt-engine",
                    object_uri=tensorrt_object_key,
                    file_type=YOLOX_TENSORRT_ENGINE_FILE,
                    metadata={
                        "stage": "build-tensorrt-engine",
                        "object_uri": tensorrt_object_key,
                        "source_object_uri": optimized_object_key,
                        "build_precision": build_precision,
                        "execution_mode": "stub-tensorrt-build",
                        "engine_file_bytes": self.dataset_storage.resolve(tensorrt_object_key).stat().st_size,
                    },
                )
            )

        return YoloXConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=tuple(outputs),
            metadata={
                "phase": _resolve_expected_phase(request.target_formats),
                "executed_step_kinds": [step.kind for step in request.plan_steps],
                "validation_summary": validation_summary,
                "conversion_options": _build_expected_conversion_options(request),
            },
        )

    def _write_file(self, object_key: str, content: bytes) -> None:
        """写入测试所需的最小占位文件。

        参数：
        - object_key：目标文件 object key。
        - content：文件内容。
        """

        resolved_path = self.dataset_storage.resolve(object_key)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_bytes(content)


def _build_test_output_base_name(request: YoloXConversionRunRequest) -> str:
    """根据来源模型信息构建测试输出前缀。"""

    model_name = request.source_runtime_target.model_name.replace(" ", "-").lower() or "yolox"
    model_scale = request.source_runtime_target.model_scale.strip().lower() or "unknown"
    return f"{model_name}-{model_scale}"


def _resolve_expected_phase(target_formats: tuple[str, ...]) -> str:
    """根据目标格式集合返回测试期望阶段。"""

    if "tensorrt-engine" in target_formats:
        return "phase-2-tensorrt-engine"
    if "openvino-ir" in target_formats:
        return "phase-2-openvino-ir"
    return "phase-1-onnx"


def _build_expected_conversion_options(request: YoloXConversionRunRequest) -> dict[str, object]:
    """根据请求元数据构建测试用转换策略摘要。"""

    options: dict[str, object] = {}
    if "openvino-ir" in request.target_formats:
        options["openvino_ir_precision"] = str(request.metadata.get("openvino_ir_precision") or "fp32")
    if "tensorrt-engine" in request.target_formats:
        options["tensorrt_engine_precision"] = str(
            request.metadata.get("tensorrt_engine_precision") or "fp32"
        )
    return options