"""发行目录 Python 与 accelerator 校验测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.maintenance import release_runtime_validation


@pytest.mark.parametrize(
    ("tool_output", "expected_version"),
    (
        (b"TensorRT version: 10.16.1\n", "10.16.1"),
        (b"TensorRT.trtexec [TensorRT v101601] [b11]\n", "10.16.1"),
    ),
)
def test_read_trtexec_version_supports_real_output_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_output: bytes,
    expected_version: str,
) -> None:
    """兼容 dotted 版本和 trtexec 使用的六位紧凑版本。"""

    executable = tmp_path / "trtexec.exe"
    executable.write_bytes(b"tool")
    monkeypatch.setattr(
        release_runtime_validation.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=tool_output),
    )

    version, error = release_runtime_validation._read_trtexec_version(executable)

    assert version == expected_version
    assert error is None


def test_read_trtexec_version_reads_banner_before_long_help_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """版本 banner 在长帮助开头时也不能被尾部诊断截断。"""

    executable = tmp_path / "trtexec.exe"
    executable.write_bytes(b"tool")
    monkeypatch.setattr(
        release_runtime_validation.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"[TensorRT v101601]\n" + b"x" * 8192,
        ),
    )

    version, error = release_runtime_validation._read_trtexec_version(executable)

    assert version == "10.16.1"
    assert error is None
