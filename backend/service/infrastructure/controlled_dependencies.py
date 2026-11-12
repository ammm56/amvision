"""校验数据集和节点共同使用的受控第三方发行版本。"""

from importlib.metadata import PackageNotFoundError, version

from backend.service.application.errors import ServiceConfigurationError


def require_controlled_distribution(name: str, expected: str) -> None:
    """要求 name 的发行版本等于 expected；缺失或错配不降级读取。"""
    try:
        actual = version(name)
    except PackageNotFoundError:
        actual = None
    if actual != expected:
        raise ServiceConfigurationError(
            "点云读取依赖不满足受控版本要求",
            details={
                "distribution": name,
                "expected_version": expected,
                "actual_version": actual,
            },
        )
