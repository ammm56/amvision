"""离线构建入口必须先验来源，再创建工作目录。"""

from pathlib import Path
import subprocess
import sys


def test_wrong_source_hash_cannot_build(tmp_path):
    """坏归档不能被解压，也不能调用构建后端。"""
    source = tmp_path / "wrong.tar.gz"
    source.write_bytes(b"not an upstream archive")
    workspace = tmp_path / "build"
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "build_controlled_python.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "trimesh",
            "--archive",
            str(source),
            "--work-dir",
            str(workspace),
            "--wheel-dir",
            str(tmp_path / "wheels"),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "SHA-256 mismatch" in result.stderr
    assert not workspace.exists()
