"""后端托管 Vue 构建时，默认模板跟随访问来源，显式配置保持优先级。"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.service.api.app import FrontendStaticFiles


@pytest.mark.parametrize("base_url,ws_base", [
    ("http://testserver:18360", "ws://testserver:18360"),
    ("https://vision.example", "wss://vision.example"),
])
def test_template_uses_current_origin(tmp_path, base_url, ws_base) -> None:
    """非默认端口及 HTTPS 页面不能回连开发机 5600 端口。"""
    template = {"apiBaseUrl": "http://127.0.0.1:5600/api/v1", "wsBaseUrl": "ws://127.0.0.1:5600/ws/v1", "features": {"workflowEditor": True}}
    (tmp_path / "runtime-config.template.json").write_text(json.dumps(template), encoding="utf-8")
    app = FastAPI()
    app.mount("/", FrontendStaticFiles(directory=tmp_path))
    with TestClient(app, base_url=base_url) as client:
        response = client.get("/runtime-config.json")
    assert response.status_code == 200
    assert response.json() == {**template, "apiBaseUrl": base_url + "/api/v1", "wsBaseUrl": ws_base + "/ws/v1"}
    assert response.headers["cache-control"] == "no-store"
    assert json.loads((tmp_path / "runtime-config.template.json").read_text()) == template


@pytest.mark.parametrize("filename", ["runtime-config.json", "runtime-config.local.json"])
def test_explicit_runtime_config_is_preserved(tmp_path, filename) -> None:
    """显式远程后端配置不因同源默认策略而被覆盖。"""
    payload = {"apiBaseUrl": "https://other.example/api/v1", "wsBaseUrl": "wss://other.example/ws/v1"}
    (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "runtime-config.template.json").write_text("{}", encoding="utf-8")
    app = FastAPI()
    app.mount("/", FrontendStaticFiles(directory=tmp_path))
    with TestClient(app) as client:
        assert client.get("/runtime-config.json").json() == payload
