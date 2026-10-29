"""格剖面来源布局；仍由点云 Scope 持有，格支持按原始行号去重保存。"""

from types import MappingProxyType

import numpy as np

from backend.service.application.errors import InvalidRequestError


def profile_lineage_shapes(point_count, cell_count, source_count):
    """固定 LE 数组顺序供运行校验及资产读写共同使用。"""
    return dict(
        cell_indices=((cell_count, 2), "<u8"),
        cell_offsets=((cell_count + 1, 1), "<u8"),
        cell_sources=((source_count, 1), "<u8"),
        cell_heights=((cell_count, 1), "<f8"),
        profile_cells=((point_count, 2), "<u8"),
        profile_weights=((point_count, 2), "<f8"),
        profile_kinds=((point_count, 1), "u1"),
        profile_stations=((point_count, 1), "<u8"),
        profile_sides=((point_count, 1), "u1"),
    )


def validate_profile_lineage(
    arrays, *, point_count, source_point_count, policy, cancel
):
    """不接受源边字段伪装成格估计；布局、格邻接、原始支持与运算互相核对。"""
    if set(arrays) != set(profile_lineage_shapes(0, 0, 0)):
        raise InvalidRequestError("格剖面来源字段不完整")
    cells = arrays["cell_indices"]
    n, m = len(cells), len(arrays["cell_sources"])
    shapes = profile_lineage_shapes(point_count, n, m)
    for name, (shape, dtype) in shapes.items():
        value = arrays[name]
        if (
            value.shape != shape
            or value.dtype != np.dtype(dtype)
            or value.flags.writeable
        ):
            raise InvalidRequestError("格剖面来源形状、精度或只读状态无效")
    sources = arrays["cell_sources"][:, 0]
    cost = m * 24 + n * 64 + point_count * 256
    if cost > policy.max_working_bytes:
        raise InvalidRequestError("格剖面来源校验超过工作预算")
    offsets = arrays["cell_offsets"][:, 0]
    if offsets[0] != 0 or offsets[-1] != m or np.any(offsets[1:] <= offsets[:-1]):
        raise InvalidRequestError("格剖面支持区间无效")
    if np.any(cells > np.iinfo(np.int64).max):
        raise InvalidRequestError("格坐标超过可验证整数范围")
    if n > 1 and not np.all(
        (cells[1:, 0] > cells[:-1, 0])
        | ((cells[1:, 0] == cells[:-1, 0]) & (cells[1:, 1] > cells[:-1, 1]))
    ):
        raise InvalidRequestError("格注册表必须唯一且按 U/V 排序")
    if np.any(sources >= source_point_count) or len(np.unique(sources)) != m:
        raise InvalidRequestError("格支持原始行号越界或重复计权")
    if not np.isfinite(arrays["cell_heights"]).all():
        raise InvalidRequestError("格聚合高度必须有限")
    cancel()
    rows = min(policy.chunk_rows, max(1, policy.max_working_bytes // 512))
    for start in range(0, point_count, rows):
        cancel()
        end = min(start + rows, point_count)
        pair = arrays["profile_cells"][start:end]
        w = arrays["profile_weights"][start:end]
        kinds = arrays["profile_kinds"][start:end, 0]
        sides = arrays["profile_sides"][start:end, 0]
        stations = arrays["profile_stations"][start:end, 0]
        if np.any(pair >= n) or np.any(kinds > 3) or np.any(sides > 3):
            raise InvalidRequestError("格剖面索引或来源种类无效")
        if (
            not np.isfinite(w).all()
            or np.any(w < 0)
            or np.any(w > 1)
            or not np.allclose(w.sum(axis=1), 1, rtol=0, atol=8 * np.finfo(float).eps)
        ):
            raise InvalidRequestError("格剖面插值权重无效")
        first, second = cells[pair[:, 0]], cells[pair[:, 1]]
        axis = sides // 2
        if not np.array_equal(first[np.arange(len(pair)), 1 - axis], stations):
            raise InvalidRequestError("格剖面站位与源格不一致")
        estimated = kinds != 0
        if np.any(pair[estimated, 0] != pair[estimated, 1]) or np.any(
            w[estimated] != (1, 0)
        ):
            raise InvalidRequestError("格边估计不得伪造第二个插值格")
        crossing = ~estimated
        delta = second[crossing].astype(np.int64) - first[crossing].astype(np.int64)
        expected = np.zeros(delta.shape, dtype=np.int64)
        expected[np.arange(len(delta)), axis[crossing]] = np.where(
            sides[crossing] % 2 == 0, -1, 1
        )
        if not np.array_equal(delta, expected):
            raise InvalidRequestError("阈值插值必须使用对应方向的相邻格")
        h = arrays["cell_heights"][pair[crossing], 0]
        if (
            np.any(h[:, 0] * h[:, 1] > 0)
            or np.any(h[:, 0] == h[:, 1])
            or not np.allclose((h * w[crossing]).sum(axis=1), 0, rtol=0, atol=1e-10)
        ):
            raise InvalidRequestError("格中心插值不位于声明的零高度截面")


def profile_lineage_chunk(arrays, selected, *, max_working_bytes):
    """借用任意逻辑子集时重建去重格表，不把生成行号伪装为源行号。"""
    selected = np.asarray(selected, dtype=np.uint64)
    if len(selected) * 128 > max_working_bytes:
        raise InvalidRequestError("格剖面来源访问超过工作预算")
    pairs = arrays["profile_cells"][selected]
    cells, inverse = np.unique(pairs, return_inverse=True)
    original_offsets = arrays["cell_offsets"][:, 0]
    counts = original_offsets[cells + 1] - original_offsets[cells]
    m = sum(int(v) for v in counts)
    if len(selected) * 256 + len(cells) * 128 + m * 24 > max_working_bytes:
        raise InvalidRequestError("格剖面来源访问超过工作预算")
    offsets = np.zeros((len(cells) + 1, 1), dtype="<u8")
    offsets[1:, 0] = np.cumsum(counts, dtype=np.uint64)
    sources = np.empty((m, 1), dtype="<u8")
    for i, cell in enumerate(cells):
        sources[offsets[i, 0] : offsets[i + 1, 0]] = arrays["cell_sources"][
            original_offsets[cell] : original_offsets[cell + 1]
        ]
    result = dict(
        cell_indices=arrays["cell_indices"][cells],
        cell_offsets=offsets,
        cell_sources=sources,
        cell_heights=arrays["cell_heights"][cells],
        profile_cells=inverse.reshape(-1, 2).astype("<u8"),
        **{
            name: arrays[name][selected]
            for name in (
                "profile_weights",
                "profile_kinds",
                "profile_stations",
                "profile_sides",
            )
        },
    )
    for value in result.values():
        value.setflags(write=False)
    return MappingProxyType(result)
