from __future__ import annotations

import re
import struct
from enum import Enum
from io import BufferedReader
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, List, Literal, Optional, Sequence, Tuple, Union, cast

import lzf
import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt, model_validator

from ._strict_records import (
    CheckedWriter, ascii_records, check_cancel, exact_read, positive,
    read_line, remaining_bytes, require_eof, write_records,
)

from .pointcloud2 import (
    NPTYPE_TO_PFTYPE,
    build_dtype_from_msg,
    sensor_msgs__msg__PointCloud2,
)

if TYPE_CHECKING:
    from sensor_msgs.msg import PointCloud2
    from std_msgs.msg import Header

PathLike = Union[str, Path]

MetaDataVersion = Literal[".7", "0.7"]
MetaDataViewPoint = Tuple[float, float, float, float, float, float, float]
DEFAULT_VIEWPOINT: MetaDataViewPoint = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)

NUMPY_TYPE_TO_PCD_TYPE: dict[
    npt.DTypeLike,
    Tuple[str, int],
] = {
    np.dtype("uint8"): ("U", 1),
    np.dtype("uint16"): ("U", 2),
    np.dtype("uint32"): ("U", 4),
    np.dtype("uint64"): ("U", 8),
    np.dtype("int8"): ("I", 1),
    np.dtype("int16"): ("I", 2),
    np.dtype("int32"): ("I", 4),
    np.dtype("int64"): ("I", 8),
    np.dtype("float32"): ("F", 4),
    np.dtype("float64"): ("F", 8),
}

PCD_TYPE_TO_NUMPY_TYPE: dict[
    Tuple[str, int],
    npt.DTypeLike,
] = {
    ("F", 4): np.float32,
    ("F", 8): np.float64,
    ("U", 1): np.uint8,
    ("U", 2): np.uint16,
    ("U", 4): np.uint32,
    ("U", 8): np.uint64,
    ("I", 1): np.int8,
    ("I", 2): np.int16,
    ("I", 4): np.int32,
    ("I", 8): np.int64,
}

HEADER_KEYS = ("version", "fields", "size", "type", "count", "width", "height", "viewpoint", "points", "data")


class Encoding(str, Enum):
    ASCII = "ascii"
    BINARY = "binary"
    BINARY_COMPRESSED = "binary_compressed"


