"""读取有界 PLY 顶点并为数据集查看器生成抽样点和正交缩略图。"""

from pathlib import Path

import numpy as np
from PIL import Image

from backend.service.infrastructure.controlled_dependencies import (
    require_controlled_distribution,
)


def read_vertices(path: Path):
    """复用受控 PLY 解析器，完整验证单一 vertex 元素后返回原精度字段。"""
    require_controlled_distribution("trimesh", "5.1.1+amvision.2")
    from trimesh.exchange.ply import read_ply_data, read_ply_header

    with path.open("rb") as stream:
        header = read_ply_header(stream, max_header_bytes=512 * 2048)
        if len(header.elements) != 1 or header.elements[0].name != "vertex":
            raise ValueError("点云 PLY 只支持单一 vertex 元素，不接受面或其他元素")
        vertex = header.elements[0]
        if not 1 <= vertex.count <= 2_000_000:
            raise ValueError("PLY 顶点数须为 1 至 200 万")
        if len(vertex.properties) > 32 or any(
            p.count_dtype is not None for p in vertex.properties
        ):
            raise ValueError("PLY 顶点仅支持至多 32 个标量属性")
        if not {"x", "y", "z"}.issubset(p.name for p in vertex.properties):
            raise ValueError("PLY 缺少 XYZ 坐标")
        return read_ply_data(
            stream,
            header,
            max_decoded_bytes=128 * 1024**2,
            chunk_rows=65536,
            chunk_bytes=1024**2,
        )


def make_cloud_preview(path: Path, preview: Path, points: Path) -> dict:
    """保留原始计数与范围，浏览器只接收至多 50000 个居中的 XYZ/RGB 样点。"""
    data = read_vertices(path)
    xyz = np.column_stack([data[k] for k in ("x", "y", "z")]).astype(np.float64)
    valid = np.flatnonzero(np.isfinite(xyz).all(axis=1))
    rgb_fields = ("red", "green", "blue")
    has_color = all(k in data.dtype.names for k in rgb_fields)
    if not has_color and any(k in data.dtype.names for k in rgb_fields):
        raise ValueError("PLY 颜色必须同时提供 red、green 和 blue")
    if has_color:
        for field in rgb_fields:
            values = data[field]
            if not np.isfinite(values).all() or values.min() < 0 or values.max() > 255:
                raise ValueError("PLY RGB 数值应在 0 至 255 之间")
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
