"""页面验收入口不能误用业务端口或复用既有运行目录。"""

import sys

import pytest

from tests.integration.metrology3d.published_ui import main


@pytest.mark.parametrize("port", [5600, 5601, 0, 65536])
def test_isolated_ui_rejects_business_or_invalid_port(tmp_path, monkeypatch, port):
    """校验失败发生在创建目录和启动服务之前。"""
    root = tmp_path / "not-created"
    monkeypatch.setattr(
        sys, "argv", ["published_ui", "--root", str(root), "--port", str(port)]
    )
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2
    assert not root.exists()


def test_isolated_ui_rejects_existing_root(tmp_path, monkeypatch):
    """不覆盖已有数据库、测试输入或其他资产。"""
    monkeypatch.setattr(
        sys, "argv", ["published_ui", "--root", str(tmp_path), "--port", "5620"]
    )
    with pytest.raises(FileExistsError):
        main()
    assert list(tmp_path.iterdir()) == []
