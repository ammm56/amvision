"""发行默认同源、显式分离地址与开发 local 配置的隔离契约。"""

import json
from pathlib import Path

from backend.maintenance.release_assembly import ReleaseAssemblyRequest, _copy_frontend_assets


def test_release_keeps_template_and_drops_development_local_config(tmp_path: Path) -> None:
    """开发机 local 文件不能令默认发行误连另一套实例。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("test", encoding="utf-8")
    (dist / "runtime-config.local.json").write_text('{"apiBaseUrl":"http://old-host/api/v1"}', encoding="utf-8")
    template = tmp_path / "template.json"
    template.write_text('{"apiBaseUrl":"http://127.0.0.1:5600/api/v1"}', encoding="utf-8")
    output = tmp_path / "release"
    request = ReleaseAssemblyRequest(profile_id="full-windows-x64-cpu", output_root=tmp_path,
                                     frontend_dist_dir=dist, frontend_runtime_config_template_file=template)
    _copy_frontend_assets(output, request=request)
    assert (output / "frontend/runtime-config.template.json").is_file()
    assert not (output / "frontend/runtime-config.json").exists()
    assert not (output / "frontend/runtime-config.local.json").exists()


def test_explicit_release_config_takes_precedence(tmp_path: Path) -> None:
    """显式发行配置可以覆盖 dist 中旧配置，地址不被改成同源。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("test", encoding="utf-8")
    (dist / "runtime-config.json").write_text('{"apiBaseUrl":"old"}', encoding="utf-8")
    explicit = tmp_path / "explicit.json"
    payload = {"apiBaseUrl": "https://separate-host/api/v1", "wsBaseUrl": "wss://separate-host/ws/v1"}
    explicit.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "release"
    request = ReleaseAssemblyRequest(profile_id="full-windows-x64-cpu", output_root=tmp_path,
                                     frontend_dist_dir=dist, frontend_runtime_config_source_file=explicit)
    _copy_frontend_assets(output, request=request)
    assert json.loads((output / "frontend/runtime-config.json").read_text()) == payload
