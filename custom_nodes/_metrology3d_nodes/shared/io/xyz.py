"""XYZ 系列的 NumPy 文本读取；有界行块，不自写格式或数值解析器。"""

from __future__ import annotations

from decimal import Decimal
from typing import BinaryIO, Callable, Iterator

import numpy as np

from backend.contracts.workflows.point_cloud import CloudFileOptions
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy


def line_blocks(
    stream: BinaryIO,
    policy: PointCloudIoPolicy,
    cancel: Callable[[], None],
) -> Iterator[tuple[int, list[bytes]]]:
    """只做行边界/ASCII 保护；行号包括空行，不忽略坏行或注释。"""
    lines: list[bytes] = []
    used = 0
    row = 0
    first = 1
    while True:
        cancel()
        line = stream.readline(policy.chunk_bytes + 1)
        if not line:
            break
        row += 1
        if len(line) > policy.chunk_bytes:
            raise ValueError(f"XYZ row {row}: line exceeds chunk_bytes")
        line.decode("ascii")
        body = line[:-1] if line.endswith(b"\n") else line
        if line.endswith(b"\r\n"):
            body = body[:-1]
        if any(value < 32 and value != 9 for value in body):
            raise ValueError(f"XYZ row {row}: invalid whitespace")
        if not line.strip(b" \t\r\n"):
            continue
        if lines and (
            used + len(line) > policy.chunk_bytes or len(lines) >= policy.chunk_rows
        ):
            yield first, lines
            lines = []
            used = 0
        if not lines:
            first = row
        lines.append(line)
        used += len(line)
    if lines:
        yield first, lines


def inspect_xyz(
    stream: BinaryIO,
    options: CloudFileOptions,
    policy: PointCloudIoPolicy,
    cancel: Callable[[], None],
) -> tuple[int, np.dtype]:
    """预扫描行数以准确分配；数值及列数由 loadtxt 在正文阶段验证。"""
    count = 0
    dtype = np.dtype(
        [
            (name, field.dtype)
            for field in options.field_mapping
            for name in field.source_names
        ]
    )
    start = stream.tell()
    for _row, lines in line_blocks(stream, policy, cancel):
        count += len(lines)
        if count * dtype.itemsize > policy.max_decoded_bytes:
            raise ValueError("XYZ decoded array exceeds max_decoded_bytes")
    stream.seek(start)
    return count, dtype


def read_xyz(
    stream: BinaryIO,
    count: int,
    dtype: np.dtype,
    policy: PointCloudIoPolicy,
    cancel: Callable[[], None],
) -> np.ndarray:
    """每块由 NumPy 解码；浮点特殊值与有限数越界分别检查。"""
    if count * dtype.itemsize > policy.max_decoded_bytes:
        raise ValueError("XYZ decoded array exceeds max_decoded_bytes")
    result = np.empty(count, dtype=dtype)
    offset = 0
    names = dtype.names
    for row, lines in line_blocks(stream, policy, cancel):
        block = np.loadtxt(
            lines,
            dtype=np.float64,
            comments=None,
            delimiter=None,
            quotechar=None,
            usecols=None,
            ndmin=2,
        )
        if block.shape != (len(lines), len(names)) or offset + len(lines) > count:
            raise ValueError(f"XYZ row {row}: unexpected columns or records")
        for column, name in enumerate(names):
            values = block[:, column]
            target = dtype[name]
            if target.kind == "u":
                if np.any(
                    ~np.isfinite(values)
                    | (values != np.floor(values))
                    | (values < 0)
                    | (values > 255)
                ):
                    raise ValueError(f"XYZ row {row} field {name}: invalid RGB")
            else:
                # Decimal 只区分 NumPy 已返回的 0/Inf 与文本的真实非有限值。
                for index in np.flatnonzero(~np.isfinite(values) | (values == 0)):
                    token = lines[int(index)].split()[column].decode("ascii")
                    number = Decimal(token)
                    if number.is_finite() and (
                        not np.isfinite(values[index])
                        or (number != 0 and values[index] == 0)
                    ):
                        raise ValueError(
                            f"XYZ row {row} field {name}: float range exceeded"
                        )
                if np.any(
                    np.isfinite(values) & (np.abs(values) > np.finfo(target).max)
                ):
                    raise ValueError(
                        f"XYZ row {row} field {name}: target dtype overflow"
                    )
            with np.errstate(under="ignore"):
                converted = values.astype(target)
            if target.kind == "f" and np.any(
                (values != 0) & np.isfinite(values) & (converted == 0)
            ):
                raise ValueError(f"XYZ row {row} field {name}: target dtype underflow")
            result[name][offset : offset + len(lines)] = converted
        offset += len(lines)
    if offset != count:
        raise ValueError("XYZ record count changed during read")
    cancel()
    return result
