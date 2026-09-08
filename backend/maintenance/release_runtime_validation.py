"""发行目录 bundled Python 与加速器环境校验。"""

from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys

from packaging.requirements import InvalidRequirement, Requirement
from backend.maintenance.launcher_release import validate_launcher_package


def validate_release_runtime(
    *,
    app_root: Path,
    release_manifest: dict[str, object],
) -> dict[str, object]:
    """校验当前发行目录正在使用的 Python、依赖和 accelerator。"""

    issues: list[str] = []
    if release_manifest.get("desktop_launcher") is not None:
        try:
            validate_launcher_package(app_root)
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append(f"桌面启动器发行文件校验失败: {error}")
    expected_python = (app_root / "python" / "python.exe").resolve()
    actual_python = Path(sys.executable).resolve()
    if os.path.normcase(str(actual_python)) != os.path.normcase(str(expected_python)):
        issues.append(
            "validate-layout 必须由当前发行目录的 python/python.exe 执行: "
            f"actual={actual_python}"
        )
    if sys.version_info[:2] != (3, 12):
        issues.append(
            "bundled Python 必须为 3.12: "
            f"actual={sys.version_info.major}.{sys.version_info.minor}"
        )
    pointer_bits = struct.calcsize("P") * 8
    if pointer_bits != 64:
        issues.append(f"bundled Python 必须为 64-bit: actual={pointer_bits}")
    machine = platform.machine().strip().lower()
    if machine not in {"amd64", "x86_64"}:
        issues.append(f"bundled Python 架构必须为 x64: actual={machine or 'unknown'}")
    if os.name != "nt":
        issues.append(f"当前发行 profile 只支持 Windows: actual={os.name}")

    requirements_path = app_root / "app" / "requirements.txt"
    requirement_issues = _validate_installed_requirements(requirements_path)
    issues.extend(requirement_issues)

    accelerator_section = release_manifest.get("accelerator")
    accelerator_section = (
        accelerator_section if isinstance(accelerator_section, dict) else {}
    )
    accelerator_kind = str(accelerator_section.get("kind") or "").strip().lower()
    accelerator_result = _validate_accelerator(
        app_root=app_root,
        accelerator_kind=accelerator_kind,
    )
    issues.extend(str(item) for item in accelerator_result.pop("issues"))
    return {
        "valid": not issues,
        "python_executable": str(actual_python),
        "python_version": platform.python_version(),
        "pointer_bits": pointer_bits,
        "machine": machine,
        "requirements_valid": not requirement_issues,
        "accelerator": accelerator_result,
        "issues": issues,
    }


def _validate_installed_requirements(requirements_path: Path) -> list[str]:
    """检查 requirements 中的直接依赖是否已安装且版本满足约束。"""

    if not requirements_path.is_file():
        return [f"requirements 文件不存在: {requirements_path}"]
    issues: list[str] = []
    for line_number, raw_line in enumerate(
        requirements_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            issues.append(f"requirements 第 {line_number} 行格式无效: {line}")
            continue
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            installed_version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            issues.append(f"缺少 Python 依赖: {requirement.name}")
            continue
        if requirement.specifier and installed_version not in requirement.specifier:
            issues.append(
                "Python 依赖版本不匹配: "
                f"{requirement.name}={installed_version}, expected={requirement.specifier}"
            )
    return issues


def _validate_accelerator(
    *,
    app_root: Path,
    accelerator_kind: str,
) -> dict[str, object]:
    """校验 torch、CUDA、cuDNN 与 TensorRT 是否匹配当前 profile。"""

    issues: list[str] = []
    result: dict[str, object] = {"kind": accelerator_kind, "issues": issues}
    try:
        import torch
    except Exception as error:  # noqa: BLE001 - 发布校验必须返回完整诊断
        issues.append(f"PyTorch 导入失败: {error}")
        return result

    torch_cuda_version = torch.version.cuda
    result.update(
        {
            "torch_version": torch.__version__,
            "torch_cuda_version": torch_cuda_version,
            "cuda_available": bool(torch.cuda.is_available()),
            "cudnn_version": torch.backends.cudnn.version(),
        }
    )
    if accelerator_kind == "cpu":
        if torch_cuda_version is not None:
            issues.append(
                "CPU profile 必须使用 CPU-only PyTorch: "
                f"torch.version.cuda={torch_cuda_version}"
            )
        return result
    if accelerator_kind != "nvidia":
        issues.append(f"未知 accelerator kind: {accelerator_kind or 'empty'}")
        return result
    if torch_cuda_version is None:
        issues.append("NVIDIA profile 使用了 CPU-only PyTorch")
    if not torch.cuda.is_available():
        issues.append("NVIDIA profile 无法访问 CUDA 设备")
    if torch.backends.cudnn.version() is None:
        issues.append("NVIDIA profile 无法加载 cuDNN")

    try:
        import tensorrt
    except Exception as error:  # noqa: BLE001 - 发布校验必须返回完整诊断
        issues.append(f"TensorRT Python 导入失败: {error}")
        return result
    tensorrt_version = str(tensorrt.__version__)
    result["tensorrt_python_version"] = tensorrt_version
    trtexec_path = app_root / "tools" / "tensorrt" / "bin" / "trtexec.exe"
    trtexec_version, trtexec_error = _read_trtexec_version(trtexec_path)
    result["trtexec_version"] = trtexec_version
    if trtexec_error is not None:
        issues.append(trtexec_error)
    elif _version_prefix(tensorrt_version) != _version_prefix(trtexec_version or ""):
        issues.append(
            "TensorRT Python 与 trtexec 版本不一致: "
            f"python={tensorrt_version}, trtexec={trtexec_version}"
        )
    cudnn_bin_dir = os.getenv("AMVISION_CUDNN_BIN_DIR", "").strip()
    result["cudnn_bin_dir"] = cudnn_bin_dir or None
    if not cudnn_bin_dir or not any(Path(cudnn_bin_dir).glob("cudnn64_*.dll")):
        issues.append("launcher 未解析到包含 cuDNN DLL 的目录")
    return result


def _read_trtexec_version(executable_path: Path) -> tuple[str | None, str | None]:
    """读取发行包 trtexec 的版本号。"""

    if not executable_path.is_file():
        return None, f"trtexec 不存在: {executable_path}"
    try:
        completed = subprocess.run(
            [str(executable_path), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"trtexec 版本检查失败: {error}"
    output = completed.stdout.decode("utf-8", errors="replace")
    match = re.search(
        r"(?:TensorRT\s+v?|version[:\s]+)(\d+(?:\.\d+){1,3})",
        output,
        re.I,
    )
    compact_match = re.search(r"TensorRT\s+v(\d{6})", output, re.I)
    version = match.group(1) if match is not None else None
    if version is None and compact_match is not None:
        compact_version = compact_match.group(1)
        version = ".".join(
            str(int(compact_version[index : index + 2]))
            for index in range(0, 6, 2)
        )
    if completed.returncode != 0 or version is None:
        diagnostic_output = output[-4096:].strip()
        return None, (
            "trtexec 无法返回有效版本: "
            f"returncode={completed.returncode}, output={diagnostic_output}"
        )
    return version, None


def _version_prefix(version: str) -> tuple[int, ...]:
    """取版本号前三段用于 Python wheel 与原生工具对齐。"""

    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version.strip())
    return tuple(int(part) for part in match.groups()) if match is not None else ()
