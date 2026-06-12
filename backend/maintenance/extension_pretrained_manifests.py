"""YOLOE 与 SAM3 扩展节点预训练目录扫描与 manifest 重生。"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_YOLOE_WEIGHT_PATTERN = re.compile(
    r"^yoloe-(?P<family>v8|11|26)(?P<size>n|s|m|l|x)-seg(?P<prompt_free>-pf)?\.pt$",
    re.IGNORECASE,
)
_SIZE_TOKEN_TO_SCALE = {
    "n": "nano",
    "s": "s",
    "m": "m",
    "l": "l",
    "x": "x",
}


@dataclass(frozen=True)
class ExtensionPretrainedManifestSyncResult:
    """描述一次扩展节点预训练 manifest 重生结果。"""

    moved_legacy_yoloe_root: bool
    written_manifest_paths: tuple[Path, ...]
    warnings: tuple[str, ...]


def sync_extension_pretrained_manifests(
    repository_root: Path | None = None,
) -> ExtensionPretrainedManifestSyncResult:
    """扫描 YOLOE 与 SAM3 资产目录并重写 manifest.json。

    参数：
    - repository_root：可选仓库根目录；为空时使用当前仓库根。

    返回：
    - ExtensionPretrainedManifestSyncResult：本次扫描、迁移和写入结果。
    """

    repo_root = repository_root.resolve() if repository_root is not None else REPOSITORY_ROOT
    pretrained_root = repo_root / "data" / "files" / "models" / "pretrained"
    yoloe_root = pretrained_root / "yoloe"
    sam3_root = pretrained_root / "sam3"

    warnings: list[str] = []
    moved_legacy_yoloe_root = _normalize_yoloe_task_root(yoloe_root, warnings=warnings)
    written_manifest_paths: list[Path] = []
    written_manifest_paths.extend(_sync_yoloe_manifests(yoloe_root, warnings=warnings))
    written_manifest_paths.extend(_sync_sam3_manifests(sam3_root, warnings=warnings))

    return ExtensionPretrainedManifestSyncResult(
        moved_legacy_yoloe_root=moved_legacy_yoloe_root,
        written_manifest_paths=tuple(written_manifest_paths),
        warnings=tuple(warnings),
    )


def _normalize_yoloe_task_root(yoloe_root: Path, *, warnings: list[str]) -> bool:
    """把遗留的 yoloe/detection 目录迁到 yoloe/segmentation。"""

    legacy_detection_root = yoloe_root / "detection"
    canonical_segmentation_root = yoloe_root / "segmentation"
    if not legacy_detection_root.is_dir():
        return False
    if canonical_segmentation_root.exists():
        warnings.append(
            "检测到 yoloe/detection 与 yoloe/segmentation 同时存在；未自动迁移 legacy detection 目录"
        )
        return False
    canonical_segmentation_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy_detection_root), str(canonical_segmentation_root))
    return True


def _sync_yoloe_manifests(yoloe_root: Path, *, warnings: list[str]) -> list[Path]:
    """扫描 YOLOE segmentation 权重目录并重写 manifest。"""

    task_root = yoloe_root / "segmentation"
    if not task_root.is_dir():
        warnings.append("未找到 yoloe/segmentation 目录，已跳过 YOLOE manifest 重生")
        return []

    written_manifest_paths: list[Path] = []
    for scale_dir in _iter_child_dirs(task_root):
        for variant_dir in _iter_child_dirs(scale_dir):
            checkpoint_path = _resolve_single_checkpoint_file(variant_dir / "checkpoints", warnings=warnings)
            if checkpoint_path is None:
                warnings.append(f"YOLOE 目录缺少可识别 checkpoint：{variant_dir.as_posix()}")
                continue
            match = _YOLOE_WEIGHT_PATTERN.match(checkpoint_path.name)
            if match is None:
                warnings.append(f"YOLOE checkpoint 文件名不符合官方命名规则：{checkpoint_path.name}")
                continue

            family_token = match.group("family").lower()
            size_token = match.group("size").lower()
            prompt_free = bool(match.group("prompt_free"))
            parsed_scale = _SIZE_TOKEN_TO_SCALE[size_token]
            if scale_dir.name != parsed_scale:
                warnings.append(
                    "YOLOE 目录 scale 与 checkpoint 文件名推断结果不一致："
                    f"{scale_dir.name} != {parsed_scale} ({checkpoint_path.name})"
                )
            expected_variant = f"{family_token}-{'prompt-free' if prompt_free else 'default'}"
            if variant_dir.name != expected_variant:
                warnings.append(
                    "YOLOE variant 目录名与 checkpoint 文件名推断结果不一致："
                    f"{variant_dir.name} != {expected_variant}"
                )

            model_name = f"yoloe-{family_token}"
            model_scale = parsed_scale
            task_type = "segmentation"
            model_version_id = (
                f"mv-pretrained-{model_name}-{task_type}-{model_scale}"
                f"{'-prompt-free' if prompt_free else ''}"
            )
            checkpoint_file_id = (
                f"mf-pretrained-{model_name}-{task_type}-{model_scale}-checkpoint"
                f"{'-prompt-free' if prompt_free else ''}"
            )
            manifest_payload = {
                "model_name": model_name,
                "model_scale": model_scale,
                "task_type": task_type,
                "model_version_id": model_version_id,
                "checkpoint_file_id": checkpoint_file_id,
                "checkpoint_path": str(checkpoint_path.relative_to(variant_dir)).replace("\\", "/"),
                "metadata": {
                    "catalog_name": variant_dir.name,
                    "entry_name": variant_dir.name,
                    "source": "local-pretrained",
                    "upstream_weight_name": checkpoint_path.name,
                    "upstream_mode": "prompt-free" if prompt_free else "default",
                    "node_usage": "custom-node",
                    "node_primary_output": "detections.v1",
                    "notes": "YOLOE 官方权重为 segmentation 变体，第一阶段 custom node 先以 detection 输出形式使用。"
                },
            }
            manifest_path = variant_dir / "manifest.json"
            _write_manifest_file(manifest_path, manifest_payload)
            written_manifest_paths.append(manifest_path)
    return written_manifest_paths


def _sync_sam3_manifests(sam3_root: Path, *, warnings: list[str]) -> list[Path]:
    """扫描 SAM3 segmentation 权重目录并重写 manifest。"""

    task_root = sam3_root / "segmentation"
    if not task_root.is_dir():
        warnings.append("未找到 sam3/segmentation 目录，已跳过 SAM3 manifest 重生")
        return []

    written_manifest_paths: list[Path] = []
    for scale_dir in _iter_child_dirs(task_root):
        for variant_dir in _iter_child_dirs(scale_dir):
            checkpoint_path = _resolve_single_checkpoint_file(variant_dir / "checkpoints", warnings=warnings)
            if checkpoint_path is None:
                warnings.append(f"SAM3 目录缺少可识别 checkpoint：{variant_dir.as_posix()}")
                continue
            if checkpoint_path.name.lower() != "sam3.pt":
                warnings.append(f"SAM3 checkpoint 文件名不是预期的 sam3.pt：{checkpoint_path.name}")

            variant_suffix = "" if variant_dir.name == "default" else f"-{variant_dir.name}"
            manifest_payload = {
                "model_name": "sam3",
                "model_scale": scale_dir.name,
                "task_type": "segmentation",
                "model_version_id": f"mv-pretrained-sam3-segmentation-{scale_dir.name}{variant_suffix}",
                "checkpoint_file_id": f"mf-pretrained-sam3-segmentation-{scale_dir.name}-checkpoint{variant_suffix}",
                "checkpoint_path": str(checkpoint_path.relative_to(variant_dir)).replace("\\", "/"),
                "metadata": {
                    "catalog_name": variant_dir.name,
                    "entry_name": variant_dir.name,
                    "source": "local-pretrained",
                    "upstream_weight_name": checkpoint_path.name,
                    "upstream_mode": "default",
                    "node_usage": "custom-node",
                    "node_modes": ["semantic", "interactive"],
                },
            }
            manifest_path = variant_dir / "manifest.json"
            _write_manifest_file(manifest_path, manifest_payload)
            written_manifest_paths.append(manifest_path)
    return written_manifest_paths


def _iter_child_dirs(root_dir: Path) -> tuple[Path, ...]:
    """返回一个目录下按名称排序的直接子目录。"""

    if not root_dir.is_dir():
        return ()
    return tuple(sorted((path for path in root_dir.iterdir() if path.is_dir()), key=lambda item: item.name))


def _resolve_single_checkpoint_file(
    checkpoints_dir: Path,
    *,
    warnings: list[str],
) -> Path | None:
    """返回一个 variant 目录中唯一可用的 checkpoint 文件。"""

    if not checkpoints_dir.is_dir():
        return None
    checkpoint_files = tuple(
        sorted(
            (
                path
                for path in checkpoints_dir.iterdir()
                if path.is_file() and path.name != ".gitkeep" and path.suffix.lower() == ".pt"
            ),
            key=lambda item: item.name,
        )
    )
    if not checkpoint_files:
        return None
    if len(checkpoint_files) > 1:
        warnings.append(
            "checkpoint 目录内存在多个 .pt 文件，当前只使用第一个："
            f"{checkpoints_dir.as_posix()}"
        )
    return checkpoint_files[0]


def _write_manifest_file(manifest_path: Path, payload: dict[str, object]) -> None:
    """把 manifest payload 写回磁盘。"""

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
