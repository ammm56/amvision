"""直接编译已核验上游坐标基函数的局部审计，不替代完整 wheel 验收。"""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import shutil
import subprocess


def excerpt(text, start, end):
    """仅截取明确函数边界，算法正文不改写。"""
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def main():
    """源身份必须匹配固定原版或修复版；编译结果保持真实退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--compiler-family", choices=("gnu", "msvc"), default="gnu")
    parser.add_argument("--upstream", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    spec = json.loads(
        (root / "runtimes/python_patches/open3d/manifest.json").read_text("utf-8")
    )
    name = "cpp/open3d/t/geometry/kernel/PointCloudImpl.h"
    header = args.source / name
    with header.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    expected = spec["original_files" if args.upstream else "patched_files"][name]
    if actual != expected:
        raise ValueError("Native frame audit source SHA-256 mismatch")
    for path, checksum in spec["support_files"].items():
        with (args.source / path).open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != checksum:
                raise ValueError(f"Native audit support SHA-256 mismatch: {path}")
    frame = excerpt(
        header.read_text("utf-8"),
        "template <typename scalar_t>\nOPEN3D_HOST_DEVICE void GetCoordinateSystemOnPlane",
        "template <typename scalar_t>\ninline OPEN3D_HOST_DEVICE void Swap",
    )
    matrix = args.source / "cpp/open3d/core/linalg/kernel/Matrix.h"
    cross = excerpt(
        matrix.read_text("utf-8"),
        "template <typename scalar_t>\nOPEN3D_HOST_DEVICE OPEN3D_FORCE_INLINE void cross_3x1",
        "template <typename scalar_t>\nOPEN3D_HOST_DEVICE OPEN3D_FORCE_INLINE scalar_t\ncross_mag_3x1",
    )
    args.work_dir.mkdir(parents=True, exist_ok=False)
    generated = args.work_dir / "boundary_frame_excerpt.h"
    generated.write_text(
        "// Extracted from Open3D (MIT); source hash verified by audit runner.\n"
        "#include <cmath>\n#define OPEN3D_HOST_DEVICE\n#define OPEN3D_FORCE_INLINE inline\n"
        "using std::abs; using std::sqrt;\nnamespace open3d { namespace core { namespace linalg { namespace kernel {\n"
        + cross
        + "\n}}}\n"
        + frame
        + "\n}\n",
        encoding="utf-8",
    )
    shutil.copyfile(args.source / "LICENSE", args.work_dir / "LICENSE.Open3D")
    source = Path(__file__).with_suffix(".cpp")
    executable = (args.work_dir / "frame-audit").resolve()
    if args.compiler_family == "msvc":
        executable = executable.with_suffix(".exe")
        command = [
            args.compiler,
            "/nologo",
            "/std:c++17",
            "/O2",
            "/EHsc",
            f"/I{args.work_dir.resolve()}",
            str(source),
            f"/Fo{args.work_dir.resolve() / 'frame-audit.obj'}",
            f"/Fe{executable}",
        ]
    else:
        command = [
            args.compiler,
            "-std=c++17",
            "-O2",
            "-I",
            str(args.work_dir),
            str(source),
            "-o",
            str(executable),
        ]
    subprocess.run(command, check=True)
    raise SystemExit(subprocess.run([str(executable)]).returncode)


if __name__ == "__main__":
    main()
