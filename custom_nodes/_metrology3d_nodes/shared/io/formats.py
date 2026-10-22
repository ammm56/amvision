"""调用已冻结的受控公开 I/O；格式不匹配或依赖错误不换库重试。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from typing import BinaryIO, Callable

import numpy as np

from backend.contracts.workflows.point_cloud import CloudFileOptions, PcdSourceMetadata
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy
from custom_nodes._metrology3d_nodes.shared.io.xyz import inspect_xyz, read_xyz


@dataclass(frozen=True)
class InspectedCloudFile:
    """成熟解析器返回的源布局和正文读取器；不含未验证的成功点云。"""

    count: int
    dtype: np.dtype
    source_metadata: PcdSourceMetadata | None
    read: Callable[[], np.ndarray]


def require_controlled_distribution(name: str, expected: str) -> None:
    """只接受本项目锁定的修复发行版本。"""
    if version(name) != expected:
        raise RuntimeError(f"{name} requires controlled version {expected}")


def inspect_cloud_file(
    stream: BinaryIO,
    options: CloudFileOptions,
    policy: PointCloudIoPolicy,
    cancel: Callable[[], None],
) -> InspectedCloudFile:
    """由显式 profile 选择唯一读取器，不根据扩展名猜测。"""
    cancel()
    if options.profile_id.startswith("ply-"):
        require_controlled_distribution("trimesh", "5.1.1+amvision.1")
        from trimesh.exchange.ply import read_ply_data, read_ply_header

        header = read_ply_header(stream, max_header_bytes=policy.max_header_bytes)
        encoding = {
            "ply-ascii": "ascii",
            "ply-binary-le": "binary_little_endian",
            "ply-binary-be": "binary_big_endian",
        }[options.profile_id]
        if header.encoding != encoding:
            raise ValueError("PLY encoding does not match profile")
        if len(header.elements) != 1 or header.elements[0].name != "vertex":
            raise ValueError("PLY point profile cannot omit other elements")
        vertex = header.elements[0]
        if any(prop.count_dtype is not None for prop in vertex.properties):
            raise ValueError("PLY point profile does not accept list fields")
        dtype = np.dtype([(prop.name, prop.dtype) for prop in vertex.properties])
        return InspectedCloudFile(
            vertex.count,
            dtype,
            None,
            lambda: read_ply_data(
                stream,
                header,
                max_decoded_bytes=policy.max_decoded_bytes,
                chunk_rows=policy.chunk_rows,
                chunk_bytes=policy.chunk_bytes,
                cancel=cancel,
            ),
        )
    if options.profile_id.startswith("pcd-"):
        require_controlled_distribution("pypcd4", "1.5.1+amvision.2")
        from pypcd4.pypcd4 import read_pcd_data, read_pcd_header

        metadata, _offset = read_pcd_header(
            stream, max_header_bytes=policy.max_header_bytes
        )
        encoding = {
            "pcd-ascii": "ascii",
            "pcd-binary": "binary",
            "pcd-binary-compressed": "binary_compressed",
        }[options.profile_id]
        if metadata.data.value != encoding:
            raise ValueError("PCD encoding does not match profile")
        source = (
            None
            if metadata.points == 0
            else PcdSourceMetadata(
                format="pcd",
                width=metadata.width,
                height=metadata.height,
                organized=metadata.height > 1,
                viewpoint=metadata.viewpoint,
                source_spatial=options.spatial,
            )
        )
        return InspectedCloudFile(
            metadata.points,
            metadata.build_dtype(),
            source,
            lambda: read_pcd_data(
                stream,
                metadata,
                max_decoded_bytes=policy.max_decoded_bytes,
                max_working_bytes=policy.max_working_bytes,
                chunk_rows=policy.chunk_rows,
                chunk_bytes=policy.chunk_bytes,
                cancel=cancel,
            ),
        )
    count, dtype = inspect_xyz(stream, options, policy, cancel)
    return InspectedCloudFile(
        count, dtype, None, lambda: read_xyz(stream, count, dtype, policy, cancel)
    )
