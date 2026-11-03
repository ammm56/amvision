"""Workflow 子进程内部数值库线程配置。"""

from __future__ import annotations

import os

from threadpoolctl import threadpool_limits


_blas_thread_limit: threadpool_limits | None = None


def configure_workflow_process_threads(operator_thread_count: int) -> None:
    """在 Workflow 子进程启动时配置已加载和后续加载的 OpenCV/BLAS。"""

    global _blas_thread_limit
    thread_count = max(1, int(operator_thread_count))
    os.environ["OMP_NUM_THREADS"] = str(thread_count)
    os.environ["MKL_NUM_THREADS"] = str(thread_count)
    os.environ["OPENBLAS_NUM_THREADS"] = str(thread_count)
    os.environ["NUMEXPR_NUM_THREADS"] = str(thread_count)
    # spawn 导入 target 的依赖时可能已加载 NumPy；环境变量只约束后续加载的库。
    # 在进程入口设置常驻限制，不在并发节点中进入/退出临时线程上下文。
    _blas_thread_limit = threadpool_limits(limits=thread_count, user_api="blas")
    try:
        import cv2  # noqa: PLC0415

        cv2.setNumThreads(thread_count)
    except Exception:
        # OpenCV 是可选节点依赖，未安装时不阻止非视觉 Workflow 启动。
        pass
