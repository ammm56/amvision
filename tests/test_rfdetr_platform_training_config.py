"""RF-DETR 平台训练参数与 resume 契约测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core._namespace import (
    _namespace_from_configs,
)
from backend.service.application.models.rfdetr_core.factory import (
    build_rfdetr_full_core_config,
)
from backend.service.application.models.rfdetr_core.export.execution import (
    resolve_rfdetr_export_input_size_summary,
)
from backend.service.application.models.rfdetr_core.training.platform_artifacts import (
    prepare_resume_checkpoint,
)
from backend.service.application.models.rfdetr_core.training.platform_dataset import (
    _build_rfdetr_roboflow_file_name,
    prepare_roboflow_coco_dataset,
)
from backend.service.application.models.rfdetr_core.training.callbacks.best_model import (
    BestModelCallback,
)
from backend.service.application.models.rfdetr_core.training.platform_runner import (
    RfdetrPlatformTrainingRequest,
    _build_train_config,
    _resolve_rfdetr_final_learning_rate,
    resolve_rfdetr_platform_training_input_size,
)
from backend.service.application.models.rfdetr_core.training import (
    platform_runner as platform_runner_module,
)
from backend.service.application.models.training.device_selection import (
    SingleTrainingDeviceSelection,
)
from backend.service.application.models.training.rfdetr_detection import (
    RfdetrTrainingExecutionRequest,
)
from backend.service.application.models.training.rfdetr_segmentation import (
    RfdetrSegmentationTrainingExecutionRequest,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_rfdetr_platform_dataset_preserves_nested_image_paths() -> None:
    """验证同名图片不会因压平路径而在 RF-DETR 临时数据集中互相覆盖。"""

    assert _build_rfdetr_roboflow_file_name(
        split_name="train",
        file_name="train/camera-a/shared.jpg",
    ) == "camera-a/shared.jpg"
    assert _build_rfdetr_roboflow_file_name(
        split_name="train",
        file_name="camera-b/shared.jpg",
    ) == "camera-b/shared.jpg"


def test_rfdetr_platform_dataset_reads_extended_length_source_paths(
    tmp_path: Path,
) -> None:
    """验证 RF-DETR 数据准备可读取 Windows extended-length 图片路径。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    long_image_root = "/".join(
        f"segment-{index}-{'x' * 40}" for index in range(6)
    )
    splits: list[dict[str, object]] = []
    for split_index, split_name in enumerate(("train", "val"), start=1):
        image_key = f"{long_image_root}/{split_name}/sample.jpg"
        annotation_key = f"annotations/{split_name}.json"
        storage.write_bytes(image_key, f"image-{split_name}".encode())
        storage.write_json(
            annotation_key,
            {
                "images": [
                    {
                        "id": split_index,
                        "file_name": f"{split_name}/sample.jpg",
                        "width": 16,
                        "height": 16,
                    }
                ],
                "annotations": [
                    {
                        "id": split_index,
                        "image_id": split_index,
                        "category_id": 0,
                        "bbox": [1, 1, 4, 4],
                    }
                ],
                "categories": [{"id": 0, "name": "part"}],
            },
        )
        splits.append(
            {
                "name": split_name,
                "annotation_file": annotation_key,
                "image_root": long_image_root,
            }
        )

    prepared = prepare_roboflow_coco_dataset(
        dataset_storage=storage,
        manifest_payload={"splits": splits},
        dataset_dir=tmp_path / "prepared",
        task_type=DETECTION_TASK_TYPE,
    )

    assert prepared.labels == ("part",)
    assert (prepared.dataset_dir / "train" / "sample.jpg").read_bytes() == b"image-train"
    assert (prepared.dataset_dir / "valid" / "val" / "sample.jpg").read_bytes() == b"image-val"


def test_rfdetr_export_rejects_implicit_input_alignment() -> None:
    """转换不得把已登记尺寸静默改成另一组实际张量尺寸。"""

    with pytest.raises(InvalidRequestError, match="禁止静默对齐") as exc_info:
        resolve_rfdetr_export_input_size_summary(
            task_type=DETECTION_TASK_TYPE,
            model_scale="nano",
            input_size=(385, 641),
        )

    assert exc_info.value.details["input_size"] == {"width": 641, "height": 385}
    assert exc_info.value.details["nearest_aligned_input_size"] == {
        "width": 672,
        "height": 416,
    }


def test_rfdetr_export_keeps_aligned_non_square_input() -> None:
    """合法非方形输入必须原样进入 RF-DETR 导出张量。"""

    effective, summary = resolve_rfdetr_export_input_size_summary(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        input_size=(384, 640),
    )

    assert effective == (384, 640)
    assert summary["effective"] == {"width": 640, "height": 384}


