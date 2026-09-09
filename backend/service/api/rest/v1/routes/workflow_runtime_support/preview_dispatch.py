"""将 Preview 阻塞操作移出 HTTP loop，并保留取消时的资源所有权。"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Awaitable, Callable, TypeVar

from anyio import to_thread


T = TypeVar("T")


async def run_preview_blocking(function: Callable[..., T], *args, **kwargs) -> T:
    """等待线程真正结束后传播取消，调用方 finally 才可以释放其输入。"""

    return await wait_preview_completion(to_thread.run_sync(partial(function, *args, **kwargs)))


async def wait_preview_completion(operation: Awaitable[T]) -> T:
    """屏蔽请求取消直到执行与清理闭环完成，不遗留仍持有上传资源的后台任务。"""

    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        # 取出异常，避免遗留无人观察的 Task；取消仍是请求的最终结果。
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()
