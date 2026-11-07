"""平面与边缘共用的分块正交拟面；调用方负责支持选择和内存准入。"""

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)


def orthogonal_fit_blocks(count, read, *, chunk_rows, cancel):
    """read 返回完整支持的逻辑区间；不采样、不剔点，返回中心/法向/奇异值/残差。"""
    if (
        type(count) is not int
        or count < 3
        or type(chunk_rows) is not int
        or chunk_rows < 1
    ):
        raise InvalidRequestError("正交拟面需要至少三点和合法块长")
    points = centered = None
    try:
        with np.errstate(over="raise", invalid="raise"):
            cancel()
            anchor = read(0, 1)[0].copy()
            total = np.zeros(3)
            compensation = np.zeros(3)
            for start in range(0, count, chunk_rows):
                cancel()
                points = read(start, min(start + chunk_rows, count))
                addition = (points - anchor).sum(axis=0) - compensation
                new_total = total + addition
                compensation = (new_total - total) - addition
                total = new_total
            relative_center = total / count
            center = anchor + relative_center
            reduced = np.empty((0, 3), dtype=np.float64)
            for start in range(0, count, chunk_rows):
                cancel()
                points = read(start, min(start + chunk_rows, count))
                centered = (points - anchor) - relative_center
                reduced = np.linalg.qr(np.concatenate((reduced, centered)), mode="r")
            _, singular, right = np.linalg.svd(reduced, full_matrices=False)
            normal = right[-1]
            squares, largest = 0.0, 0.0
            for start in range(0, count, chunk_rows):
                cancel()
                points = read(start, min(start + chunk_rows, count))
                residuals = ((points - anchor) - relative_center) @ normal
                squares += float(residuals @ residuals)
                largest = max(largest, float(np.max(np.abs(residuals))))
            points = centered = None
            cancel()
            return center, normal, singular, float(np.sqrt(squares / count)), largest
    except BaseException as error:
        points = centered = None
        release_exception_frames(error)
        raise