class MetaData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fields: Tuple[str, ...]
    size: Tuple[PositiveInt, ...]
    type: Tuple[Literal["F", "U", "I"], ...]
    count: Tuple[PositiveInt, ...]
    points: NonNegativeInt
    width: NonNegativeInt
    height: NonNegativeInt = 1
    version: MetaDataVersion = "0.7"
    viewpoint: MetaDataViewPoint = DEFAULT_VIEWPOINT
    data: Encoding = Encoding.BINARY_COMPRESSED

    @model_validator(mode="after")
    def validate_layout(self):
        """解码前校验字段、组织结构与展开名称，不创建点数组。"""
        if not self.fields or not (len(self.fields) == len(self.size) == len(self.type) == len(self.count)):
            raise ValueError("header: FIELDS/SIZE/TYPE/COUNT length mismatch")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("header: duplicate FIELDS")
        for name in self.fields:
            if not name or not name.isascii() or any(c.isspace() for c in name):
                raise ValueError("header: invalid field name")
        if any((kind, size) not in PCD_TYPE_TO_NUMPY_TYPE for kind, size in zip(self.type, self.size)):
            raise ValueError("header: unsupported TYPE/SIZE")
        if self.points != self.width * self.height or self.height < 1:
            raise ValueError("header: POINTS must equal WIDTH * HEIGHT, HEIGHT must be positive")
        if not all(np.isfinite(value) for value in self.viewpoint) or not any(self.viewpoint[3:]):
            raise ValueError("header: invalid VIEWPOINT")
        counts = dict(zip(self.fields, self.count))
        for name in self.fields:
            match = re.fullmatch(r"(.+)__(\d{4,})", name)
            if match and match[1] in counts and counts[match[1]] > 1:
                index = int(match[2])
                if index < counts[match[1]] and name == f"{match[1]}__{index:04d}":
                    raise ValueError("header: flattened COUNT field collision")
        return self

    @property
    def record_bytes(self) -> int:
        """完整记录的字节数，用于 dtype 展开前容量检查。"""
        return sum(size * count for size, count in zip(self.size, self.count))

    @property
    def field_columns(self) -> Tuple[Tuple[str, ...], ...]:
        """原 FIELDS 到结构数组列的有序映射。"""
        return tuple((name,) if count == 1 else tuple(f"{name}__{i:04d}" for i in range(count))
                     for name, count in zip(self.fields, self.count))

    @staticmethod
    def parse_header(lines: List[str]) -> MetaData:
        """
        Parse a header in accordance with the PCD (Point Cloud Data) file format.
        See https://pointclouds.org/documentation/tutorials/pcd_file_format.html.

        Args:
            lines (List[str]): A list of lines of the header

        Raises:
            pydantic.ValidationError: If the header is invalid

        Returns:
            MetaData: Parsed MetaData object
        """

        _header = {}
        previous = -1
        for line in lines:
            if line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) < 2 or tokens[0] != tokens[0].upper():
                raise ValueError("header: malformed directive")
            key, value = tokens[0].lower(), tokens[1:]
            if key not in HEADER_KEYS or key in _header or HEADER_KEYS.index(key) <= previous:
                raise ValueError("header: unknown, duplicate or out-of-order directive")
            previous = HEADER_KEYS.index(key)
            if key in ("version", "data", "width", "height", "points") and len(value) != 1:
                raise ValueError("header: extra scalar tokens")
            if key in ["version", "data"]:
                _header[key] = value[0]
            elif key in ["width", "height", "points"]:
                if not value[0].isascii() or not value[0].isdecimal():
                    raise ValueError("header: invalid nonnegative integer")
                _header[key] = int(value[0])
            elif key in ["fields"]:
                _header[key] = tuple(value)
            elif key in ["type"]:
                _header[key] = tuple(value)
            elif key in ["size", "count"]:
                if any(not v.isascii() or not v.isdecimal() for v in value):
                    raise ValueError("header: invalid positive integer")
                _header[key] = tuple(int(v) for v in value)
            elif key in ["viewpoint"]:
                _header[key] = tuple(float(v) for v in value)
        required = set(HEADER_KEYS) - {"count", "viewpoint"}
        if not required <= _header.keys():
            raise ValueError("header: missing required directive")
        # PCD 0.7 明确定义 COUNT 和 VIEWPOINT 的省略值，不是失败降级。
        if "count" not in _header:
            _header["count"] = (1,) * len(_header["fields"])
        return _validate_metadata(_header)

    def compose_header(self, data: Optional[Encoding] = None) -> str:
        header: List[str] = []

        header.append(f"VERSION {self.version}")
        header.append(f"FIELDS {' '.join(self.fields)}")
        header.append(f"SIZE {' '.join([str(v) for v in self.size])}")
        header.append(f"TYPE {' '.join(self.type)}")
        header.append(f"COUNT {' '.join([str(v) for v in self.count])}")
        header.append(f"WIDTH {self.width}")
        header.append(f"HEIGHT {self.height}")
        header.append(f"VIEWPOINT {' '.join([str(v) for v in self.viewpoint])}")
        header.append(f"POINTS {self.points}")
        header.append(f"DATA {(data or self.data).value}")

        return "\n".join(header) + "\n"

    def build_dtype(self) -> np.dtype[np.void]:
        field_names: List[str] = []
        np_types: List[npt.DTypeLike] = []

        for i, field in enumerate(self.fields):
            np_type: npt.DTypeLike = np.dtype(PCD_TYPE_TO_NUMPY_TYPE[(self.type[i], self.size[i])]).newbyteorder("<")

            if (count := self.count[i]) == 1:
                field_names.append(field)
                np_types.append(np_type)
            else:
                field_names.extend([f"{field}__{i:04d}" for i in range(count)])
                np_types.extend([np_type] * count)

        return np.dtype([x for x in zip(field_names, np_types)])

    def derive(self, **overrides: object) -> MetaData:
        """Returns a copy of this MetaData with only the given fields overridden

        Every field not named in `overrides` is carried over unchanged from
        this instance, instead of falling back to MetaData's own defaults
        (which is what happens when building a MetaData from scratch, e.g.
        via `_validate_metadata`). Use this when deriving one PointCloud
        from another -- concatenating, filtering, selecting fields -- so
        metadata like `viewpoint` isn't silently lost in the process.
        """

        return MetaData.model_validate({**self.model_dump(), **overrides})


def _dtype_names(dtype: np.dtype) -> Tuple[str, ...]:
    # `dtype.names` is None for non-structured dtypes, but every dtype this
    # library builds (via MetaData.build_dtype() / build_dtype_from_msg())
    # is structured, so this always holds.
    assert dtype.names is not None
    return dtype.names


def _merge_viewpoints(viewpoints: Sequence[MetaDataViewPoint]) -> MetaDataViewPoint:
    # A combined point cloud only has one meaningful viewpoint if every
    # source agreed on it in the first place -- there's no way to average
    # or otherwise reconcile acquisition poses that actually differ.
    first, *rest = viewpoints
    if all(viewpoint == first for viewpoint in rest):
        return first

    return DEFAULT_VIEWPOINT


def _validate_metadata(data: dict) -> MetaData:
    return MetaData.model_validate(data)


def read_pcd_header(fp, *, max_header_bytes):
    """公开检查头部并返回正文偏移，尚不分配点数组。"""
    positive(max_header_bytes, "max_header_bytes")
    start = fp.tell()
    lines = []
    while True:
        remaining = max_header_bytes - (fp.tell() - start)
        if remaining <= 0:
            raise ValueError("header: byte budget exceeded")
        raw = read_line(fp, remaining, "header")
        if not raw.endswith(b"\n"):
            raise ValueError("header: unterminated line")
        line = raw.decode("ascii").strip()
        lines.append(line)
        if line.split()[:1] == ["DATA"]:
            return MetaData.parse_header(lines), fp.tell()


