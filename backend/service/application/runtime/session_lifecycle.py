"""模型 runtime session 的统一释放边界。"""

from __future__ import annotations

from typing import Any


class RuntimeSessionLease:
    """代理 runtime session，并保证显式或离开作用域时幂等释放。"""

    def __init__(self, session: Any) -> None:
        """接管一个已创建的 runtime session。"""

        self._session = session
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        """把 predict 等协议调用转发给底层 session。"""

        return getattr(self._session, name)

    def close(self) -> None:
        """幂等释放底层 session，并清理模型与 GPU 缓存引用。"""

        if self._closed:
            return
        self._closed = True
        session = self._session
        self._session = None
        try:
            close_session = getattr(session, "close", None)
            if callable(close_session):
                close_session()
        finally:
            del session
            from backend.service.application.support.resource_cleanup import (
                release_model_task_resources,
            )

            release_model_task_resources()

    def __enter__(self) -> "RuntimeSessionLease":
        """进入受控 session 生命周期。"""

        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """离开上下文时释放底层 session。"""

        del exc_type, exc, traceback
        self.close()

    def __del__(self) -> None:
        """异常路径未显式关闭时执行最终兜底。"""

        try:
            self.close()
        except Exception:
            pass


__all__ = ["RuntimeSessionLease"]
