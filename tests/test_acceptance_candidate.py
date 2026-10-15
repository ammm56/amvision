"""冻结候选必须发现源码被改动、删除及无效清单。"""
import pytest
import os
import subprocess
from tests.integration.acceptance_candidate import file_digest, inventory_files, verify_candidate
from tests.integration.acceptance_evidence import write_evidence


def test_candidate_detects_modified_and_deleted_file(tmp_path):
    """同名文件变化也必须失败，不能只比较路径或提交号。"""
    source = tmp_path / "runtime" / "source.py"
    source.parent.mkdir()
    source.write_text("before")
    manifest = tmp_path / "candidate.json"
    _freeze(manifest, source.parent)
    assert verify_candidate(manifest)["status"] == "passed"
    source.write_text("after")
    assert verify_candidate(manifest)["status"] == "failed"
    source.unlink()
    assert verify_candidate(manifest)["status"] == "failed"


def test_candidate_rejects_empty_manifest(tmp_path):
    """空清单不构成验收候选证据。"""
    manifest = tmp_path / "candidate.json"
    write_evidence(manifest, {"format_id": "amvision.acceptance-candidate.v1", "files": []})
    with pytest.raises(ValueError):
        verify_candidate(manifest)


def _freeze(manifest, root):
    """构造含显式目录边界的 v2 清单。"""
    inventory = {"trees": [{"path": str(root), "exclude_directories": ["__pycache__"]}],
                 "files": [], "globs": []}
    write_evidence(manifest, {"format_id": "amvision.acceptance-candidate.v2", "inventory": inventory,
                             "files": [file_digest(path) for path in sorted(inventory_files(inventory))]})


def test_candidate_detects_added_runtime_file_but_excludes_bytecode(tmp_path):
    """新增运行时文件必须失败，正常字节码缓存不使冻结失效。"""
    root = tmp_path / "custom_nodes"
    root.mkdir()
    (root / "existing.py").write_text("value = 1")
    manifest = tmp_path / "candidate.json"
    _freeze(manifest, root)
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "existing.pyc").write_bytes(b"cache")
    assert verify_candidate(manifest)["status"] == "passed"
    added = root / "new_node.py"
    added.write_text("value = 2")
    assert verify_candidate(manifest)["added"] == [str(added)]
    assert verify_candidate(manifest)["status"] == "failed"


def test_candidate_detects_previously_absent_tree(tmp_path):
    """冻结时尚未存在的扩展目录也不能成为新增文件的盲区。"""
    source = tmp_path / "source.py"
    source.write_text("1")
    root = tmp_path / "custom_nodes"
    inventory = {"trees": [{"path": str(root), "exclude_directories": []}],
                 "files": [str(source)], "globs": []}
    manifest = tmp_path / "candidate.json"
    write_evidence(manifest, {"format_id": "amvision.acceptance-candidate.v2", "inventory": inventory,
                             "files": [file_digest(source)]})
    assert verify_candidate(manifest)["status"] == "passed"
    root.mkdir()
    (root / "new.py").write_text("1")
    assert verify_candidate(manifest)["status"] == "failed"


def test_candidate_requires_inventory_and_rejects_legacy(tmp_path):
    """旧格式和没有扫描范围的清单不能提供完整认证。"""
    source = tmp_path / "source.py"
    source.write_text("1")
    manifest = tmp_path / "candidate.json"
    for version in ("v1", "v2"):
        write_evidence(manifest, {"format_id": f"amvision.acceptance-candidate.{version}", "files": [file_digest(source)]})
        with pytest.raises(ValueError):
            verify_candidate(manifest)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 边界")
def test_candidate_rejects_junction_added_after_freeze(tmp_path):
    """新增 junction 不能使冻结扫描跳出边界，也不能被当作已排除缓存。"""
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "source.py").write_text("1")
    target = tmp_path / "outside"
    target.mkdir()
    manifest = tmp_path / "candidate.json"
    _freeze(manifest, root)
    link = root / "__pycache__"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match="链接"):
            verify_candidate(manifest)
    finally:
        link.rmdir()
