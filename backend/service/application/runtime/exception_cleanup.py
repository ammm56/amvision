"""保留异常栈位置，同时释放已退栈处理函数持有的大数组和映射视图。"""

from traceback import clear_frames


def release_exception_frames(error: BaseException) -> None:
    """仅清除已退栈帧的局部变量；不抹掉异常原因、消息和 traceback 位置。"""
    pending = [error]
    visited = set()
    while pending:
        failure = pending.pop()
        if id(failure) in visited:
            continue
        visited.add(id(failure))
        clear_frames(failure.__traceback__)
        pending.extend(
            item
            for item in (failure.__cause__, failure.__context__)
            if item is not None
        )
