"""显式字段的交换导出；复用受控 writer，不自行生成 PLY/PCD 文法。"""

from typing import Annotated, Literal, Self

import numpy as np
from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.metrology import Contract, Identifier, unique_ids
from backend.contracts.workflows.point_cloud import (
    CloudFileOptions,
    CloudFieldMapping,
    ShortText,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes._metrology3d_nodes.shared.io.formats import (
    require_controlled_distribution,
)


class CloudExportOptions(Contract):
    """交换文件输出沿当前单位；字段选择和空间信息缺失必须明确。"""

    profile_id: Literal[
        "ply-binary-le",
        "ply-binary-be",
        "ply-ascii",
        "pcd-ascii",
        "pcd-binary",
        "pcd-binary-compressed",
        "xyz-whitespace",
        "xyzn-whitespace",
        "xyzi-whitespace",
        "xyzrgb-whitespace",
    ]
    profile_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    fields: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    file_name: ShortText
    spatial_acknowledged: StrictBool

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        """禁止重复字段、缺少坐标或将文件名当路径。"""
        unique_ids(self.fields, "fields")
        if (
            "positions" not in self.fields
            or any(c in self.file_name for c in ("/", "\\", ":", "\0"))
            or self.file_name in (".", "..")
        ):
            raise ValueError("导出字段或文件名无效")
        if not self.spatial_acknowledged:
            raise ValueError("交换文件不完整保存单位与空间声明，必须显式确认")
        return self


def export_cloud_file(runtime, reference, options, *, stream, max_output_bytes, cancel):
    """完整物化所选结构数组并计费；成功仅指文件编码完成，不代表已发布。"""
    from backend.service.application.runtime.io.bounded_output import (
        BoundedBinaryOutput,
    )

    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise ValueError("导出文件限额必须显式提供")
    options = CloudExportOptions.model_validate(options)
    fields = {f.name: f for f in reference.fields or ()}
    if not set(options.fields) <= set(fields):
        raise InvalidRequestError("导出包含不存在的点云字段")
    canonical = {
        "positions": ("x", "y", "z"),
        "normals": ("nx", "ny", "nz"),
        "colors": ("r", "g", "b"),
    }
    mapping = tuple(
        CloudFieldMapping(
            source_names=canonical.get(name, (name,)),
            target_name=name,
            **fields[name].model_dump(exclude={"name"}),
        )
        for name in options.fields
    )
    # 共用同一严格 profile 校验；公开导出不允许省略/窄化所选字段。
    read_options = CloudFileOptions(
        profile_id=options.profile_id,
        profile_version=options.profile_version,
        spatial=reference.spatial,
        field_mapping=mapping,
    )
    dtype_fields = [
        (column, np.dtype(m.dtype).newbyteorder("<"))
        for m in mapping
        for column in m.source_names
    ]
    unique_ids([column for column, _ in dtype_fields], "导出列名")
    dtype = np.dtype(dtype_fields)
    size = reference.point_count * dtype.itemsize
    if size > runtime.policy.max_decoded_bytes:
        raise InvalidRequestError("导出结构数组超过显式解码预算")
    # 输入 gather、编码字节与 XYZ float64 工作数组均在块预算内。
    input_row_bytes = sum(
        np.dtype(f.dtype).itemsize * f.components for f in fields.values()
    )
    rows = min(
        runtime.policy.chunk_rows,
        runtime.policy.max_working_bytes
        // (input_row_bytes + dtype.itemsize * 2 + len(dtype_fields) * 16 + 32),
    )
    if rows < 1:
        raise InvalidRequestError("导出工作预算不足一行")
    reservation = runtime.budget.reserve(size)
    data = None
    block = None
    try:
        with runtime.borrow(reference) as view:
            data = np.empty(reference.point_count, dtype=dtype)
            for start in range(0, reference.point_count, rows):
                cancel()
                stop = min(start + rows, reference.point_count)
                block = view.chunk(start, stop)
                for m in mapping:
                    for index, column in enumerate(m.source_names):
                        data[column][start:stop] = block[m.target_name][:, index]
            output = BoundedBinaryOutput(stream, max_output_bytes, cancel)
            _write(
                data,
                output,
                options,
                reference,
                rows,
                runtime.policy.max_working_bytes,
                cancel,
            )
            return {
                "profile_id": options.profile_id,
                "profile_version": options.profile_version,
                "point_count": reference.point_count,
                "fields_written": list(options.fields),
                "fields_omitted": [f for f in fields if f not in options.fields],
                "spatial": reference.spatial.model_dump(mode="json"),
                "source_reference": reference.source.reference.model_dump(mode="json")
                if reference.source.kind == "asset"
                else None,
            }, read_options
    except BaseException as error:
        release_exception_frames(error)
        raise
    finally:
        block = None
        data = None
        reservation.close()


def _write(data, stream, options, reference, rows, max_working_bytes, cancel):
    """唯一格式分派；失败不换库、编码或精度。"""
    if options.profile_id.startswith("ply-"):
        require_controlled_distribution("trimesh", "5.1.1+amvision.1")
        from trimesh.exchange.ply import write_ply_points

        write_ply_points(
            stream,
            data,
            encoding={
                "ply-ascii": "ascii",
                "ply-binary-le": "binary_little_endian",
                "ply-binary-be": "binary_big_endian",
            }[options.profile_id],
            chunk_rows=rows,
            cancel=cancel,
        )
    elif options.profile_id.startswith("pcd-"):
        require_controlled_distribution("pypcd4", "1.5.1+amvision.2")
        from pypcd4.pypcd4 import PointCloud, MetaData, Encoding

        encoding = Encoding(
            {
                "pcd-ascii": "ascii",
                "pcd-binary": "binary",
                "pcd-binary-compressed": "binary_compressed",
            }[options.profile_id]
        )
        source = reference.source_metadata
        if source is not None and source.source_spatial != reference.spatial:
            raise InvalidRequestError(
                "PCD 原始 VIEWPOINT 不属于当前空间，不能原样贴到导出文件"
            )
        kwargs = (
            {
                "width": source.width,
                "height": source.height,
                "viewpoint": source.viewpoint,
            }
            if source
            else {"width": len(data), "height": 1}
        )
        metadata = MetaData(
            fields=data.dtype.names,
            size=tuple(data.dtype[n].itemsize for n in data.dtype.names),
            type=tuple(
                {"f": "F", "i": "I", "u": "U"}[data.dtype[n].kind]
                for n in data.dtype.names
            ),
            count=(1,) * len(data.dtype.names),
            points=len(data),
            data=encoding,
            **kwargs,
        )
        PointCloud(metadata, data).save(
            stream,
            encoding=encoding,
            chunk_rows=rows,
            max_working_bytes=max_working_bytes,
            cancel=cancel,
        )
    else:
        formats = [
            "%.9g"
            if data.dtype[n].itemsize == 4
            else "%.17g"
            if data.dtype[n].kind == "f"
            else "%d"
            for n in data.dtype.names
        ]
        for start in range(0, len(data), rows):
            cancel()
            block = np.column_stack(
                [data[name][start : start + rows] for name in data.dtype.names]
            )
            np.savetxt(
                stream,
                block,
                fmt=formats,
                delimiter=" ",
                newline="\n",
                encoding="ascii",
            )
        stream.flush()