def test_rfdetr_final_learning_rate_uses_actual_optimizer_state() -> None:
    """训练摘要必须读取 optimizer 的实际最终学习率。"""

    trainer = SimpleNamespace(
        optimizers=[SimpleNamespace(param_groups=[{"lr": 2.5e-5}])]
    )
    assert _resolve_rfdetr_final_learning_rate(
        trainer=trainer,
        fallback=1e-4,
    ) == pytest.approx(2.5e-5)


def _request(
    *, task_type: str, extra_options: dict[str, object]
) -> RfdetrPlatformTrainingRequest:
    """构造不访问 dataset storage 的参数映射请求。"""

    return RfdetrPlatformTrainingRequest(
        dataset_storage=None,  # type: ignore[arg-type]
        manifest_payload={},
        task_type=task_type,
        model_scale="nano",
        batch_size=2,
        max_epochs=3,
        input_size=(384, 384),
        precision="fp32",
        extra_options=extra_options,
    )


def _build_config(
    tmp_path: Path,
    *,
    task_type: str,
    extra_options: dict[str, object],
    resume_checkpoint_path: str | None = None,
):
    """调用平台参数适配层构造 TrainConfig。"""

    return _build_train_config(
        request=_request(task_type=task_type, extra_options=extra_options),
        dataset_dir=tmp_path / "dataset",
        output_dir=tmp_path / "output",
        labels=("part",),
        extra_options=extra_options,
        device_selection=SingleTrainingDeviceSelection(
            device_name="cpu",
            device_index=None,
        ),
        resume_checkpoint_path=resume_checkpoint_path,
    )


def test_rfdetr_detection_platform_maps_matcher_loss_and_recipe_options(
    tmp_path: Path,
) -> None:
    """Detection 前端参数必须真实进入 matcher、criterion 和训练配方。"""

    options = {
        "learning_rate": 2e-4,
        "class_cost": 1.1,
        "bbox_cost": 4.2,
        "giou_cost": 1.7,
        "class_loss_weight": 0.8,
        "bbox_loss_weight": 4.5,
        "giou_loss_weight": 1.9,
        "grad_accum_steps": 2,
    }
    train_config = _build_config(
        tmp_path,
        task_type=DETECTION_TASK_TYPE,
        extra_options=options,
    )
    model_config = build_rfdetr_full_core_config(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=1,
        device="cpu",
    )
    namespace = _namespace_from_configs(model_config, train_config)

    assert train_config.lr == pytest.approx(2e-4)
    assert train_config.grad_accum_steps == 2
    assert train_config.use_ema is True
    assert train_config.multi_scale is True
    assert train_config.expanded_scales is True
    assert namespace.set_cost_class == pytest.approx(1.1)
    assert namespace.set_cost_bbox == pytest.approx(4.2)
    assert namespace.set_cost_giou == pytest.approx(1.7)
    assert namespace.cls_loss_coef == pytest.approx(0.8)
    assert namespace.bbox_loss_coef == pytest.approx(4.5)
    assert namespace.giou_loss_coef == pytest.approx(1.9)


def test_rfdetr_recipe_boolean_strings_and_default_epochs_are_stable(
    tmp_path: Path,
) -> None:
    """配置字符串不得把 false 误判为 true，默认训练不能退化成单 epoch。"""

    train_config = _build_config(
        tmp_path,
        task_type=DETECTION_TASK_TYPE,
        extra_options={
            "use_ema": "false",
            "multi_scale": "false",
            "expanded_scales": "false",
        },
    )

    assert train_config.use_ema is False
    assert train_config.multi_scale is False
    assert train_config.expanded_scales is False
    assert (
        RfdetrTrainingExecutionRequest(
            dataset_storage=object(),  # type: ignore[arg-type]
            manifest_payload={},
        ).max_epochs
        == 100
    )
    assert (
        RfdetrSegmentationTrainingExecutionRequest(
            dataset_storage=object(),  # type: ignore[arg-type]
            manifest_payload={},
        ).max_epochs
        == 100
    )


def test_rfdetr_segmentation_platform_maps_mask_and_cosine_options(
    tmp_path: Path,
) -> None:
    """Segmentation mask 权重和最小学习率比例不得被静默忽略。"""

    options = {
        "lr_scheduler": "cosine",
        "min_lr_ratio": 0.03,
        "class_loss_weight": 1.25,
        "mask_ce_weight": 6.0,
        "mask_dice_weight": 7.0,
    }
    train_config = _build_config(
        tmp_path,
        task_type=SEGMENTATION_TASK_TYPE,
        extra_options=options,
        resume_checkpoint_path="resume.ckpt",
    )
    model_config = build_rfdetr_full_core_config(
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale="nano",
        num_classes=1,
        device="cpu",
    )
    namespace = _namespace_from_configs(model_config, train_config)

    assert train_config.resume == "resume.ckpt"
    assert train_config.lr_scheduler == "cosine"
    assert train_config.lr_min_factor == pytest.approx(0.03)
    assert namespace.cls_loss_coef == pytest.approx(1.25)
    assert namespace.mask_ce_loss_coef == pytest.approx(6.0)
    assert namespace.mask_dice_loss_coef == pytest.approx(7.0)


