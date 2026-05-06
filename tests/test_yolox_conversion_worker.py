"""YOLOX conversion worker phase-1 集成测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.queue import LocalFileQueueBackend
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
    YoloXConversionTaskRequest,
)
from backend.service.application.models.yolox_model_service import SqlAlchemyYoloXModelService
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
from tests.yolox_test_support import create_yolox_test_runtime, seed_yolox_model_version



@pytest.mark.parametrize(
    (
        "target_formats",
        "extra_options",
        "expected_produced_formats",
        "expected_phase",
        "expected_conversion_options",
    ),
    [
        (("onnx",), {}, ("onnx",), "phase-1-onnx", {}),
        (("onnx-optimized",), {}, ("onnx", "onnx-optimized"), "phase-1-onnx", {}),
        (
            ("openvino-ir",),
            {"openvino_ir_precision": "fp32"},
            ("onnx", "onnx-optimized", "openvino-ir"),
            "phase-2-openvino-ir",
            {"openvino_ir_precision": "fp32"},
        ),
        (
            ("openvino-ir",),
            {"openvino_ir_precision": "fp16"},
            ("onnx", "onnx-optimized", "openvino-ir"),
            "phase-2-openvino-ir",
            {"openvino_ir_precision": "fp16"},
        ),
        (
            ("tensorrt-engine",),
            {"tensorrt_engine_precision": "fp32"},
            ("onnx", "onnx-optimized", "tensorrt-engine"),
            "phase-2-tensorrt-engine",
            {"tensorrt_engine_precision": "fp32"},
        ),
        (
            ("tensorrt-engine",),
            {"tensorrt_engine_precision": "fp16"},
            ("onnx", "onnx-optimized", "tensorrt-engine"),
            "phase-2-tensorrt-engine",
            {"tensorrt_engine_precision": "fp16"},
        ),
    ],
)
def test_conversion_queue_worker_executes_supported_targets(
    tmp_path: Path,
    target_formats: tuple[str, ...],
    extra_options: dict[str, object],
    expected_produced_formats: tuple[str, ...],
    expected_phase: str,
    expected_conversion_options: dict[str, object],
) -> None:
    """验证 conversion queue worker 可以跑通当前已接通的转换目标并完成登记链。"""

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_placeholder_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    submission = service.submit_conversion_task(
        YoloXConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=target_formats,
            extra_options=extra_options,
        )
    )

    worker = YoloXConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_FakeYoloXConversionRunner(dataset_storage=dataset_storage),
    )

    assert worker.run_once() is True

    result = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).process_conversion_task(submission.task_id)
    task_detail = SqlAlchemyTaskService(session_factory).get_task(submission.task_id, include_events=True)
    report_payload = json.loads(dataset_storage.resolve(result.report_object_key).read_text(encoding="utf-8"))

    assert submission.status == "queued"
    assert task_detail.task.state == "succeeded"
    assert result.status == "succeeded"
    assert result.requested_target_formats == target_formats
    assert result.produced_formats == expected_produced_formats
    assert len(result.builds) == len(expected_produced_formats)
    assert {item.build_format for item in result.builds} == set(expected_produced_formats)
    assert dataset_storage.resolve(result.plan_object_key).is_file() is True
    assert dataset_storage.resolve(result.report_object_key).is_file() is True
    assert report_payload["validation_summary"]["allclose"] is True
    assert report_payload["planned_target_formats"] == list(target_formats)
    assert report_payload["phase"] == expected_phase
    assert report_payload["conversion_options"] == expected_conversion_options

    model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    for build_summary in result.builds:
        model_build = model_service.get_model_build(build_summary.model_build_id)
        assert model_build is not None
        assert model_build.conversion_task_id == submission.task_id
        build_path = dataset_storage.resolve(build_summary.build_file_uri)
        assert build_path.is_file() is True
        if build_summary.build_format == "openvino-ir":
            assert build_path.suffix == ".xml"
            assert build_path.with_suffix(".bin").is_file() is True
            assert build_summary.metadata["build_precision"] == expected_conversion_options["openvino_ir_precision"]
            assert build_summary.metadata["compress_to_fp16"] is (
                expected_conversion_options["openvino_ir_precision"] == "fp16"
            )
            assert model_build.metadata["build_precision"] == expected_conversion_options["openvino_ir_precision"]
            assert model_build.metadata["compress_to_fp16"] is (
                expected_conversion_options["openvino_ir_precision"] == "fp16"
            )
        if build_summary.build_format == "tensorrt-engine":
            assert build_path.suffix == ".engine"
            expected_tensorrt_precision = str(expected_conversion_options["tensorrt_engine_precision"])
            assert build_summary.metadata["build_precision"] == expected_tensorrt_precision
            assert model_build.metadata["build_precision"] == expected_tensorrt_precision


def _create_test_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建 conversion 测试使用的数据库、文件存储和队列。"""

    return create_yolox_test_runtime(tmp_path, database_name="amvision-yolox-conversion.db")


def _seed_placeholder_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个仅用于逻辑测试的最小训练输出 ModelVersion。"""

    return seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="conversion-source-1",
        training_task_id="training-conversion-source-1",
        model_name="yolox-nano-conversion",
        dataset_version_id="dataset-version-conversion-source-1",
        checkpoint_file_id="checkpoint-file-conversion-1",
        labels_file_id="labels-file-conversion-1",
    )


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