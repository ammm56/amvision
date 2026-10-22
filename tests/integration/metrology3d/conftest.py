"""显式集成套件复用受控依赖的内容身份校验，不静默跳过。"""

from tests.integration.controlled_io.conftest import require_controlled_versions

__all__ = ["require_controlled_versions"]


def pytest_addoption(parser):
    """完整样本显式选择，日常回归不自动读取现场大文件。"""
    parser.addoption("--cloud-sample", default=None)
    parser.addoption("--cloud-report-dir", default=None)
