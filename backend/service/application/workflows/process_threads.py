"""Workflow 子进程内部数值库线程配置。"""

from __future__ import annotations

import os


def configure_workflow_process_threads(operator_thread_count: int) -> None:
    """在 Workflow 子进程启动时一次性设置 OpenCV/BLAS 线程上限。"""

    thread_count = max(1, int(operator_thread_count))
    os.environ["OMP_NUM_THREADS"] = str(thread_count)
    os.environ["MKL_NUM_THREADS"] = str(thread_count)
    os.environ["OPENBLAS_NUM_THREADS"] = str(thread_count)
    os.environ["NUMEXPR_NUM_THREADS"] = str(thread_count)
    try:
        import cv2  # noqa: PLC0415

        cv2.setNumThreads(thread_count)
    except Exception:
        # OpenCV 是可选节点依赖，未安装时不阻止非视觉 Workflow 启动。
        pass
