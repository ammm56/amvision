"""调用时扫描目录，以有界 Top-K 选取文件，不保存跨运行状态。"""

from __future__ import annotations

import fnmatch
import heapq
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from backend.nodes.core_nodes.support.local_io.files import build_directory_file_record
from backend.service.application.errors import InvalidRequestError


def iter_directory_files(
    *,
    directory_path: Path,
    recursive: bool,
    include_hidden: bool,
    glob_pattern: str,
    extensions: tuple[str, ...],
    check: Callable[[], None] | None = None,
) -> Iterator[Path]:
    """普通文件名模式流式遍历；保留 Directory Scan 的相对路径 Glob 能力。"""
    if Path(glob_pattern).is_absolute() or ".." in glob_pattern.replace(
        "\\", "/"
    ).split("/"):
        raise InvalidRequestError("glob_pattern 必须位于指定目录内")
    if "/" in glob_pattern or "\\" in glob_pattern or "**" in glob_pattern:
        paths = (
            directory_path.rglob(glob_pattern)
            if recursive
            else directory_path.glob(glob_pattern)
        )
        for path in paths:
            if check is not None:
                check()
            relative = path.relative_to(directory_path)
            if not include_hidden and any(
                part.startswith(".") for part in relative.parts
            ):
                continue
            if any(
                parent.is_symlink() or parent.is_junction()
                for parent in [path, *path.parents]
                if parent != directory_path and directory_path in parent.parents
            ):
                continue
            if path.is_file() and (not extensions or path.suffix.lower() in extensions):
                yield path
        return
    yield from _walk(
        directory_path, recursive, include_hidden, glob_pattern, extensions, check
    )


def _walk(
    directory: Path,
    recursive: bool,
    include_hidden: bool,
    pattern: str,
    extensions: tuple[str, ...],
    check: Callable[[], None] | None,
) -> Iterator[Path]:
    """每层只保留一个 scandir 句柄，不收集整目录路径，不遍历链接目录。"""
    with os.scandir(directory) as entries:
        for entry in entries:
            if check is not None:
                check()
            if not include_hidden and entry.name.startswith("."):
                continue
            path = Path(entry.path)
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if path.is_junction():
                    continue
                if recursive:
                    try:
                        yield from _walk(
                            path, recursive, include_hidden, pattern, extensions, check
                        )
                    except FileNotFoundError:
                        # 扫描期间消失的子目录不构成可读取文件。
                        continue
                continue
            if (
                entry.is_file(follow_symlinks=False)
                and fnmatch.fnmatch(entry.name, pattern)
                and (not extensions or path.suffix.lower() in extensions)
            ):
                yield path


def select_directory_records(
    paths: Iterator[Path],
    *,
    sort_by: str,
    descending: bool,
    limit: int | None,
    min_stable_age_seconds: float,
    current_time_seconds: float,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """完整检查候选，数量受限时仅保留 K 条；同时间用规范路径确定顺序。"""
    counts = {"raw_count": 0, "unstable_skipped_count": 0, "missing_skipped_count": 0}
    cutoff_ns = int((current_time_seconds - min_stable_age_seconds) * 1_000_000_000)

    def records() -> Iterator[dict[str, object]]:
        """惰性产生记录，使 Top-K 不依赖整目录大小。"""
        for path in paths:
            try:
                record = build_directory_file_record(path)
            except FileNotFoundError:
                counts["missing_skipped_count"] += 1
                continue
            counts["raw_count"] += 1
            if (
                min_stable_age_seconds > 0
                and int(record["modified_time_epoch_ns"]) > cutoff_ns
            ):
                counts["unstable_skipped_count"] += 1
                continue
            yield record

    def key(record: dict[str, object]) -> tuple:
        """保持 Directory Scan 的倒序定义；时间精度使用纳秒。"""
        path = str(record["path"])
        name_key = (os.path.normcase(path), path)
        return (
            (int(record["modified_time_epoch_ns"]), *name_key)
            if sort_by == "modified_time"
            else name_key
        )

    try:
        if limit is None:
            selected = sorted(records(), key=key, reverse=descending)
        else:
            select = heapq.nlargest if descending else heapq.nsmallest
            selected = select(limit, records(), key=key)
    except OSError as exc:
        raise InvalidRequestError(
            "目录扫描失败", details={"error_code": "local_directory_scan_failed"}
        ) from exc
    finally:
        close = getattr(paths, "close", None)
        if close is not None:
            close()
    return selected, counts
