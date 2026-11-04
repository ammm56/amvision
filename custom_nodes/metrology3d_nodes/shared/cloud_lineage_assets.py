"""来源数组的固定资产布局；复用云借用、ObjectStore 流和既有容量。"""


def lineage_chunks(view, rows, cancel):
    """按字段有界输出；CSR 偏移累加，不能把分块偏移直接拼接。"""
    n = view.reference.point_count
    voxel = view.reference.lineage_kind == "voxel-aggregate"
    fields = (
        ("voxel_keys", "member_offsets", "source_rows")
        if voxel
        else ("source_edges", "weights", "face_offsets", "source_faces")
    )
    offset_name, member_name = (
        ("member_offsets", "source_rows") if voxel else ("face_offsets", "source_faces")
    )
    for name in fields:
        offset = 0
        if name == offset_name:
            yield bytes(8)
        for start in range(0, n, rows):
            cancel()
            block = view.lineage_chunk(start, min(start + rows, n))
            if name == offset_name:
                yield (block[name][1:] + offset).astype("<u8", copy=False).tobytes()
                offset += len(block[member_name])
            else:
                yield block[name].tobytes(order="C")


def count_lineage_members(view, rows, cancel):
    """对当前逻辑视图的邻面/体素成员计数，裁剪后不沿用父云数量。"""
    count = 0
    for start in range(0, view.reference.point_count, rows):
        cancel()
        count += len(
            view.lineage_chunk(start, min(start + rows, view.reference.point_count))[
                "source_rows"
                if view.reference.lineage_kind == "voxel-aggregate"
                else "source_faces"
            ]
        )
    return count
