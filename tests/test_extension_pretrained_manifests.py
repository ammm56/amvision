"""扩展节点预训练 manifest 重生测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.maintenance.extension_pretrained_manifests import (
    sync_extension_pretrained_manifests,
)


def test_sync_extension_pretrained_manifests_moves_legacy_yoloe_root_and_writes_manifests(
    tmp_path: Path,
) -> None:
    """验证 legacy yoloe/detection 会迁到 segmentation，并写出 manifest。"""

    yoloe_variant_dir = (
        tmp_path
        / "data"
        / "files"
        / "models"
        / "pretrained"
        / "yoloe"
        / "detection"
        / "s"
        / "v8-default"
    )
    yoloe_checkpoint_dir = yoloe_variant_dir / "checkpoints"
    yoloe_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (yoloe_checkpoint_dir / "yoloe-v8s-seg.pt").write_bytes(b"fake")

    sam3_variant_dir = (
        tmp_path
        / "data"
        / "files"
        / "models"
        / "pretrained"
        / "sam3"
        / "segmentation"
        / "l"
        / "default"
    )
    sam3_checkpoint_dir = sam3_variant_dir / "checkpoints"
    sam3_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (sam3_checkpoint_dir / "sam3.pt").write_bytes(b"fake")

    result = sync_extension_pretrained_manifests(tmp_path)

    assert result.moved_legacy_yoloe_root is True
    yoloe_manifest_path = (
        tmp_path
        / "data"
        / "files"
        / "models"
        / "pretrained"
        / "yoloe"
        / "segmentation"
        / "s"
        / "v8-default"
        / "manifest.json"
    )
    sam3_manifest_path = sam3_variant_dir / "manifest.json"
    yoloe_manifest = json.loads(yoloe_manifest_path.read_text(encoding="utf-8"))
    sam3_manifest = json.loads(sam3_manifest_path.read_text(encoding="utf-8"))

    assert yoloe_manifest["task_type"] == "segmentation"
    assert yoloe_manifest["checkpoint_path"] == "checkpoints/yoloe-v8s-seg.pt"
    assert sam3_manifest["task_type"] == "segmentation"
    assert sam3_manifest["checkpoint_path"] == "checkpoints/sam3.pt"


def test_sync_extension_pretrained_manifests_marks_prompt_free_yoloe_variants(
    tmp_path: Path,
) -> None:
    """验证 prompt-free YOLOE 变体会写入对应 metadata。"""

    variant_dir = (
        tmp_path
        / "data"
        / "files"
        / "models"
        / "pretrained"
        / "yoloe"
        / "segmentation"
        / "nano"
        / "26-prompt-free"
    )
    checkpoint_dir = variant_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "yoloe-26n-seg-pf.pt").write_bytes(b"fake")

    result = sync_extension_pretrained_manifests(tmp_path)

    manifest_path = variant_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result.moved_legacy_yoloe_root is False
    assert manifest["metadata"]["upstream_mode"] == "prompt-free"
    assert manifest["model_version_id"].endswith("-prompt-free")
