"""完整样本的共享读取与身份，不通过发布/API 测试模块加载格式适配器。"""

from hashlib import file_digest, sha256

import numpy as np

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from tests.test_point_cloud_trigger import descriptor

FILE_SHA = "ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b"
ARRAY_SHA = "956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6"
POINTS = 14_745_099


def sample_array(sample, destination):
    """用受控 parser 读取完整原始样本，不自行解码、不只取样本前缀。"""
    from trimesh.exchange.ply import read_ply_header, read_ply_data

    with sample.open("rb") as stream:
        assert file_digest(stream, "sha256").hexdigest() == FILE_SHA
        stream.seek(0)
        header = read_ply_header(stream, max_header_bytes=65536)
        data = read_ply_data(
            stream,
            header,
            max_decoded_bytes=400000000,
            chunk_rows=65536,
            chunk_bytes=4194304,
        )
    assert len(data) == POINTS and data.dtype.names == ("x", "y", "z")
    digest = sha256()
    with destination.open("wb") as stream:
        for start in range(0, POINTS, 65536):
            block = np.column_stack(
                [data[key][start : start + 65536] for key in data.dtype.names]
            )
            assert block.dtype == np.dtype("<f4")
            with memoryview(block).cast("B") as view:
                digest.update(view)
                stream.write(view)
    assert digest.hexdigest() == ARRAY_SHA
    cloud = descriptor().model_dump(mode="json")
    cloud.update(point_count=POINTS, content_length=POINTS * 12)
    cloud["fields"][0].update(count=POINTS, byte_length=POINTS * 12)
    cloud["spatial"] = dict(
        length_unit=None,
        unit_source="unknown",
        frame_id="sample-source",
        axes=dict(
            handedness="unknown",
            axis_labels=["X", "Y", "Z"],
            definition_source="unknown",
        ),
    )
    return CloudBufferDescriptor.model_validate(cloud)