def test_rfdetr_step_scheduler_ignores_cosine_minimum_ratio(tmp_path: Path) -> None:
    """Step 为默认策略，不能因 min_lr_ratio 存在而隐式切换。"""

    train_config = _build_config(
        tmp_path,
        task_type=SEGMENTATION_TASK_TYPE,
        extra_options={"min_lr_ratio": 0.03},
    )
    assert train_config.lr_scheduler == "step"
    assert train_config.lr_min_factor == pytest.approx(0.0)


def test_prepare_rfdetr_resume_checkpoint_preserves_full_lightning_state(
    tmp_path: Path,
) -> None:
    """完整 Lightning checkpoint 必须原样用于 resume，不能降级成预训练权重。"""

    checkpoint_path = tmp_path / "resume.ckpt"
    payload = {
        "state_dict": {"model.weight": torch.tensor([1.0])},
        "optimizer_states": [{"state": {}, "param_groups": []}],
        "lr_schedulers": [{"last_epoch": 4}],
        "epoch": 4,
        "global_step": 20,
        "pytorch-lightning_version": "2.6.5",
    }
    torch.save(payload, checkpoint_path)

    resolved = prepare_resume_checkpoint(checkpoint_path, tmp_path)

    assert resolved == str(checkpoint_path)
    restored = torch.load(resolved, map_location="cpu", weights_only=False)
    assert restored["optimizer_states"] == payload["optimizer_states"]
    assert restored["lr_schedulers"] == payload["lr_schedulers"]
    assert restored["epoch"] == 4
    assert restored["global_step"] == 20


def test_prepare_rfdetr_resume_checkpoint_converts_legacy_model_payload(
    tmp_path: Path,
) -> None:
    """旧 ModelVersion 仍可恢复模型与 epoch，但不伪造不存在的优化器状态。"""

    checkpoint_path = tmp_path / "legacy.pth"
    torch.save(
        {
            "model": {"weight": torch.tensor([2.0])},
            "args": {},
            "epoch": 2,
        },
        checkpoint_path,
    )

    resolved = prepare_resume_checkpoint(checkpoint_path, tmp_path)

    assert resolved is not None
    restored = torch.load(resolved, map_location="cpu", weights_only=False)
    assert torch.equal(restored["state_dict"]["model.weight"], torch.tensor([2.0]))
    assert restored["epoch"] == 2
    assert restored["optimizer_states"] == []


def test_rfdetr_platform_records_effective_square_training_input() -> None:
    """矩形请求必须收敛并记录为 core 实际训练使用的方形尺寸。"""

    assert resolve_rfdetr_platform_training_input_size(
        task_type=DETECTION_TASK_TYPE,
        model_scale="s",
        input_size=(385, 630),
    ) == (640, 640)


def test_rfdetr_best_checkpoint_preserves_full_lightning_resume_state() -> None:
    """部署 model 与 Lightning resume state 可以共存于同一个 checkpoint。"""

    connector = SimpleNamespace(
        dump_checkpoint=Mock(
            return_value={
                "optimizer_states": [{"state": {"step": 3}}],
                "lr_schedulers": [{"last_epoch": 2}],
                "callbacks": {"callback": {"best": 0.8}},
            }
        )
    )
    trainer = SimpleNamespace(
        current_epoch=2,
        global_step=12,
        _checkpoint_connector=connector,
    )
    deployment_state = {"weight": torch.tensor([2.0])}
    resume_state = {"weight": torch.tensor([1.0])}

    payload = BestModelCallback._build_checkpoint_payload(
        deployment_state,
        {"epochs": 3},
        trainer,
        model_name="RFDETRNano",
        resume_model_state_dict=resume_state,
    )

    connector.dump_checkpoint.assert_called_once_with(weights_only=False)
    assert torch.equal(payload["model"]["weight"], torch.tensor([2.0]))
    assert torch.equal(payload["state_dict"]["model.weight"], torch.tensor([1.0]))
    assert payload["optimizer_states"] == [{"state": {"step": 3}}]
    assert payload["lr_schedulers"] == [{"last_epoch": 2}]
    assert payload["callbacks"] == {"callback": {"best": 0.8}}
    assert payload["epoch"] == 2
    assert payload["global_step"] == 12
    assert payload["pytorch-lightning_version"]


