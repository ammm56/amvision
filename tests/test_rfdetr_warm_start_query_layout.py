"""RF-DETR warm-start query 分组元数据门禁。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.catalog.yolo_model_pretrained_catalog import (
    _load_yolo_model_catalog_entry,
)
from backend.service.application.models.rfdetr_core.models.weights import (
    _resolve_checkpoint_query_layout,
    _slice_query_param_per_group,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_query_layout_reads_exact_catalog_manifest(tmp_path: Path) -> None:
    """checkpoint 没有 args 时只读取精确引用当前文件的 catalog manifest。"""

    checkpoint_path = tmp_path / "default" / "checkpoints" / "model.pth"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_bytes(b"checkpoint")
    manifest_path = checkpoint_path.parent.parent / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "checkpoint_path": "checkpoints/model.pth",
                "checkpoint_model_config": {
                    "num_queries": 100,
                    "group_detr": 13,
                },
            }
        ),
        encoding="utf-8",
    )

    assert _resolve_checkpoint_query_layout(
        checkpoint_args=None,
        checkpoint_path=checkpoint_path.resolve(),
    ) == (100, 13)


def test_query_layout_does_not_use_manifest_for_another_checkpoint(
    tmp_path: Path,
) -> None:
    """manifest 引用其他文件时不能把布局误用于当前 checkpoint。"""

    checkpoint_path = tmp_path / "default" / "checkpoints" / "model.pth"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_bytes(b"checkpoint")
    (checkpoint_path.parent.parent / "manifest.json").write_text(
        json.dumps(
            {
                "checkpoint_path": "checkpoints/another.pth",
                "checkpoint_model_config": {
                    "num_queries": 100,
                    "group_detr": 13,
                },
            }
        ),
        encoding="utf-8",
    )

    assert _resolve_checkpoint_query_layout(
        checkpoint_args=None,
        checkpoint_path=checkpoint_path.resolve(),
    ) == (None, None)


def test_partial_checkpoint_query_layout_is_rejected(tmp_path: Path) -> None:
    """只声明一个 query 维度不能再按 Tensor 行数猜测另一个维度。"""

    with pytest.raises(ValueError, match="必须同时存在"):
        _resolve_checkpoint_query_layout(
            checkpoint_args={"num_queries": 100},
            checkpoint_path=(tmp_path / "model.pth").resolve(),
        )


def test_query_slice_preserves_each_group_order() -> None:
    """缩减 query 数时逐组截取，不能使用破坏分组的 flat slice。"""

    tensor = torch.arange(8, dtype=torch.float32).reshape(8, 1)

    sliced = _slice_query_param_per_group(
        tensor,
        ckpt_num_queries=4,
        ckpt_group_detr=2,
        target_num_queries=2,
        target_group_detr=2,
    )

    assert sliced.flatten().tolist() == [0.0, 1.0, 4.0, 5.0]


def test_query_slice_rejects_layout_tensor_mismatch() -> None:
    """资产元数据与 Tensor 行数矛盾时必须失败，不能回退 flat slice。"""

    with pytest.raises(ValueError, match="元数据与 Tensor 行数不一致"):
        _slice_query_param_per_group(
            torch.zeros((7, 1)),
            ckpt_num_queries=4,
            ckpt_group_detr=2,
            target_num_queries=2,
            target_group_detr=2,
        )


def test_query_slice_rejects_layout_expansion() -> None:
    """warm-start 只能裁剪已有 query，不能隐式创建缺失 query。"""

    with pytest.raises(ValueError, match="不能从较小"):
        _slice_query_param_per_group(
            torch.zeros((8, 1)),
            ckpt_num_queries=4,
            ckpt_group_detr=2,
            target_num_queries=5,
            target_group_detr=2,
        )


def test_rfdetr_catalog_requires_query_layout_metadata(tmp_path: Path) -> None:
    """正式 RF-DETR catalog 资产缺少布局元数据时在启动登记阶段失败。"""

    manifest_path, dataset_storage = _write_rfdetr_catalog_asset(
        tmp_path,
        checkpoint_model_config=None,
    )

    with pytest.raises(ServiceConfigurationError, match="checkpoint_model_config"):
        _load_yolo_model_catalog_entry(
            manifest_path=manifest_path,
            dataset_storage=dataset_storage,
            model_type="rfdetr",
        )


def test_rfdetr_catalog_registers_query_layout_metadata(tmp_path: Path) -> None:
    """已补齐的 query 布局随 ModelVersion metadata 一起登记。"""

    manifest_path, dataset_storage = _write_rfdetr_catalog_asset(
        tmp_path,
        checkpoint_model_config={"num_queries": 100, "group_detr": 13},
    )

    entry = _load_yolo_model_catalog_entry(
        manifest_path=manifest_path,
        dataset_storage=dataset_storage,
        model_type="rfdetr",
    )

    assert entry.metadata["checkpoint_model_config"] == {
        "num_queries": 100,
        "group_detr": 13,
    }


def _write_rfdetr_catalog_asset(
    tmp_path: Path,
    *,
    checkpoint_model_config: dict[str, int] | None,
) -> tuple[Path, LocalDatasetStorage]:
    """写入一个隔离的 RF-DETR catalog 资产。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    asset_dir = (
        dataset_storage.root_dir
        / "models"
        / "pretrained"
        / "rfdetr"
        / "segmentation"
        / "nano"
        / "default"
    )
    checkpoint_path = asset_dir / "checkpoints" / "model.pth"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_bytes(b"checkpoint")
    payload: dict[str, object] = {
        "model_name": "rfdetr",
        "model_scale": "nano",
        "task_type": "segmentation",
        "model_version_id": "mv-pretrained-rfdetr-segmentation-nano",
        "checkpoint_file_id": "mf-pretrained-rfdetr-segmentation-nano-checkpoint",
        "checkpoint_path": "checkpoints/model.pth",
        "metadata": {"source": "test"},
    }
    if checkpoint_model_config is not None:
        payload["checkpoint_model_config"] = checkpoint_model_config
    manifest_path = asset_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path, dataset_storage
