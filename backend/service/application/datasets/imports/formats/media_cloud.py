"""读取有界 PLY 顶点并为数据集查看器生成抽样点和正交缩略图。"""

from pathlib import Path

import numpy as np
from PIL import Image

_TYPES = {
    "char": "i1",
    "uchar": "u1",
    "short": "i2",
    "ushort": "u2",
    "int": "i4",
    "uint": "u4",
    "float": "f4",
    "double": "f8",
    "int8": "i1",
    "uint8": "u1",
    "int16": "i2",
    "uint16": "u2",
    "int32": "i4",
    "uint32": "u4",
    "float32": "f4",
    "float64": "f8",
}


def read_vertices(path: Path):
    """仅解析第一个 vertex 元素，忽略后续面；不加载任意 PLY 扩展代码。"""
    with path.open("rb") as stream:
        if stream.readline(16).strip() != b"ply":
            raise ValueError("点云必须是 PLY 文件")
        encoding = ""
        element = ""
        count = 0
        fields = []
        for _ in range(512):
            line = stream.readline(2048)
            if not line or len(line) >= 2048:
                raise ValueError("PLY 头部无效")
            parts = line.decode("ascii").split()
            if not parts or parts[0] in {"comment", "obj_info"}:
                continue
            if parts == ["end_header"]:
                break
            if parts[0] == "format" and len(parts) == 3 and parts[2] == "1.0":
                encoding = parts[1]
            elif parts[0] == "element" and len(parts) == 3:
                element = parts[1]
                if not count:
                    if element != "vertex" or not 1 <= int(parts[2]) <= 2_000_000:
                        raise ValueError("PLY 首元素须为 1 至 200 万个顶点")
                    count = int(parts[2])
                elif element == "vertex":
                    raise ValueError("PLY vertex 定义重复")
            elif parts[0] == "property" and element == "vertex":
                if len(parts) != 3 or parts[1] not in _TYPES or len(fields) >= 32:
                    raise ValueError("PLY 顶点仅支持标量属性")
                fields.append((parts[2], _TYPES[parts[1]]))
        else:
            raise ValueError("PLY 头部过长")
        dtype = np.dtype(fields)
        if not count or not {"x", "y", "z"}.issubset(dtype.names or ()):
            raise ValueError("PLY 缺少 XYZ 坐标")
        if dtype.itemsize * count > 128 * 1024**2:
            raise ValueError("点云顶点数据超过 128 MiB")
        if encoding == "ascii":

            def rows():
                for _ in range(count):
                    line = stream.readline(2048)
                    if not line.strip() or len(line) >= 2048:
                        raise ValueError("PLY 顶点行无效")
                    yield line

            data = np.loadtxt(rows(), dtype=dtype, ndmin=1, comments=None)
        elif encoding in {"binary_little_endian", "binary_big_endian"}:
            endian = "<" if encoding == "binary_little_endian" else ">"
            data = np.fromfile(stream, dtype=dtype.newbyteorder(endian), count=count)
        else:
            raise ValueError("不支持的 PLY 编码")
        if len(data) != count:
            raise ValueError("PLY 顶点数量与头部不符")
    return data


def make_cloud_preview(path: Path, preview: Path, points: Path) -> dict:
    """保留原始计数与范围，浏览器只接收至多 50000 个居中的 XYZ/RGB 样点。"""
    data = read_vertices(path)
    xyz = np.column_stack([data[k] for k in ("x", "y", "z")]).astype(np.float64)
    valid = np.flatnonzero(np.isfinite(xyz).all(axis=1))
    rgb_fields = ("red", "green", "blue")
    has_color = all(k in data.dtype.names for k in rgb_fields)
    if not has_color and any(k in data.dtype.names for k in rgb_fields):
        raise ValueError("PLY 颜色必须同时提供 red、green 和 blue")
    meta = {
        "point_count": len(data),
        "valid_count": len(valid),
        "invalid_count": len(data) - len(valid),
        "has_color": has_color,
    }
    image = Image.new("RGB", (480, 360), (43, 47, 51))
    if len(valid):
        full = xyz[valid]
        low, high = full.min(axis=0), full.max(axis=0)
        origin = low / 2 + high / 2
        scale = float((high / 2 - low / 2).max()) or 1.0
        ids = valid[np.linspace(0, len(valid) - 1, min(50000, len(valid)), dtype=int)]
        pos = (xyz[ids] / scale - origin / scale).astype("<f4")
        if not np.isfinite(pos).all():
            raise ValueError("点云坐标超出显示精度范围")
        colors = (
            np.column_stack([data[k][ids] for k in rgb_fields])
            if has_color
            else np.full(pos.shape, 190)
        )
        if not np.isfinite(colors).all() or colors.min() < 0 or colors.max() > 255:
            raise ValueError("PLY RGB 数值应在 0 至 255 之间")
        np.concatenate((pos, colors / 255), axis=1).astype("<f4").tofile(points)
        pixels = np.array(image)
        x = np.clip(240 + 135 * (pos[:, 0] - 0.45 * pos[:, 1]), 0, 479).astype(int)
        y = np.clip(180 - 105 * (pos[:, 2] + 0.35 * pos[:, 1]), 0, 359).astype(int)
        pixels[y, x] = colors.astype(np.uint8)
        image = Image.fromarray(pixels)
        meta.update(
            z_range=[float(low[2]), float(high[2])],
            origin=origin.tolist(),
            scale=scale,
            preview_count=len(ids),
        )
    else:
        points.write_bytes(b"")
        meta["preview_count"] = 0
    image.save(preview, format="PNG")
    return meta
