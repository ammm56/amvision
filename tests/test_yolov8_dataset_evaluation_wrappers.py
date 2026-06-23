"""YOLOv8 数据集级评估入口测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.service.application.models.evaluation import obb_evaluation as obb_module
from backend.service.application.models.evaluation import pose_evaluation as pose_module
from backend.service.application.models.evaluation import (
    segmentation_evaluation as segmentation_module,
)
from backend.service.application.models.yolov8_core.evaluation import obb as yolov8_obb_module
from backend.service.application.models.yolov8_core.evaluation import pose as yolov8_pose_module
from backend.service.application.models.yolov8_core.evaluation import segmentation as yolov8_segmentation_module


class _FakeDatasetStorage:
    """提供数据集级评估测试需要的最小本地存储接口。"""

    def __init__(self, root):
        self.root = root
        self.written_json: dict[str, object] = {}

    def resolve(self, object_key: str):
        return self.root / object_key

    def write_json(self, object_key: str, payload: object) -> None:
        self.written_json[object_key] = payload
        target = self.resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")


def test_yolov8_segmentation_dataset_evaluation_runs_inside_yolov8_core(monkeypatch, tmp_path) -> None:
    """验证 YOLOv8 segmentation 数据集级入口不再回调旧 primary evaluator。"""

    image_path = tmp_path / "images" / "a.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image")

    class FakeRuntime:
        def load_session(self, *, dataset_storage, runtime_target):
            assert runtime_target.model_version_id == "mv-seg"
            return FakeSession()

    class FakeSession:
        def predict(self, request):
            assert request.input_image_bytes == b"fake-image"
            assert request.score_threshold == 0.25
            assert request.mask_threshold == 0.6
            return SimpleNamespace(
                image_width=12,
                image_height=12,
                latency_ms=1.0,
                instances=[
                    SimpleNamespace(
                        class_id=0,
                        bbox_xyxy=[0.0, 0.0, 10.0, 10.0],
                        score=0.95,
                        segments=(
                            [
                                [0.0, 0.0],
                                [10.0, 0.0],
                                [10.0, 10.0],
                                [0.0, 10.0],
                            ],
                        ),
                    ),
                ],
            )

    monkeypatch.setattr(yolov8_segmentation_module, "DefaultSegmentationModelRuntime", FakeRuntime)

    result = yolov8_segmentation_module.run_yolov8_segmentation_evaluation(
        yolov8_segmentation_module.YoloV8SegmentationEvaluationRequest(
            dataset_storage=_FakeDatasetStorage(tmp_path),
            runtime_target=SimpleNamespace(model_version_id="mv-seg", model_type="yolov8"),
            manifest_payload={
                "categories": [{"id": 0, "name": "part"}],
                "splits": [
                    {
                        "name": "val",
                        "image_root": "images",
                        "images": [{"id": 1, "file_name": "a.jpg"}],
                        "annotations": [
                            {
                                "image_id": 1,
                                "category_id": 0,
                                "bbox": [0.0, 0.0, 10.0, 10.0],
                                "segmentation": [
                                    [
                                        0.0,
                                        0.0,
                                        10.0,
                                        0.0,
                                        10.0,
                                        10.0,
                                        0.0,
                                        10.0,
                                    ],
                                ],
                            },
                        ],
                    },
                ],
            },
            score_threshold=0.25,
            mask_threshold=0.6,
            extra_options={"limit": 2},
        ),
    )

    assert not hasattr(yolov8_segmentation_module, "run_segmentation_evaluation")
    assert result.sample_count == 1
    assert result.map50 == 1.0
    assert result.mask_map50 == 1.0
    assert result.report_payload["model_type"] == "yolov8"


def test_yolov8_pose_dataset_evaluation_delegates_to_platform_evaluator(monkeypatch) -> None:
    """验证 YOLOv8 pose 数据集级入口会构造正式评估请求。"""

    captured = {}
    expected_result = SimpleNamespace(sample_count=1)

    def fake_run(request):
        captured["request"] = request
        return expected_result

    monkeypatch.setattr(yolov8_pose_module, "run_pose_evaluation", fake_run)

    runtime_target = SimpleNamespace(model_type="yolov8")
    result = yolov8_pose_module.run_yolov8_pose_evaluation(
        yolov8_pose_module.YoloV8PoseEvaluationRequest(
            dataset_storage=SimpleNamespace(),
            runtime_target=runtime_target,
            manifest_payload={"splits": []},
            score_threshold=0.35,
            extra_options={"limit": 3},
        ),
    )

    assert result is expected_result
    assert captured["request"].runtime_target is runtime_target
    assert captured["request"].score_threshold == 0.35
    assert captured["request"].extra_options == {"limit": 3}


def test_yolov8_obb_dataset_evaluation_delegates_to_platform_evaluator(monkeypatch) -> None:
    """验证 YOLOv8 OBB 数据集级入口会构造正式评估请求。"""

    captured = {}
    expected_result = SimpleNamespace(sample_count=1)

    def fake_run(request):
        captured["request"] = request
        return expected_result

    monkeypatch.setattr(yolov8_obb_module, "run_obb_evaluation", fake_run)

    runtime_target = SimpleNamespace(model_type="yolov8")
    result = yolov8_obb_module.run_yolov8_obb_evaluation(
        yolov8_obb_module.YoloV8ObbEvaluationRequest(
            dataset_storage=SimpleNamespace(),
            runtime_target=runtime_target,
            manifest_payload={"splits": []},
            score_threshold=0.45,
            extra_options={"limit": 4},
        ),
    )

    assert result is expected_result
    assert captured["request"].runtime_target is runtime_target
    assert captured["request"].score_threshold == 0.45
    assert captured["request"].extra_options == {"limit": 4}


def test_pose_evaluation_uses_loaded_runtime_session(monkeypatch, tmp_path) -> None:
    """验证 pose 评估通过 runtime session 执行预测并返回报告 payload。"""

    image_path = tmp_path / "images" / "a.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image")
    calls = {"load_session": 0, "predict": 0}

    class FakeRuntime:
        def load_session(self, *, dataset_storage, runtime_target):
            calls["load_session"] += 1
            assert runtime_target.model_version_id == "mv-pose"
            return FakeSession()

    class FakeSession:
        def predict(self, request):
            calls["predict"] += 1
            assert request.input_image_bytes == b"fake-image"
            return SimpleNamespace(
                detections=[
                    SimpleNamespace(
                        class_id=0,
                        keypoints=[1.0, 1.0, 2.0, 2.0, 2.0, 2.0],
                        score=0.9,
                    ),
                ],
            )

    monkeypatch.setattr(pose_module, "DefaultPoseModelRuntime", FakeRuntime)

    result = pose_module.run_pose_evaluation(
        pose_module.PoseEvaluationRequest(
            dataset_storage=_FakeDatasetStorage(tmp_path),
            runtime_target=SimpleNamespace(model_version_id="mv-pose", model_type="yolov8"),
            manifest_payload={
                "categories": [{"id": 0, "name": "person"}],
                "splits": [
                    {
                        "name": "val",
                        "image_root": "images",
                        "images": [{"id": 1, "file_name": "a.jpg"}],
                        "annotations": [
                            {
                                "image_id": 1,
                                "category_id": 0,
                                "keypoints": [1.0, 1.0, 2.0, 2.0, 2.0, 2.0],
                                "num_keypoints": 2,
                            },
                        ],
                    },
                ],
            },
        ),
    )

    assert calls == {"load_session": 1, "predict": 1}
    assert result.sample_count == 1
    assert result.report_payload["sample_count"] == 1
    assert result.oks_ap50 == 1.0
    assert result.oks_ap50_95 == 1.0
    assert result.predictions_payload[0]["score"] == 0.9


def test_segmentation_evaluation_computes_bbox_and_mask_ap(monkeypatch, tmp_path) -> None:
    """验证 segmentation 评估同时计算 bbox AP 和 mask AP。"""

    image_path = tmp_path / "images" / "a.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image")

    class FakeRuntime:
        def load_session(self, *, dataset_storage, runtime_target):
            assert runtime_target.model_version_id == "mv-seg"
            return FakeSession()

    class FakeSession:
        def predict(self, request):
            assert request.input_image_bytes == b"fake-image"
            return SimpleNamespace(
                image_width=12,
                image_height=12,
                latency_ms=1.0,
                instances=[
                    SimpleNamespace(
                        class_id=0,
                        bbox_xyxy=[0.0, 0.0, 10.0, 10.0],
                        score=0.95,
                        segments=(
                            [
                                [0.0, 0.0],
                                [10.0, 0.0],
                                [10.0, 10.0],
                                [0.0, 10.0],
                            ],
                        ),
                    ),
                ],
            )

    monkeypatch.setattr(segmentation_module, "DefaultSegmentationModelRuntime", FakeRuntime)

    result = segmentation_module.run_segmentation_evaluation(
        segmentation_module.SegmentationEvaluationRequest(
            dataset_storage=_FakeDatasetStorage(tmp_path),
            runtime_target=SimpleNamespace(model_version_id="mv-seg", model_type="yolov8"),
            manifest_payload={
                "categories": [{"id": 0, "name": "part"}],
                "splits": [
                    {
                        "name": "val",
                        "image_root": "images",
                        "images": [{"id": 1, "file_name": "a.jpg"}],
                        "annotations": [
                            {
                                "image_id": 1,
                                "category_id": 0,
                                "bbox": [0.0, 0.0, 10.0, 10.0],
                                "segmentation": [
                                    [
                                        0.0,
                                        0.0,
                                        10.0,
                                        0.0,
                                        10.0,
                                        10.0,
                                        0.0,
                                        10.0,
                                    ],
                                ],
                            },
                        ],
                    },
                ],
            },
        ),
    )

    assert result.sample_count == 1
    assert result.map50 == 1.0
    assert result.map50_95 == 1.0
    assert result.mask_map50 == 1.0
    assert result.mask_map50_95 == 1.0


def test_obb_evaluation_uses_loaded_runtime_session(monkeypatch, tmp_path) -> None:
    """验证 OBB 评估通过 runtime session 执行预测并返回报告 payload。"""

    image_path = tmp_path / "a.jpg"
    image_path.write_bytes(b"fake-image")
    calls = {"load_session": 0, "predict": 0}

    class FakeRuntime:
        def load_session(self, *, dataset_storage, runtime_target):
            calls["load_session"] += 1
            assert runtime_target.model_version_id == "mv-obb"
            return FakeSession()

    class FakeSession:
        def predict(self, request):
            calls["predict"] += 1
            assert request.input_image_bytes == b"fake-image"
            return SimpleNamespace(
                detections=[
                    SimpleNamespace(
                        class_id=0,
                        bbox=[10.0, 10.0, 4.0, 2.0, 0.0],
                        score=0.8,
                    ),
                ],
            )

    monkeypatch.setattr(
        "backend.service.application.runtime.tasks.obb_model_runtime.DefaultObbModelRuntime",
        FakeRuntime,
    )

    result = obb_module.run_obb_evaluation(
        obb_module.ObbEvaluationRequest(
            dataset_storage=_FakeDatasetStorage(tmp_path),
            runtime_target=SimpleNamespace(model_version_id="mv-obb", model_type="yolov8"),
            manifest_payload={
                "images": [{"id": 1, "file_name": "a.jpg"}],
                "annotations": [
                    {
                        "image_id": 1,
                        "category_id": 0,
                        "bbox": [10.0, 10.0, 4.0, 2.0, 0.0],
                    },
                ],
                "categories": [{"id": 0, "name": "part"}],
            },
        ),
    )

    assert calls == {"load_session": 1, "predict": 1}
    assert result.sample_count == 1
    assert result.report_payload["sample_count"] == 1
    assert result.map50 == 1.0
    assert result.map50_95 == 1.0
    assert result.predictions_payload[0]["score"] == 0.8
