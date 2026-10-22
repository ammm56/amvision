"""本项目受控 wheel 身份，不伪装上游原版。"""

from importlib.metadata import version as distribution_version

__version__ = version = distribution_version("pypcd4")
