"""前后端回归使用同一份当前 Catalog 字段，不允许 fixture 悄悄漂移。"""

import json

from tests.integration.metrology3d.parameter_ui_fixture import (
    FIXTURE,
    parameter_ui_fixture,
)


def test_parameter_ui_fixture_matches_current_catalog():
    """契约变化必须同批更新前端真实分发回归输入。"""
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == parameter_ui_fixture()
