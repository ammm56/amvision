"""RF-DETR core 工具函数模块：`utilities.logger`。"""

import logging
import os
import sys


class _RFDETRLogger(logging.Logger):
    """RF-DETR core 类：`_RFDETRLogger`。"""

    def __init__(self, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level)
        self._warned_once: set[str] = set()

    def warning_once(self, msg: str, *args: object, **kwargs: object) -> None:
        """执行 `warning_once`。
        
        参数：
        - `msg`：传入的 `msg` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if msg not in self._warned_once:
            self._warned_once.add(msg)
            self.warning(msg, *args, **kwargs)


def get_logger(name: str = "rf-detr", level: int | None = None) -> _RFDETRLogger:
    """执行 `get_logger`。
    
    参数：
    - `name`：传入的 `name` 参数。
    - `level`：传入的 `level` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if level is None:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    logger = logging.getLogger(name)

    if not isinstance(logger, _RFDETRLogger):
        logger.__class__ = _RFDETRLogger
        logger._warned_once = set()  # type: ignore[attr-defined]

    logger.setLevel(level)

    if not logger.handlers:
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.addFilter(lambda r: r.levelno <= logging.INFO)
        stdout_handler.setFormatter(formatter)

        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        stderr_handler.setFormatter(formatter)

        logger.addHandler(stdout_handler)
        logger.addHandler(stderr_handler)
        logger.propagate = False

    return logger  # type: ignore[return-value]


