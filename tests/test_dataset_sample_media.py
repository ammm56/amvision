"""专用数据集 ZIP 的输入边界、深度单位、附件归属及 PLY 预览回归。"""

import json
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.service.application.datasets.imports.contracts import DatasetImportRequest
from backend.service.application.datasets.imports.formats.sample_media import (
    asset_path,
    parse_sample_media,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.datasets.imports.formats.media_cloud import (
    read_vertices,
)


def parse(root: Path, kind: str, **entry):
    """写入实际清单，经正式解析器生成归一化样本。"""
    manifest = {
        "format_id": "amvision.sample-media.v1",
        "task_type": kind,
        "samples": [{"id": "part-1", "split": "test", **entry}],
    }
    (root / "samples.json").write_text(json.dumps(manifest), encoding="utf-8")
    request = DatasetImportRequest("project", "parts", "parts.zip", kind)
    return parse_sample_media(root, request).samples[0]


def test_anomaly_mask_preserves_original_bytes_and_optional_region(tmp_path):
    Image.new("RGB", (3, 2)).save(tmp_path / "part.png")
    mask = np.array([[0, 1, 0], [0, 0, 0]], np.uint8)
    Image.fromarray(mask).save(tmp_path / "label.png")
    item = parse(tmp_path, "anomaly", image="part.png", label="anomaly")
    assert item.sample.metadata["sample_media"]["assets"] == []
    item = parse(
        tmp_path, "anomaly", image="part.png", label="anomaly", mask="label.png"
    )
    assert (
        asset_path(item.source_image_path, "mask").read_bytes()
        == (tmp_path / "label.png").read_bytes()
    )
    with Image.open(asset_path(item.source_image_path, "mask-preview")) as im:
        assert np.array_equal(np.asarray(im)[:, :, 3] != 0, mask != 0)
    with pytest.raises(InvalidRequestError):
        parse(tmp_path, "anomaly", image="part.png", label="normal", mask="label.png")


def test_rgbd_keeps_native_resolution_and_invalid_values(tmp_path):
    Image.new("RGB", (9, 6)).save(tmp_path / "rgb.png")
    raw = np.array([[0, 250], [300, 450]], np.uint16)
    Image.fromarray(raw).save(tmp_path / "depth.png")
    item = parse(
        tmp_path,
        "rgbd",
        image="rgb.png",
        depth="depth.png",
        unit="m",
        scale=0.001,
        invalid=0,
    )
    m = item.sample.metadata["sample_media"]
    assert (item.sample.width, item.sample.height) == (9, 6)
    assert m["depth_size"] == [2, 2] and m["depth_range"] == [0.25, 0.45]
    assert m["valid_count"] == 3 and m["alignment"] == "unknown"
    assert np.array_equal(
        np.fromfile(asset_path(item.source_image_path, "depth-values"), "<u2"),
        raw.ravel(),
    )
    with Image.open(asset_path(item.source_image_path, "depth-preview")) as im:
        assert im.getpixel((0, 0)) == (0, 0, 0)


def test_cloud_retains_invalid_counts_and_source(tmp_path):
    contents = b"ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 1 2\n1 3 4\nnan 0 0\n"
    (tmp_path / "a.ply").write_bytes(contents)
    item = parse(tmp_path, "point-cloud", cloud="a.ply", unit="mm", frame="sensor")
    m = item.sample.metadata["sample_media"]
    assert (m["point_count"], m["preview_count"], m["invalid_count"]) == (3, 2, 1)
    assert m["z_range"] == [2, 4]
    assert asset_path(item.source_image_path, "cloud").read_bytes() == contents
    assert asset_path(item.source_image_path, "points").stat().st_size == 48


@pytest.mark.parametrize(
    "kind,row",
    [
        ("anomaly", dict(image="../outside.png", label="normal")),
        (
            "rgbd",
            dict(image="part.png", depth="part.png", unit="mm", scale=1, invalid=0),
        ),
        (
            "rgbd",
            dict(
                image="part.png",
                depth="missing.png",
                unit="mm",
                scale=1,
                invalid=0,
                alignment="registered",
            ),
        ),
        (
            "connector-reference",
            dict(
                image="part.png",
                synthetic=True,
                unit="mm",
                pins=[{"id": "P1", "x": 9, "y": 1}],
            ),
        ),
        (
            "connector-reference",
            dict(
                image="part.png",
                synthetic=True,
                unit="mm",
                measured=[{"name": "pitch", "value": 2.5, "unit": "mm"}],
            ),
        ),
        ("point-cloud", dict(cloud="part.png", unit="mm", frame="scanner")),
    ],
)
def test_rejects_invalid_reference_without_fabricating_data(tmp_path, kind, row):
    Image.new("RGB", (2, 2)).save(tmp_path / "part.png")
    with pytest.raises(InvalidRequestError):
        parse(tmp_path, kind, **row)


def ply_bytes(body=b"1 2 3\n", *, encoding="ascii", count=1, extra=""):
    """构造独立字节真值，不使用被测 writer。"""
    return (
        f"ply\nformat {encoding} 1.0\nelement vertex {count}\n"
        "property float x\nproperty float y\nproperty float z\n"
        f"{extra}end_header\n"
    ).encode() + body


@pytest.mark.parametrize(
    "contents",
    [
        ply_bytes(b""),
        ply_bytes(b"1 2\n"),
        ply_bytes(b"1 2 3\n", count=2),
        ply_bytes(b"1 2 3\n4 5 6\n"),
        ply_bytes(b"1 2 3 4\n"),
        ply_bytes(b"1oops 2 3\n"),
        ply_bytes(b"1e39 2 3\n"),
        ply_bytes(extra="element face 1\nproperty list uchar int vertex_indices\n"),
        ply_bytes(extra="property float x\n"),
        ply_bytes(extra="property list uchar float values\n"),
        ply_bytes(b"1 2 3 256\n", extra="property uchar intensity\n"),
        ply_bytes(b"1 2 3 -1\n", extra="property uchar intensity\n"),
        ply_bytes(b"1 2 3 1.1\n", extra="property uchar intensity\n"),
        ply_bytes(struct.pack("<fff", 1, 2, 3)[:-1], encoding="binary_little_endian"),
        ply_bytes(struct.pack(">fff", 1, 2, 3) + b"x", encoding="binary_big_endian"),
    ],
)
def test_cloud_strict_import_rejects_malformed_content(tmp_path, contents):
    """正式清单入口不得把截断、冗余记录、坏字段标记为导入成功。"""
    (tmp_path / "a.ply").write_bytes(contents)
    with pytest.raises(InvalidRequestError):
        parse(tmp_path, "point-cloud", cloud="a.ply", unit="mm", frame="sensor")


@pytest.mark.parametrize(
    "encoding,endian",
    [("ascii", "<"), ("binary_little_endian", "<"), ("binary_big_endian", ">")],
)
def test_cloud_strict_reader_preserves_all_fields(tmp_path, encoding, endian):
    """全字段保留声明精度；原始附件逐字节保持不变。"""
    value = np.nextafter(1.0, 2.0)
    header = (
        f"ply\nformat {encoding} 1.0\nelement vertex 1\n"
        "property double x\nproperty float y\nproperty float z\nproperty uint64 source\nend_header\n"
    ).encode()
    body = (
        b"1.0000000000000002 2 3 18446744073709551615\n"
        if encoding == "ascii"
        else struct.pack(endian + "dffQ", value, 2, 3, 2**64 - 1)
    )
    path = tmp_path / "a.ply"
    path.write_bytes(header + body)
    data = read_vertices(path)
    assert data.dtype.names == ("x", "y", "z", "source")
    assert data.dtype["x"].itemsize == 8 and data.dtype["y"].itemsize == 4
    assert data["x"][0] == value and int(data["source"][0]) == 2**64 - 1
    item = parse(tmp_path, "point-cloud", cloud="a.ply", unit="mm", frame="sensor")
    assert asset_path(item.source_image_path, "cloud").read_bytes() == header + body


def test_cloud_dependency_mismatch_is_configuration_error(tmp_path, monkeypatch):
    """依赖错配不伪装为坏文件，也不退回自建解析器。"""
    from backend.service.infrastructure import controlled_dependencies

    monkeypatch.setattr(controlled_dependencies, "version", lambda _: "5.1.1")
    (tmp_path / "a.ply").write_bytes(ply_bytes())
    with pytest.raises(ServiceConfigurationError):
        parse(tmp_path, "point-cloud", cloud="a.ply", unit="mm", frame="sensor")


def test_cloud_invalid_coordinate_does_not_hide_bad_rgb(tmp_path):
    """无效 XYZ 被显示过滤前仍须验证所有源字段。"""
    (tmp_path / "a.ply").write_bytes(
        ply_bytes(
            b"nan 2 3 256 0 0\n",
            extra="property float red\nproperty float green\nproperty float blue\n",
        )
    )
    with pytest.raises(InvalidRequestError, match="RGB"):
        parse(tmp_path, "point-cloud", cloud="a.ply", unit="mm", frame="sensor")
