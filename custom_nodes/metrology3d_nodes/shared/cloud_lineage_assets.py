"""来源数组的固定资产布局；复用云借用、ObjectStore 流和既有容量。"""


def lineage_chunks(view, rows, cancel):
    """按字段有界输出；CSR 偏移累加，不能把分块偏移直接拼接。"""
    n = view.reference.point_count
    for name in ("source_edges", "weights", "face_offsets", "source_faces"):
        offset = 0
        if name == "face_offsets":
            yield bytes(8)
        for start in range(0, n, rows):
            cancel()
            block = view.lineage_chunk(start, min(start + rows, n))
            if name == "face_offsets":
                yield (block[name][1:] + offset).astype("<u8", copy=False).tobytes()
                offset += len(block["source_faces"])
            else:
                yield block[name].tobytes(order="C")


def count_lineage_faces(view, rows, cancel):
    """对当前逻辑视图计数，经过裁剪后不沿用父云邻面数量。"""
    count = 0
    for start in range(0, view.reference.point_count, rows):
        cancel()
        count += len(
            view.lineage_chunk(start, min(start + rows, view.reference.point_count))[
                "source_faces"
            ]
        )
    return count
