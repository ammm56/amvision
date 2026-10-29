"""四侧分位跨度；输出统计端点，不把分位数冒充单个实测点。"""

import numpy as np

from backend.contracts.workflows.envelope3d import PROFILE_SIDES, ProfileQuantileContact
from backend.service.application.errors import InvalidRequestError


def profile_spans(positions, profiles, evaluation, mode, *, max_working_bytes, cancel):
    """各侧等站位权重，复用 NumPy linear 分位，不对缺失区间增加权重。"""
    cancel()
    if len(positions) * 256 > max_working_bytes:
        raise InvalidRequestError("稳健剖面统计超过工作预算")
    if tuple(part["segment_id"] for part in profiles) != PROFILE_SIDES:
        raise InvalidRequestError("稳健跨度需要完整且顺序明确的四侧剖面")
    uv = (np.asarray(positions, dtype=float) - evaluation.origin) @ np.asarray(
        evaluation.rotation
    )
    if not np.isfinite(uv).all():
        raise InvalidRequestError("剖面位置必须有限")
    limits, contacts, coordinates = [], [], []
    cursor = 0
    for side, part in enumerate(profiles):
        cancel()
        start, count = part["start"], part["count"]
        if start != cursor or count < 1 or start + count > len(uv):
            raise InvalidRequestError("剖面布局不完整")
        cursor += count
        q = mode.lower_quantile if side % 2 == 0 else mode.upper_quantile
        values = uv[start : start + count, side // 2]
        # 稳定顺序给相等统计值确定的来源；数据块保持只读语义。
        order = np.argsort(values, kind="stable")
        rank = q * (count - 1)
        first, last, weight = int(rank), min(int(rank) + 1, count - 1), rank - int(rank)
        indices = (int(start + order[first]), int(start + order[last]))
        value = float(np.quantile(values, q, method=mode.quantile_method))
        point = (1 - weight) * uv[indices[0]] + weight * uv[indices[1]]
        point[side // 2], point[2] = value, 0
        coordinates.append(
            point @ np.asarray(evaluation.rotation).T + evaluation.origin
        )
        contacts.append(
            ProfileQuantileContact(
                kind="profile-quantile",
                side=PROFILE_SIDES[side],
                sample_count=count,
                quantile=q,
                method=mode.quantile_method,
                ranks=(first, last),
                vertex_indices=indices,
                weight=weight,
            )
        )
        limits.append(value)
    if cursor != len(uv):
        raise InvalidRequestError("剖面布局未覆盖完整支持")
    if not limits[0] < limits[1] or not limits[2] < limits[3]:
        return None
    cancel()
    return dict(
        limits=limits,
        contacts=contacts,
        coordinates=coordinates,
        span_u=limits[1] - limits[0],
        span_v=limits[3] - limits[2],
    )