def test_rfdetr_platform_routes_resume_to_lightning_and_releases_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """resume 必须传给 Trainer.fit，训练退出时模型先迁回 CPU 并统一清理。"""

    prepared_dataset = SimpleNamespace(
        labels=("part",),
        dataset_dir=tmp_path / "prepared-dataset",
        has_test_split=False,
    )
    model_to = Mock()
    module = SimpleNamespace(model=SimpleNamespace(to=model_to))
    data_module = object()

    class _Trainer:
        callback_metrics = {"val/mAP_50_95": torch.tensor(0.8)}
        current_epoch = 1

        def __init__(self) -> None:
            self.fit_calls: list[dict[str, object]] = []

        def fit(self, fitted_module, *, datamodule, ckpt_path) -> None:
            self.fit_calls.append(
                {
                    "module": fitted_module,
                    "datamodule": datamodule,
                    "ckpt_path": ckpt_path,
                }
            )

    trainer = _Trainer()
    prepare_pretrain = Mock(return_value=None)
    release_resources = Mock()
    model_config = SimpleNamespace(resolution=384, amp=False)

    monkeypatch.setattr(
        platform_runner_module,
        "_resolve_device_selection",
        lambda options: SingleTrainingDeviceSelection(
            device_name="cpu", device_index=None
        ),
    )
    monkeypatch.setattr(
        platform_runner_module,
        "prepare_roboflow_coco_dataset",
        lambda **kwargs: prepared_dataset,
    )
    monkeypatch.setattr(
        platform_runner_module,
        "prepare_resume_checkpoint",
        lambda checkpoint_path, temporary_dir: "full-resume.ckpt",
    )
    monkeypatch.setattr(
        platform_runner_module,
        "prepare_pretrain_checkpoint",
        prepare_pretrain,
    )
    monkeypatch.setattr(
        platform_runner_module,
        "build_rfdetr_full_core_config",
        lambda **kwargs: model_config,
    )
    monkeypatch.setattr(
        platform_runner_module,
        "_load_rfdetr_lightning_training_components",
        lambda: (
            lambda model_config, train_config: data_module,
            lambda model_config, train_config: module,
            lambda *args, **kwargs: trainer,
        ),
    )
    monkeypatch.setattr(
        platform_runner_module,
        "read_or_build_checkpoint_artifacts",
        lambda **kwargs: SimpleNamespace(
            best_checkpoint_bytes=b"best-checkpoint",
            latest_checkpoint_bytes=b"checkpoint",
        ),
    )
    monkeypatch.setattr(
        platform_runner_module,
        "build_metrics_payload",
        lambda **kwargs: {"input_size": {"width": 384, "height": 384}},
    )
    monkeypatch.setattr(
        platform_runner_module,
        "build_validation_metrics_payload",
        lambda trainer: {"val/mAP_50_95": 0.8},
    )
    monkeypatch.setattr(
        platform_runner_module,
        "release_model_task_resources",
        release_resources,
    )

    request = RfdetrPlatformTrainingRequest(
        dataset_storage=SimpleNamespace(root_dir=tmp_path),  # type: ignore[arg-type]
        manifest_payload={},
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        batch_size=1,
        max_epochs=2,
        input_size=(384, 384),
        precision="fp32",
        resume_checkpoint_path=tmp_path / "resume.ckpt",
        warm_start_checkpoint_path=tmp_path / "warm-start.pth",
        extra_options={"device": "cpu"},
    )

    result = platform_runner_module.run_rfdetr_platform_training(request)

    assert result.latest_checkpoint_bytes == b"checkpoint"
    assert result.best_checkpoint_bytes == b"best-checkpoint"
    assert trainer.fit_calls == [
        {
            "module": module,
            "datamodule": data_module,
            "ckpt_path": "full-resume.ckpt",
        }
    ]
    prepare_pretrain.assert_called_once()
    assert prepare_pretrain.call_args.args[0] is None
    model_to.assert_called_once_with("cpu")
    release_resources.assert_called_once_with(trainer, data_module, module)


def test_rfdetr_warm_start_summary_does_not_expose_local_checkpoint_path(
    tmp_path: Path,
) -> None:
    """训练摘要只能暴露可追溯来源，不得泄漏宿主机绝对路径。"""

    checkpoint_path = tmp_path / "private" / "warm-start.pth"

    summary = platform_runner_module._build_warm_start_summary(
        warm_start_checkpoint_path=checkpoint_path,
        source_summary={"source_model_version_id": "model-version-1"},
        resume_checkpoint_path=None,
    )

    assert summary["enabled"] is True
    assert summary["source_model_version_id"] == "model-version-1"
    assert summary["load_summary"] == {"loader": "rfdetr-full-core-pretrain"}
    assert str(checkpoint_path) not in str(summary)
