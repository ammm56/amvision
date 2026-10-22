"""校验固定上游归档并构建普通 wheel；不联网、不安装、不改现场环境。"""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


def digest(path: Path) -> str:
    """计算文件内容身份。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """要求空构建目录，防止复用污染源或覆盖既有产物。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", choices=("trimesh", "pypcd4"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "runtimes" / "python_patches"
    spec = json.loads((root / "manifest.json").read_text("utf-8"))["packages"][
        args.package
    ]
    if digest(args.archive) != spec["source_sha256"]:
        raise ValueError("Upstream archive SHA-256 mismatch")
    args.work_dir.mkdir(parents=True, exist_ok=False)
    with tarfile.open(args.archive) as archive:
        archive.extractall(args.work_dir, filter="data")
    source = args.work_dir / f"{args.package}-{spec['upstream_version']}"
    for relative, expected in spec["original_files"].items():
        if digest(source / relative) != expected:
            raise ValueError(f"Upstream file SHA-256 mismatch: {relative}")
    patched = {}
    for relative in [*spec["original_files"], *spec.get("added_files", [])]:
        override = root / args.package / relative
        shutil.copyfile(override, source / relative)
        patched[relative] = digest(override)
    shared = root / "shared" / "_strict_records.py"
    shutil.copyfile(shared, source / spec["shared_target"])
    patched[spec["shared_target"]] = digest(shared)
    args.wheel_dir.mkdir(parents=True, exist_ok=True)
    existing = list(args.wheel_dir.glob(f"{args.package}-{spec['version']}-*.whl"))
    if existing:
        raise ValueError("Wheel already exists; use a new output directory")
    temporary = args.work_dir.resolve() / "build-temp"
    temporary.mkdir()
    env = {
        **os.environ,
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "SOURCE_DATE_EPOCH": "1767225600",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(args.wheel_dir.resolve()),
            str(source),
        ],
        check=True,
        env=env,
    )
    (wheel,) = args.wheel_dir.glob(f"{args.package}-{spec['version']}-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        (metadata_path,) = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        if metadata["Name"] != args.package or metadata["Version"] != spec["version"]:
            raise ValueError("Built wheel identity mismatch")
        for relative, expected in patched.items():
            if relative.endswith(".py"):
                actual = archive.read(relative.removeprefix("src/"))
                if hashlib.sha256(actual).hexdigest() != expected:
                    raise ValueError(
                        f"Built wheel omitted or changed patch: {relative}"
                    )
    identity = {
        "package": args.package,
        "version": spec["version"],
        "source_sha256": spec["source_sha256"],
        "patched_files": patched,
        "wheel_sha256": digest(wheel),
        "python": sys.version,
    }
    wheel.with_suffix(".build.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(identity, indent=2))


if __name__ == "__main__":
    main()
