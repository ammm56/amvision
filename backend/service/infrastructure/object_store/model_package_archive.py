"""流式模型包 ZIP 读写；不执行模型，不接受包中未声明的文件。"""

from __future__ import annotations

import hashlib
import json
import stat
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from backend.contracts.deployments.model_package import ModelDeploymentPackage, TransferLimits, safe_package_path


def file_digest(path: Path, progress: Callable[[int], None] | None = None) -> tuple[str, int]:
    """分块计算文件摘要，可用于进度、取消和占用续期。"""
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if progress:
                progress(len(chunk))
    return digest.hexdigest(), size


def write_package(path: Path, manifest: ModelDeploymentPackage, sources: Mapping[str, Path], progress: Callable[[int], None] | None = None) -> None:
    """写完并验证全部文件后公布 ZIP；失败只移除本次临时文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".writing")
    try:
        with ZipFile(staging, "w", compression=ZIP_STORED, allowZip64=True) as archive:
            archive.writestr("manifest.json", manifest.model_dump_json(indent=2))
            for item in manifest.files:
                digest, size = hashlib.sha256(), 0
                with sources[item.key].open("rb") as src, archive.open(f"files/{item.owner}/{item.path}", "w", force_zip64=True) as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        if progress:
                            progress(len(chunk))
                if (digest.hexdigest(), size) != (item.sha256, item.byte_size):
                    raise ValueError(f"导出期间文件已变化：{item.logical_name}")
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def read_package(path: Path, destination: Path, limits: TransferLimits | None = None, progress: Callable[[int], None] | None = None) -> ModelDeploymentPackage:
    """严格核对归档清单，再逐文件写入调用者专属空暂存目录。"""
    limits = limits or TransferLimits()
    if path.stat().st_size > limits.max_package_bytes:
        raise ValueError("部署包超过大小限制")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("解包目录必须为空")
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > limits.max_entries:
            raise ValueError("部署包文件数量超限")
        names = set()
        total = 0
        for entry in entries:
            safe_package_path(entry.filename)
            name = entry.filename.casefold()
            mode = entry.external_attr >> 16
            if name in names or entry.is_dir() or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or entry.flag_bits & 1:
                raise ValueError("部署包含重复路径、链接、目录或加密条目")
            names.add(name)
            total += entry.file_size
        if total > limits.max_unpacked_bytes:
            raise ValueError("部署包解压大小超限")
        if shutil.disk_usage(destination).free < total:
            raise ValueError("目标磁盘剩余空间不足以解压部署包")
        header = archive.getinfo("manifest.json")
        if header.file_size > limits.max_manifest_bytes:
            raise ValueError("部署包清单过大")
        def unique_keys(pairs):
            """拒绝歧义 JSON 重名字段。"""
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("JSON 字段重复")
                value[key] = item
            return value
        manifest = ModelDeploymentPackage.model_validate(json.loads(archive.read(header), object_pairs_hook=unique_keys))
        expected = {"manifest.json", *(f"files/{f.owner}/{f.path}" for f in manifest.files)}
        if {e.filename for e in entries} != expected:
            raise ValueError("部署包实际文件与清单不一致")
        for item in manifest.files:
            name = f"files/{item.owner}/{item.path}"
            if archive.getinfo(name).file_size != item.byte_size:
                raise ValueError(f"文件大小不匹配：{item.logical_name}")
            target = destination / item.owner / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, size = hashlib.sha256(), 0
            with archive.open(name) as src, target.open("xb") as dst:
                while chunk := src.read(1024 * 1024):
                    size += len(chunk)
                    if size > item.byte_size:
                        raise ValueError("解压文件超过声明大小")
                    digest.update(chunk)
                    dst.write(chunk)
                    if progress:
                        progress(len(chunk))
            if digest.hexdigest() != item.sha256:
                raise ValueError(f"文件摘要不匹配：{item.logical_name}")
        return manifest
