"""只在受控解析器调用边界翻译输入错误，不吞掉取消、依赖或内部故障。"""

from contextlib import contextmanager
import re

from backend.service.application.errors import WorkflowInputError


@contextmanager
def parsing_input(profile_id: str, stage: str):
    """受控版本使用 budget 前缀；保留限额与坏文件的不同错误码。"""
    try:
        yield
    except ValueError as error:
        detail = str(error)
        limited = (
            detail.startswith("budget:")
            or re.fullmatch(
                r"(?:header|body): byte budget exceeded(?: at offset \d+)?", detail
            )
            is not None
        )
        code = "limit_exceeded" if limited else f"{stage}_invalid"
        raise WorkflowInputError(
            "点云文件超过显式读取限额"
            if limited
            else (
                "点云文件头不合法"
                if stage == "header"
                else "点云文件数据不完整或不合法"
            ),
            code=f"workflow_input_point_cloud_{code}",
            details={
                "profile_id": profile_id,
                "stage": stage,
                "parser_error": detail[:512],
            },
        ) from error


def format_mismatch(profile_id: str, expected: str, actual: str):
    """错误编码必须明确拒绝，不猜测或切换读取器。"""
    return WorkflowInputError(
        "点云文件编码与读取配置不一致",
        code="workflow_input_point_cloud_format_mismatch",
        details={
            "profile_id": profile_id,
            "stage": "header",
            "expected_encoding": expected,
            "actual_encoding": actual,
        },
    )
