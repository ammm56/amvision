"""数据集扫描和校验使用的结构化问题对象。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


DatasetIssueSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class DatasetIssue:
    """描述一条可稳定定位的数据集问题。"""

    code: str
    severity: DatasetIssueSeverity
    message: str
    file: str | None = None
    location: str | None = None
    sample: str | None = None
    annotation: str | None = None
    field_name: str | None = None
    actual: object | None = None
    expected: object | None = None
    suggestion: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """序列化问题并移除没有值的可选字段。"""

        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None and value != {}
        }


class DatasetIssueCollector:
    """有上限地收集问题，避免损坏数据集制造无界内存占用。"""

    def __init__(self, *, max_retained_issues: int = 1000) -> None:
        if max_retained_issues <= 0:
            raise ValueError("max_retained_issues 必须大于 0")
        self.max_retained_issues = max_retained_issues
        self._issues: list[DatasetIssue] = []
        self.total_count = 0
        self.error_count = 0
        self.warning_count = 0

    def add(self, issue: DatasetIssue) -> None:
        """记录一条问题；达到保留上限后只继续累计数量。"""

        self.total_count += 1
        if issue.severity == "error":
            self.error_count += 1
        else:
            self.warning_count += 1
        if len(self._issues) < self.max_retained_issues:
            self._issues.append(issue)

    @property
    def issues(self) -> tuple[DatasetIssue, ...]:
        """返回当前保留的问题。"""

        return tuple(self._issues)

    def serialize(self, *, severity: DatasetIssueSeverity | None = None) -> list[dict[str, object]]:
        """按可选严重程度序列化当前保留的问题。"""

        return [
            issue.to_dict()
            for issue in self._issues
            if severity is None or issue.severity == severity
        ]

    def summary(self) -> dict[str, object]:
        """返回问题数量和截断状态。"""

        return {
            "issue_count": self.total_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "retained_issue_count": len(self._issues),
            "issues_truncated": self.total_count > len(self._issues),
        }
