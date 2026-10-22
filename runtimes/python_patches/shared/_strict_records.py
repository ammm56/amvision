"""NumPy 类型化记录读写检查；由构建器放入两个独立的受控 wheel。"""

from decimal import Decimal, InvalidOperation

import numpy as np


def positive(value, name):
    """检查调用方提供的容量，不设置生产默认值。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def check_cancel(cancel):
    """取消由调用方回调抛出异常，不转成部分成功。"""
    if cancel is not None:
        cancel()


def read_line(fp, remaining, stage):
    """限制单行读取量，缺少换行的超长输入不能无限增长。"""
    line = fp.readline(remaining + 1)
    if len(line) > remaining:
        raise ValueError(f"{stage}: byte budget exceeded at offset {fp.tell()}")
    if not line:
        raise ValueError(f"{stage}: unexpected EOF at offset {fp.tell()}")
    return line


def exact_read(fp, size):
    """本地可寻址二进制文件必须完整读到声明长度。"""
    data = fp.read(size)
    if len(data) != size:
        raise ValueError(f"body: expected {size} bytes, got {len(data)}")
    return data


def remaining_bytes(fp):
    """保存当前位置后测量文件剩余长度，不消费正文。"""
    offset = fp.tell()
    end = fp.seek(0, 2)
    fp.seek(offset)
    return end - offset


def require_eof(fp):
    """包括空白在内的尾随字节均不是声明的记录。"""
    if fp.read(1):
        raise ValueError(f"body: trailing data at offset {fp.tell() - 1}")


def ascii_records(fp, count, dtype, *, chunk_rows, chunk_bytes, cancel=None):
    """沿 NumPy loadtxt 解码有界块，保留整数精度并检查浮点范围。"""
    positive(chunk_rows, "chunk_rows")
    positive(chunk_bytes, "chunk_bytes")
    names = dtype.names
    start = 0
    while start < count:
        check_cancel(cancel)
        lines = []
        used = 0
        while len(lines) < min(chunk_rows, count - start):
            offset = fp.tell()
            line = read_line(fp, chunk_bytes, f"body row {start + len(lines) + 1}")
            if not line.strip():
                raise ValueError(f"body: empty row {start + len(lines) + 1}")
            if used + len(line) > chunk_bytes:
                fp.seek(offset)
                break
            used += len(line)
            lines.append(line)
        try:
            result = np.loadtxt(lines, dtype=dtype, comments=None, ndmin=1)
        except (ValueError, OverflowError) as exc:
            raise ValueError(
                f"body rows {start + 1}..{start + len(lines)}: {exc}"
            ) from exc
        if len(result) != len(lines):
            raise ValueError(f"body row count mismatch at row {start + 1}")
        for column, name in enumerate(names):
            if dtype[name].kind != "f":
                continue
            source = result[name]
            # NumPy 会把 1e999 读成 inf、1e-999 读成 0；仅检查这些特殊结果。
            for index in np.flatnonzero(~np.isfinite(source) | (source == 0)):
                token = lines[int(index)].split()[column].decode("ascii")
                try:
                    number = Decimal(token)
                except InvalidOperation as exc:
                    raise ValueError(
                        f"body row {start + int(index) + 1} field {name}: invalid float"
                    ) from exc
                if number.is_finite() and (
                    not np.isfinite(source[index])
                    or (number != 0 and source[index] == 0)
                ):
                    raise ValueError(
                        f"body row {start + int(index) + 1} field {name}: float range exceeded"
                    )
        yield start, result
        start += len(lines)


class CheckedWriter:
    """短写立即失败；文件所有权仍属于调用方。"""

    def __init__(self, fp):
        self.fp = fp

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("ascii")
        if self.fp.write(data) != len(data):
            raise OSError("write: short write")
        return len(data)


def write_records(fp, data, *, ascii, chunk_rows, cancel=None):
    """按声明 dtype 分块写出，ASCII 整数不经过浮点中转。"""
    positive(chunk_rows, "chunk_rows")
    writer = CheckedWriter(fp)
    formats = [
        ("%.9g" if data.dtype[name].itemsize == 4 else "%.17g")
        if data.dtype[name].kind == "f"
        else "%d"
        for name in data.dtype.names
    ]
    for start in range(0, len(data), chunk_rows):
        check_cancel(cancel)
        block = data[start : start + chunk_rows]
        if ascii:
            np.savetxt(writer, block, fmt=formats)
        else:
            writer.write(block.tobytes())
