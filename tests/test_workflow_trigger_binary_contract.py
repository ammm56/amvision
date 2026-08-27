"""Workflow Trigger mailbox 阶段 0 binary contract 门禁。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from backend.contracts.ipc import workflow_trigger_mailbox_v1 as contract
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapGuardFileError,
    MmapOwnerLockBusyError,
    acquire_mmap_guard,
    acquire_mmap_owner_lock,
    MmapPageChainError,
    build_contained_mmap_path,
    publish_u32,
    read_page_chain,
    release_mmap_owner_lock,
    select_page_indices,
    try_lock_byte_range_file,
    unlock_byte_range_file,
)
from backend.service.infrastructure.ipc.local_message.paths import (
    build_workflow_trigger_mailbox_paths,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "backend"
    / "contracts"
    / "ipc"
    / "schemas"
    / "workflow_trigger_mailbox.v1.json"
)
FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "workflow_trigger_mailbox.v1.fixture.json"
)
DOTNET_PROJECT = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "Amvar.Vision.ContractTests.vs2019.net472.csproj"
)
DOTNET_PROBE = (
    DOTNET_PROJECT.parent
    / "bin"
    / "Release"
    / "net472"
    / "Amvar.Vision.ContractTests.exe"
)


def test_binary_contract_schema_python_and_fixture_are_current() -> None:
    """Trigger schema、Python packer 和 fixture 必须逐字节一致。"""

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["contract_id"] == contract.CONTRACT_ID
    assert schema["contract_id"] == contract.CONTRACT_ID
    assert fixture["relative_mmap_path"] == contract.RELATIVE_MMAP_PATH
    assert fixture["relative_guard_path"] == contract.RELATIVE_GUARD_PATH
    assert schema["relative_mmap_path"] == contract.RELATIVE_MMAP_PATH
    assert schema["relative_guard_path"] == contract.RELATIVE_GUARD_PATH
    assert schema["base_contract_id"] == "amvision.local-message-channel.v1"
    assert schema["descriptor_extension"]["offset"] == 104
    assert schema["descriptor_extension"]["size"] == 152
    packed = contract.pack_descriptor_extension(**fixture["values"])
    assert packed.hex() == fixture["packed_hex"]
    assert len(packed) == 152


def test_workflow_trigger_paths_are_contained_by_buffers_root(tmp_path: Path) -> None:
    """正式 mmap、owner lock 与统一 byte-range guard 只能位于中立 root。"""

    buffers_root = tmp_path / "data" / "buffers"
    paths = build_workflow_trigger_mailbox_paths(buffers_root=buffers_root)
    assert paths.mmap_path == (
        buffers_root / "local-message" / "workflow-trigger" / "mailbox.mmap"
    ).resolve()
    assert paths.mmap_path.is_relative_to(buffers_root.resolve())
    assert paths.owner_lock_path.name == "owner.lock"
    assert paths.guard_path.name == "access.guard"
    with pytest.raises(ValueError, match="relative_path"):
        build_contained_mmap_path(
            root_dir=buffers_root,
            relative_path=paths.mmap_path,
        )
    with pytest.raises(ValueError, match="配置 root"):
        build_contained_mmap_path(root_dir=buffers_root, relative_path="../escape.mmap")


def test_neutral_page_chain_prefers_contiguous_and_survives_fragmentation() -> None:
    """page 分配连续优先，碎片化时仍能构造非连续链。"""

    assert select_page_indices(free_page_indices=[0, 2, 3, 4, 8], page_count=3) == (
        2,
        3,
        4,
    )
    assert select_page_indices(free_page_indices=[0, 2, 4, 8], page_count=3) == (
        0,
        2,
        4,
    )
    assert select_page_indices(free_page_indices=[0, 1], page_count=3) == ()

    headers = {0: (2, "page-0"), 2: (4, "page-2"), 4: (-1, "page-4")}
    assert read_page_chain(
        first_page_index=0,
        expected_page_count=3,
        total_page_count=8,
        no_page_index=-1,
        read_header=lambda page_index: headers[page_index],
    ) == ((0, "page-0"), (2, "page-2"), (4, "page-4"))


@pytest.mark.parametrize(
    ("headers", "reason"),
    (
        ({0: (0, "page-0")}, "cycle_or_out_of_bounds"),
        ({0: (-1, "page-0")}, "ended_early"),
        ({0: (1, "page-0"), 1: (2, "page-1")}, "too_long"),
    ),
)
def test_neutral_page_chain_rejects_invalid_shape(
    headers: dict[int, tuple[int, str]],
    reason: str,
) -> None:
    """page-chain 循环、提前结束和过长必须返回稳定原因。"""

    with pytest.raises(MmapPageChainError) as captured:
        read_page_chain(
            first_page_index=0,
            expected_page_count=2,
            total_page_count=8,
            no_page_index=-1,
            read_header=lambda page_index: headers[page_index],
        )
    assert captured.value.reason == reason


def test_neutral_publication_writes_only_little_endian_state() -> None:
    """最终 publication 只覆盖目标 uint32，不改变相邻 body。"""

    buffer = bytearray(b"abcdefgh12345678")
    publish_u32(buffer, offset=8, value=0x11223344)
    assert buffer == b"abcdefgh\x44\x33\x22\x115678"


def test_neutral_owner_lock_fences_second_owner_and_allows_takeover(
    tmp_path: Path,
) -> None:
    """owner handle 存活时禁止第二 owner，释放后允许新 epoch 接管。"""

    lock_path = tmp_path / "workflow-trigger-main.mmap.owner.lock"
    first_owner = acquire_mmap_owner_lock(lock_path)
    try:
        with pytest.raises(MmapOwnerLockBusyError):
            acquire_mmap_owner_lock(lock_path)
        if os.name == "nt":
            with pytest.raises(PermissionError):
                lock_path.unlink()
    finally:
        release_mmap_owner_lock(first_owner)
    second_owner = acquire_mmap_owner_lock(lock_path)
    release_mmap_owner_lock(second_owner)
    release_mmap_owner_lock(second_owner)
    assert second_owner.released is True
    lock_path.unlink()


def test_guard_client_never_creates_or_expands_guard_file(tmp_path: Path) -> None:
    """client 只能使用 owner 已创建的固定 guard，缺失或过短均 fail-closed。"""

    guard_path = tmp_path / "access.guard"
    with pytest.raises(MmapGuardFileError, match="不存在"):
        with acquire_mmap_guard(
            guard_path=guard_path,
            deadline_ns=time.monotonic_ns() + 1_000_000,
            poll_interval_seconds=0.0001,
            offset=0,
            length=1,
        ):
            pass
    assert not guard_path.exists()

    guard_path.write_bytes(b"\0")
    with pytest.raises(MmapGuardFileError, match="长度不足"):
        with acquire_mmap_guard(
            guard_path=guard_path,
            deadline_ns=time.monotonic_ns() + 1_000_000,
            poll_interval_seconds=0.0001,
            offset=1,
            length=1,
        ):
            pass
    assert guard_path.stat().st_size == 1


def _build_dotnet_probe() -> Path:
    """编译真实 net472 SDK 契约 probe。"""

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("未安装 dotnet/MSBuild")
    build = subprocess.run(
        [
            dotnet,
            "msbuild",
            str(DOTNET_PROJECT),
            "/t:Rebuild",
            "/p:Configuration=Release",
            "/p:TreatWarningsAsErrors=true",
            "/v:minimal",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert DOTNET_PROBE.is_file()
    return DOTNET_PROBE


@pytest.mark.skipif(os.name != "nt", reason="跨语言 byte-range lock 门禁仅适用于 Windows")
def test_python_and_dotnet_byte_range_guards_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    """Python msvcrt.locking 与 .NET FileStream.Lock 必须真实跨进程互斥。"""

    probe = _build_dotnet_probe()
    guard_path = tmp_path / "descriptor.guard"
    ready_path = tmp_path / "ready"
    holder = subprocess.Popen(
        [str(probe), "--hold-byte-lock", str(guard_path), str(ready_path), "5000"],
        cwd=ROOT,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready_path.exists(), "等待 .NET guard holder 超时"
        with pytest.raises(PermissionError):
            guard_path.unlink()
        with guard_path.open("a+b", buffering=0) as guard_file:
            with pytest.raises(BlockingIOError):
                try_lock_byte_range_file(guard_file)
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    with guard_path.open("a+b", buffering=0) as guard_file:
        try_lock_byte_range_file(guard_file)
        try:
            contender = subprocess.run(
                [str(probe), "--try-byte-lock", str(guard_path)],
                cwd=ROOT,
                timeout=10,
                check=False,
            )
            assert contender.returncode == 2
        finally:
            unlock_byte_range_file(guard_file)

    released = subprocess.run(
        [str(probe), "--try-byte-lock", str(guard_path)],
        cwd=ROOT,
        timeout=10,
        check=False,
    )
    assert released.returncode == 0