def read_pcd_data(fp, metadata, *, max_decoded_bytes, max_working_bytes, chunk_rows, chunk_bytes, cancel=None):
    """校验完整记录后解码，compressed 仍使用上游 LZF。"""
    for name, value in (("max_decoded_bytes", max_decoded_bytes), ("max_working_bytes", max_working_bytes),
                        ("chunk_rows", chunk_rows), ("chunk_bytes", chunk_bytes)):
        positive(value, name)
    size = metadata.points * metadata.record_bytes
    if size > max_decoded_bytes or metadata.record_bytes > chunk_bytes:
        raise ValueError("budget: decoded PCD or record exceeds capacity")
    if metadata.data == Encoding.BINARY and remaining_bytes(fp) != size:
        raise ValueError("body: binary PCD length mismatch")
    if metadata.data == Encoding.BINARY_COMPRESSED:
        compressed_size, uncompressed_size = struct.unpack("<II", exact_read(fp, 8))
        if uncompressed_size != size or remaining_bytes(fp) != compressed_size:
            raise ValueError("body: compressed PCD length mismatch")
        if 2 * size + compressed_size > max_working_bytes:
            raise ValueError("budget: compressed PCD working set exceeds capacity")
    check_cancel(cancel)
    dtype = metadata.build_dtype()
    pc_data = np.empty(metadata.points, dtype=dtype)
    if metadata.data == Encoding.ASCII:
        for start, block in ascii_records(fp, metadata.points, dtype, chunk_rows=chunk_rows, chunk_bytes=chunk_bytes, cancel=cancel):
            pc_data[start:start + len(block)] = block
    elif metadata.data == Encoding.BINARY:
        rows = min(chunk_rows, chunk_bytes // dtype.itemsize)
        for start in range(0, metadata.points, rows):
            check_cancel(cancel)
            block = exact_read(fp, min(rows, metadata.points - start) * dtype.itemsize)
            pc_data[start:start + len(block) // dtype.itemsize] = np.frombuffer(block, dtype)
    elif metadata.data == Encoding.BINARY_COMPRESSED:
        compressed = exact_read(fp, compressed_size)
        if size == 0:
            if compressed:
                raise ValueError("body: nonempty compressed data for empty cloud")
            buffer = b""
        else:
            buffer = lzf.decompress(compressed, uncompressed_size)
            if buffer is None or len(buffer) != size:
                raise ValueError("body: LZF decompressed length mismatch")
        offset = 0
        for names, field_size, count in zip(metadata.field_columns, metadata.size, metadata.count):
            check_cancel(cancel)
            # PCL 按原 FIELDS 分组，COUNT 分量在每点内连续，不能按展开列分组。
            length = field_size * count * metadata.points
            values = np.frombuffer(buffer, dtype=dtype[names[0]], count=metadata.points * count, offset=offset).reshape(metadata.points, count)
            for column, name in enumerate(names):
                pc_data[name] = values[:, column]
            offset += length
        if offset != size:
            raise ValueError("body: unconsumed compressed layout")
    else:
        raise ValueError("header: unsupported encoding")
    require_eof(fp)
    check_cancel(cancel)
    return pc_data


def _compose_pc_data(
    points: Union[npt.NDArray, Sequence[npt.NDArray]], metadata: MetaData
) -> npt.NDArray:
    arrays = tuple(points.T) if isinstance(points, np.ndarray) else points

    return np.rec.fromarrays(arrays, dtype=metadata.build_dtype())


class PointCloud:
    def __init__(self, metadata: MetaData, pc_data: npt.NDArray) -> None:
        if pc_data.ndim != 1 or len(pc_data) != metadata.points or pc_data.dtype != metadata.build_dtype():
            raise ValueError("data: array does not match metadata")
        self.metadata = metadata
        self.pc_data = pc_data

    @staticmethod
    def from_fileobj(fp: BufferedReader, *, max_header_bytes, **limits) -> PointCloud:
        metadata, _ = read_pcd_header(fp, max_header_bytes=max_header_bytes)
        return PointCloud(metadata, read_pcd_data(fp, metadata, **limits))

    @staticmethod
    def from_path(path: PathLike, **limits) -> PointCloud:
        """Create PointCloud from file path

        Args:
            path (PathLike): File path

        Raises:
            FileNotFoundError: Raise if `path` does not exist.

        Returns:
            PointCloud: PointCloud object

        >>> PointCloud.from_path("test.pcd")
        PointCloud(
            fields=('x', 'y', 'z') size=(4, 4, 4) type=('F', 'F', 'F') count=(1, 1, 1) points=10000
            width=10000 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )
        """

        with open(path, mode="rb") as fp:
            return PointCloud.from_fileobj(fp, **limits)

    @staticmethod
    def from_points(
        points: Union[npt.NDArray, List[npt.NDArray], Tuple[npt.NDArray, ...]],
        fields: Sequence[str],
        types: Sequence[npt.DTypeLike],
        count: Optional[Sequence[int]] = None,
    ) -> PointCloud:
        """Create PointCloud from 2D numpy array or sequence of 1D numpy arrays of each field

        Args:
            points (Union[npt.NDArray, List[npt.NDArray], Tuple[npt.NDArray, ...]]): Numpy array
            fields (Sequence[str]): Field names for each numpy array or sequence of numpy arrays
            types (Sequence[npt.DTypeLike]): Numpy type for each numpy array or
                sequence of numpy arrays
            count (Optional[Sequence[int]], optional): Number of values for each numpy array or
                sequence of numpy arrays. If None, set to 1 for all fields. Defaults to None.

        Raises:
            TypeError: Raise if `points` type is neither `npt.NDArray` nor `Sequence[npt.NDArray]`.

        Returns:
            PointCloud: PointCloud object

        >>> PointCloud.from_points(
                np.array([[1, 2, 3], [4, 5, 6]]),
                ("x", "y", "z"),
                (np.float32, np.float32, np.float32)
            )
        PointCloud(
            fields=('x', 'y', 'z') size=(4, 4, 4) type=('F', 'F', 'F') count=(1, 1, 1) points=2
            width=2 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )

        >>> PointCloud.from_points(
                [
                    np.array([1, 2, 3]),
                    np.array([4, 5, 6])
                ],
                ("x", "y", "z"),
                (np.float32, np.float32, np.float32)
            )
        PointCloud(
            fields=('x', 'y', 'z') size=(4, 4, 4) type=('F', 'F', 'F') count=(1, 1, 1) points=2
            width=2 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )
        """

        if not isinstance(points, (np.ndarray, list, tuple)):
            raise TypeError(
                "`points` must be a `np.ndarray`, `List[np.ndarray]` or `Tuple[np.ndarray]` type, "
                f"but got `{type(points).__name__}` type"
            )

        if len(fields) != len(types):
            raise ValueError(
                f"`fields` and `types` must have the same length, "
                f"but got {len(fields)} fields and {len(types)} types"
            )

        num_fields = points.shape[1] if isinstance(points, np.ndarray) else len(points)
        if num_fields != len(fields):
            raise ValueError(
                f"`points` must have {len(fields)} fields {fields}, but got {num_fields} fields"
            )

        if count is None:
            count = [1] * len(tuple(fields))

        pcd_types, sizes = [], []
        for type_ in types:
            t, s = NUMPY_TYPE_TO_PCD_TYPE[np.dtype(type_)]
            pcd_types.append(t)
            sizes.append(s)

        num_points = len(points) if isinstance(points, np.ndarray) else len(points[0])

        metadata = _validate_metadata(
            {
                "fields": fields,
                "size": sizes,
                "type": pcd_types,
                "count": count,
                "width": num_points,
                "points": num_points,
            }
        )

        return PointCloud(metadata, _compose_pc_data(points, metadata))

    @staticmethod
    def from_xyz_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z")
        types = (np.float32, np.float32, np.float32)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzi_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity")
        types = (np.float32, np.float32, np.float32, np.float32)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzl_points(points: npt.NDArray, label_type: npt.DTypeLike = np.float32) -> PointCloud:
        fields = ("x", "y", "z", "label")
        types = (np.float32, np.float32, np.float32, label_type)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzrgb_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "rgb")
        types = (np.float32, np.float32, np.float32, np.float32)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzrgbl_points(
        points: npt.NDArray, label_type: npt.DTypeLike = np.float32
    ) -> PointCloud:
        fields = ("x", "y", "z", "rgb", "label")
        types = (np.float32, np.float32, np.float32, np.float32, label_type)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzil_points(
        points: npt.NDArray, label_type: npt.DTypeLike = np.float32
    ) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "label")
        types = (np.float32, np.float32, np.float32, np.float32, label_type)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzirgb_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "rgb")
        types = (np.float32, np.float32, np.float32, np.float32, np.float32)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzirgbl_points(
        points: npt.NDArray, label_type: npt.DTypeLike = np.float32
    ) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "rgb", "label")
        types = (np.float32, np.float32, np.float32, np.float32, np.float32, label_type)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzt_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "sec", "nsec")
        types = (np.float32, np.float32, np.float32, np.uint32, np.uint32)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzir_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "ring")
        types = (np.float32, np.float32, np.float32, np.float32, np.uint16)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzirt_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "ring", "time")
        types = (np.float32, np.float32, np.float32, np.float32, np.uint16, np.float32)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzit_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "timestamp")
        types = (np.float32, np.float32, np.float32, np.float32, np.float64)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzis_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "stamp")
        types = (np.float32, np.float32, np.float32, np.float32, np.float64)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzisc_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "stamp", "classification")
        types = (np.float32, np.float32, np.float32, np.float32, np.float64, np.uint8)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzrgbs_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "rgb", "stamp")
        types = (np.float32, np.float32, np.float32, np.float32, np.float64)

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzirgbs_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "rgb", "stamp")
        types = (
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.float64,
        )

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyzirgbsc_points(points: npt.NDArray) -> PointCloud:
        fields = ("x", "y", "z", "intensity", "rgb", "stamp", "classification")
        types = (
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.float64,
            np.uint8,
        )

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_xyziradt_points(points: npt.NDArray) -> PointCloud:
        fields = (
            "x",
            "y",
            "z",
            "intensity",
            "ring",
            "azimuth",
            "distance",
            "return_type",
            "time_stamp",
        )
        types = (
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.uint16,
            np.float32,
            np.float32,
            np.uint8,
            np.float64,
        )

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_ouster_points(points: npt.NDArray) -> PointCloud:
        fields = (
            "x",
            "y",
            "z",
            "intensity",
            "t",
            "reflectivity",
            "ring",
            "ambient",
            "range",
        )
        types = (
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.float32,
            np.uint16,
            np.uint8,
            np.uint16,
            np.uint32,
        )

        return PointCloud.from_points(points, fields, types)

    @staticmethod
    def from_list(pcs: List[PointCloud]) -> PointCloud:
        """Concatenates a list of point clouds together

        The result is always unorganized (height=1), since concatenation
        doesn't in general preserve a valid 2D grid structure. `viewpoint`
        carries over if every point cloud in `pcs` agrees on it, and resets
        to the default otherwise -- there's no way to combine different
        acquisition poses into one.

        Args:
            pcs (List[PointCloud]): Point clouds to concatenate

        Returns:
            PointCloud: Concatenated point cloud
        """

        if not all(pc.fields == pcs[0].fields and pc.types == pcs[0].types for pc in pcs):
            raise ValueError("from_list: All PointClouds must have the same fields and types")

        points = sum(pc.points for pc in pcs)
        metadata = pcs[0].metadata.derive(
            points=points,
            width=points,
            height=1,
            viewpoint=_merge_viewpoints([pc.metadata.viewpoint for pc in pcs]),
            data=Encoding.BINARY_COMPRESSED,
        )

        return PointCloud(metadata, np.concatenate([pc.pc_data for pc in pcs]))

    @staticmethod
    def from_msg(msg: sensor_msgs__msg__PointCloud2) -> PointCloud:
        """Create a PointCloud from a ROS/ROS 2 sensor_msgs.msg.PointCloud2 message

        Args:
            msg: The ROS/ROS 2 sensor_msgs/PointCloud2 message

        Returns:
            The PointCloud
        """

        pc_data = np.frombuffer(msg.data, build_dtype_from_msg(msg))
        metadata = _validate_metadata(
            {
                "fields": _dtype_names(pc_data.dtype),
                "size": [
                    NUMPY_TYPE_TO_PCD_TYPE[pc_data[name].dtype][1]
                    for name in _dtype_names(pc_data.dtype)
                ],
                "type": [
                    NUMPY_TYPE_TO_PCD_TYPE[pc_data[name].dtype][0]
                    for name in _dtype_names(pc_data.dtype)
                ],
                "count": [1] * len(_dtype_names(pc_data.dtype)),
                "points": len(pc_data),
                "width": msg.width,
                "height": msg.height,
                "version": "0.7",
                "viewpoint": (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                "data": Encoding.BINARY,
            }
        )

        return PointCloud(metadata, pc_data)

    def to_msg(self, header: Optional["Header"] = None) -> "PointCloud2":
        """Create a ROS/ROS 2 sensor_msgs.msg.PointCloud2 message from the PointCloud

        Args:
            header: The header to use for the message.
                    If None, a default header will be used. Default: None.

        Returns:
            The ROS/ROS 2 sensor_msgs/PointCloud2 message
        """
        ROS_MSG_AVAILABLE = False
        try:
            from sensor_msgs.msg import PointCloud2, PointField
            from std_msgs.msg import Header

            ROS_MSG_AVAILABLE = True
            try:
                from builtin_interfaces.msg import Time  # ROS2  # type: ignore
            except ImportError:
                from std_msgs.msg import Time  # ROS1  # type: ignore
        except ImportError:
            pass

        if not ROS_MSG_AVAILABLE:
            try:
                # Fallback to rosbags
                from rosbags.typesys.stores.latest import (
                    builtin_interfaces__msg__Time as Time,
                )
                from rosbags.typesys.stores.latest import (
                    sensor_msgs__msg__PointCloud2 as PointCloud2,
                )
                from rosbags.typesys.stores.latest import (
                    sensor_msgs__msg__PointField as PointField,
                )
                from rosbags.typesys.stores.latest import (
                    std_msgs__msg__Header as Header,
                )

                ROS_MSG_AVAILABLE = True
            except ImportError:
                pass

        if not ROS_MSG_AVAILABLE:
            raise ImportError(
                "The PointCloud.to_msg() method requires ROS `sensor_msgs` or the `rosbags` pkg.\n"
                "Please install either:\n"
                "  - ROS/ROS2 (check official documentation), or\n"
                "  - rosbags via `pip install rosbags`."
            )
        fields = []
        itemsize = 0
        row_step = 0
        offset = 0
        for field, type_, count in zip(self.fields, self.types, self.counts):
            type_ = np.dtype(type_)

            itemsize += type_.itemsize
            row_step += type_.itemsize * self.points

            fields.append(
                PointField(
                    name=field,
                    offset=offset,
                    datatype=NPTYPE_TO_PFTYPE[type_],
                    count=count,
                )
            )
            offset += type_.itemsize * count

        data = self.pc_data.reshape(-1).view(np.uint8)

        if header is None:
            try:
                header = Header(stamp=Time(sec=0, nanosec=0), frame_id="")
            except (TypeError, AttributeError):
                header = Header(stamp=Time(0), frame_id="", seq=0)

        msg = PointCloud2(
            header=header,
            height=1,
            width=self.points,
            is_dense=False,
            is_bigendian=False,
            fields=fields,
            point_step=itemsize,
            row_step=len(data),
            data=data,
        )

        return msg

    @staticmethod
    def encode_rgb(rgb: npt.NDArray | list[npt.NDArray]) -> npt.NDArray:
        """
        Encode Nx3 uint8 array with RGB values to
        Nx1 float32 array with bit-packed RGB
        """

        if isinstance(rgb, np.ndarray):
            if rgb.ndim == 1:
                rgb = rgb[:, None]
        else:
            rgb = np.hstack([v[:, None] if v.ndim == 1 else v for v in rgb])

        rgb_u32 = rgb.astype(np.uint32)
        rgb_u32 = np.array(
            (rgb_u32[:, 0] << 16) | (rgb_u32[:, 1] << 8) | (rgb_u32[:, 2] << 0),
            dtype=np.uint32,
        )
        return rgb_u32.view(np.float32)

    @staticmethod
    def decode_rgb(rgb: npt.NDArray) -> npt.NDArray:
        """
        Decode Nx1 float32 array with bit-packed RGB to
        Nx3 uint8 array with RGB values
        """

        rgb = rgb.view(np.uint32)

        r = np.asarray((rgb >> 16) & 255, dtype=np.uint8).reshape(-1, 1)
        g = np.asarray((rgb >> 8) & 255, dtype=np.uint8).reshape(-1, 1)
        b = np.asarray(rgb & 255, dtype=np.uint8).reshape(-1, 1)

        return np.hstack((r, g, b)).reshape(-1, 3)

    @property
    def fields(self) -> Tuple[str, ...]:
        """
        Returns fields of the point cloud

        Returns:
            Tuple[str, ...]: Tuple of field names for each field

        Note:
            If the field count is not 1, the field names will be suffixed with __0000, __0001, etc.
            If you don't want this behavior, use the `pc.metadata.fields` instead.

        >>> pc1.metadata.count
        (1, 1, 1)

        >>> pc1.fields
        ("x", "y", "z")

        >>> pc2.metadata.count
        (1, 1, 2)

        >>> pc2.fields
        ("x", "y", "z__0000", "z__0001")

        >>> pc2.metadata.fields
        ("x", "y", "z")
        """

        fields = []
        for field, count in zip(self.metadata.fields, self.metadata.count):
            if count == 1:
                fields.append(field)
            else:
                fields.extend(f"{field}__{c:04d}" for c in range(count))

        return tuple(fields)

    @property
    def types(self) -> Tuple[npt.DTypeLike, ...]:
        """Returns types of the point cloud

        Returns:
            Tuple[npt.DTypeLike, ...]: Tuple of numpy types for each field

        Note:
            If the field count is not 1, the type will be repeated for the number of fields

        >>> pc1.metadata.count
        (1, 1, 1)

        >>> pc1.types
        (np.float32, np.int32, np.float32)

        >>> pc2.metadata.count
        (1, 2, 1)

        >>> pc2.types
        (np.float32, np.int32, np.int32, np.float32)
        """

        types = []
        for ts, count in zip(zip(self.metadata.type, self.metadata.size), self.metadata.count):
            if count == 1:
                types.append(PCD_TYPE_TO_NUMPY_TYPE[ts])
            else:
                types.extend(PCD_TYPE_TO_NUMPY_TYPE[ts] for _ in range(count))

        return tuple(types)

    @property
    def counts(self) -> Tuple[PositiveInt, ...]:
        """Returns number of elements in each field

        Returns:
            Tuple[PositiveInt, ...]: Tuple of number of elements in each field

        Note:
            If the field count is not 1, the count will be repeated for the number of its counts
            If you don't want this behavior, use the `pc.metadata.count` instead.

        >>> pc1.metadata.count
        (1, 1, 1)

        >>> pc2.metadata.count
        (1, 2, 1)

        >>> pc2.counts
        (1, 1, 1, 1)
        """

        return (1,) * sum(self.metadata.count)

    @property
    def points(self) -> int:
        """Returns number of points in the point cloud

        Returns:
            int: The number of points

        >>> pc.points
        1000
        """

        return self.metadata.points

    def numpy(self, fields: Optional[Sequence[str]] = None) -> npt.NDArray:
        """Returns numpy array of the point cloud

        Args:
            fields (Optional[Sequence[str]], optional): Fields to return.
                If None, all fields are returned. Defaults to None.

        Returns:
            npt.NDArray: Numpy array of the point cloud

        >>> pc.fields
        ("x", "y", "z")

        >>> pc.numpy()
        array([[0.0, 0.1, 0.2],
               [0.3, 0.4, 0.5],
               ...,
               [0.9, 1.0, 1.1]])

        >>> pc.numpy(("x", "y"))
        array([[0.0, 0.1],
               [0.3, 0.4],
               ...,
               [0.9, 1.0]])

        >>> pc.numpy(("x", "y", "z"))
        array([[0.0, 0.1, 0.2],
               [0.3, 0.4, 0.5],
               ...,
               [0.9, 1.0, 1.1]])
        """

        if fields is None:
            fields = self.fields

        if len(fields) == 0:
            return np.empty((0, 0))

        if self.metadata.points == 0:
            return np.empty((0, len(fields)))

        _stack = tuple(self.pc_data[field] for field in fields)

        return np.vstack(_stack).T

    def _save_as_ascii(self, fp: BinaryIO, *, chunk_rows, cancel) -> None:
        """Saves point cloud to a file as a ascii

        Args:
            fp (BinaryIO): io buffer.
        """

        write_records(fp, self.pc_data, ascii=True, chunk_rows=chunk_rows, cancel=cancel)

    def _save_as_binary(self, fp: BinaryIO, *, chunk_rows, cancel) -> None:
        """Saves point cloud to a file as a binary

        Args:
            path (PathLike): Path to the file
        """

        write_records(fp, self.pc_data, ascii=False, chunk_rows=chunk_rows, cancel=cancel)

    def _save_as_binary_compressed(self, fp: BinaryIO, *, max_working_bytes, cancel) -> None:
        """Saves point cloud to a file as a binary compressed

        Args:
            fp (BinaryIO): io buffer.
        """

        size = self.pc_data.nbytes
        output_capacity = size + (size + 31) // 32 + 1 if size else 0
        if output_capacity > 0xFFFFFFFF or size * 2 + output_capacity > max_working_bytes:
            raise ValueError("budget: compressed writer buffers exceed capacity")
        # 三份上限计入分组列块、拼接正文和压缩输出；源数组另由 owner 计费。
        blocks = []
        for names in self.metadata.field_columns:
            check_cancel(cancel)
            group_dtype = np.dtype([(name, self.pc_data.dtype[name]) for name in names])
            group = np.empty(self.points, dtype=group_dtype)
            for name in names:
                group[name] = self.pc_data[name]
            blocks.append(group.tobytes())
            del group
        uncompressed = b"".join(blocks)
        del blocks
        check_cancel(cancel)
        if not size:
            compressed = b""
        else:
            compressed = lzf.compress(uncompressed, output_capacity)
            if compressed is None:
                raise ValueError("write: LZF compression failed; encoding was not changed")
        check_cancel(cancel)
        writer = CheckedWriter(fp)
        writer.write(struct.pack("<II", len(compressed), size))
        writer.write(compressed)

    def save(self, fp: Union[PathLike, BinaryIO], encoding: Encoding = Encoding.BINARY, *, chunk_rows, max_working_bytes, cancel=None) -> None:
        """Saves point cloud to a file

        Args:
            fp (Union[PathLike, BinaryIO]): Path to the file or io buffer.
            encoding (Encoding, optional): Encoding to use. Defaults to Encoding.BINARY_COMPRESSED.
        """

        positive(chunk_rows, "chunk_rows")
        positive(max_working_bytes, "max_working_bytes")
        encoding = Encoding(encoding)
        # 导出前重新检查，拒绝调用方在构造后换掉数组导致头部/正文不一致。
        if self.pc_data.shape != (self.points,) or self.pc_data.dtype != self.metadata.build_dtype():
            raise ValueError("write: array does not match metadata")
        check_cancel(cancel)
        is_open = False
        if isinstance(fp, Path):
            fp = fp.open(mode="wb")
            is_open = True
        elif isinstance(fp, str):
            fp = open(fp, mode="wb")
            is_open = True

        try:
            header = self.metadata.compose_header(data=encoding).encode()
            CheckedWriter(fp).write(header)

            if encoding == Encoding.ASCII:
                self._save_as_ascii(fp, chunk_rows=chunk_rows, cancel=cancel)
            elif encoding == Encoding.BINARY:
                self._save_as_binary(fp, chunk_rows=chunk_rows, cancel=cancel)
            else:
                self._save_as_binary_compressed(fp, max_working_bytes=max_working_bytes, cancel=cancel)
            fp.flush()
        finally:
            if is_open:
                fp.close()

    def __add__(self, other: PointCloud) -> PointCloud:
        """Concatenates two point clouds together

        The result is always unorganized (height=1), since concatenation
        doesn't in general preserve a valid 2D grid structure. `viewpoint`
        carries over if both point clouds agree on it, and resets to the
        default otherwise -- there's no way to combine two different
        acquisition poses into one.

        Args:
            other (PointCloud): Point cloud to concatenate with

        Returns:
            PointCloud: Concatenated point cloud

        >>> pc1 = PointCloud.from_xyz_points(np.random.rand(10000, 3))
        >>> pc2 = PointCloud.from_xyz_points(np.random.rand(10000, 3))

        >>> pc1 + pc2
        PointCloud(
            fields=('x', 'y', 'z') size=(4, 4, 4) type=('F', 'F', 'F') count=(1, 1, 1) points=20000
            width=20000 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )
        """

        if self.fields != other.fields:
            raise ValueError(
                "add: Can't concatenate point clouds with different fields. "
                f"({self.fields} vs. {other.fields})"
            )
        if self.types != other.types:
            raise ValueError(
                "add: Can't concatenate point clouds with different types. "
                f"({self.types} vs. {other.types})"
            )

        points = self.points + other.points
        metadata = self.metadata.derive(
            points=points,
            width=points,
            height=1,
            viewpoint=_merge_viewpoints([self.metadata.viewpoint, other.metadata.viewpoint]),
            data=Encoding.BINARY_COMPRESSED,
        )

        return PointCloud(metadata, np.concatenate([self.pc_data, other.pc_data]))

    def __getitem__(
        self, subscript: Union[slice, str, list[str], tuple[str, ...], npt.NDArray[np.bool_]]
    ) -> PointCloud:
        """Returns a point cloud with only the points that match the subscript

        A slice or boolean mask selects a subset of points from the same
        scan, so `viewpoint` and the encoding always carry over unchanged;
        `height` resets to 1 since an arbitrary subset of points isn't
        guaranteed to form a valid 2D grid. Selecting by field name doesn't
        touch which points exist, so every metadata field other than
        `fields`/`size`/`type`/`count` carries over unchanged, `height`
        included.

        Args:
            subscript (Union[slice, npt.NDArray[np.bool_]]): Subscript to match.

        Returns:
            PointCloud: Point cloud with only the points that match the subscript.

        >>> pc = PointCloud.from_xyz_points(np.random.rand(10000, 3))

        >>> pc[3:8]
        PointCloud(
            fields=('x', 'y', 'z') size=(4, 4, 4) type=('F', 'F', 'F') count=(1, 1, 1) points=5
            width=5 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )

        >>> mask = (pc.pc_data["x"] > 0.5) & (pc.pc_data["y"] < 0.5)
        >>> pc[mask]
        PointCloud(
            fields=('x', 'y', 'z') size=(4, 4, 4) type=('F', 'F', 'F') count=(1, 1, 1) points=2593
            width=2593 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )

        >>> pc[("x", "y")]
        PointCloud(
            fields=('x', 'y') size=(4, 4) type=('F', 'F') count=(1, 1) points=10000
            width=10000 height=1 version='0.7' viewpoint=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            data=<Encoding.BINARY_COMPRESSED: 'binary_compressed'>
        )
        """

        if isinstance(subscript, slice):
            pc_data = self.pc_data[subscript]
            metadata = self.metadata.derive(points=len(pc_data), width=len(pc_data), height=1)
        elif isinstance(subscript, np.ndarray):
            mask = subscript.squeeze()
            if mask.ndim != 1:
                raise ValueError(f"Mask array must be 1-dimensional but got {mask.ndim}")

            pc_data = self.pc_data[mask]
            metadata = self.metadata.derive(points=len(pc_data), width=len(pc_data), height=1)
        elif isinstance(subscript, str) or all(isinstance(s, str) for s in cast(tuple, subscript)):
            if isinstance(subscript, str):
                subscript = (subscript,)

            subscript = cast(tuple, subscript)

            if not np.isin(subscript, self.fields).all():
                raise ValueError(f"Invalid field name(s): {subscript}")

            selected_types = [self.pc_data[field].dtype for field in subscript]
            pcd_types_and_sizes = [NUMPY_TYPE_TO_PCD_TYPE[dt] for dt in selected_types]
            metadata = self.metadata.derive(
                fields=subscript,
                size=tuple(size for _, size in pcd_types_and_sizes),
                type=tuple(pcd_type for pcd_type, _ in pcd_types_and_sizes),
                count=(1,) * len(subscript),
            )
            pc_data = _compose_pc_data(tuple(self.pc_data[field] for field in subscript), metadata)
        else:
            raise ValueError(f"Invalid subscript type: {type(subscript).__name__}")

        return PointCloud(metadata, pc_data)

    def __str__(self) -> str:
        return f"PointCloud({self.metadata})"

    def __len__(self) -> int:
        return self.points
