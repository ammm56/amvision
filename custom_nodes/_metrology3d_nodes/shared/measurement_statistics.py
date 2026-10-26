"""全支持精确投影统计；均值分块，分位数只操作自有临时数组。"""

from math import fsum, sqrt

import numpy as np

from backend.contracts.workflows.measurement3d_directional import ProjectionStatistics
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.fit_plane import _positions, _rows


def projection_statistics(runtime, cloud, settings, *, cancel):
    """总体标准差描述区域离散程度，不冒充标定或测量不确定度。"""
    if cloud.state != "ready" or cloud.point_count == 0:
        return None
    count = cloud.point_count
    exact = settings.statistic.kind != "mean"
    held = count * 8 if exact else 0
    if held > runtime.policy.max_working_bytes:
        raise InvalidRequestError("精确统计投影超过工作预算")
    rows = _rows(runtime, cloud, held_bytes=held)
    values = np.empty(count) if exact else None
    origin, direction = np.asarray(settings.origin), np.asarray(settings.direction)
    with runtime.borrow(cloud) as view, np.errstate(over="raise", invalid="raise"):
        anchor = float((_positions(view, 0, 1)[0] - origin) @ direction)
        total = compensation = 0.0
        low, high = np.inf, -np.inf
        for start in range(0, count, rows):
            cancel()
            stop = min(start + rows, count)
            projected = (_positions(view, start, stop) - origin) @ direction
            if values is not None:
                values[start:stop] = projected
            low, high = (
                min(low, float(projected.min())),
                max(high, float(projected.max())),
            )
            addition = float((projected - anchor).sum()) - compensation
            new_total = total + addition
            compensation, total = (new_total - total) - addition, new_total
        relative_mean = total / count
        mean = fsum((anchor, relative_mean))
        squares = compensation = 0.0
        for start in range(0, count, rows):
            cancel()
            stop = min(start + rows, count)
            projected = (
                values[start:stop]
                if values is not None
                else (_positions(view, start, stop) - origin) @ direction
            )
            residual = (projected - anchor) - relative_mean
            addition = float(residual @ residual) - compensation
            new_total = squares + addition
            compensation, squares = (new_total - squares) - addition, new_total
        cancel()
        if settings.statistic.kind == "mean":
            value = mean
        elif settings.statistic.kind == "median":
            value = float(np.median(values, overwrite_input=True))
        else:
            value = float(
                np.quantile(
                    values,
                    settings.statistic.probability,
                    method=settings.statistic.method,
                    overwrite_input=True,
                )
            )
        cancel()
        return ProjectionStatistics(
            count=count,
            value=value,
            mean=mean,
            std=sqrt(squares / count),
            min=low,
            max=high,
        )
