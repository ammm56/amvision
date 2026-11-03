"""三维发行依赖沿节点 manifest 锁定，复用受控 wheel，不安装或联网。"""

from hashlib import file_digest
from importlib import import_module, metadata
import json
from pathlib import Path
import shutil

from packaging.requirements import Requirement


def _verify_file(path: Path, expected: str) -> None:
    """以 SHA256 核对单个发行资产。"""
    with path.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError(f"发行资产摘要不匹配: {path.name}")


def copy_native_libraries(source: Path, target: Path, platform: str) -> dict | None:
    """复用本地原生资产，装配器不在客户机下载或安装系统包。"""
    if platform != "ubuntu-x64":
        return None
    manifest = source / "runtimes/manifests/native-libraries/ubuntu-x64.json"
    descriptor = json.loads(manifest.read_text("utf-8"))
    destination = target / "tools/native/lib"
    destination.mkdir(parents=True)
    for name, digest in descriptor["files"].items():
        if Path(name).name != name:
            raise ValueError("原生资产文件名越界")
        path = source / "runtimes/third_party/native/ubuntu-x64" / name
        _verify_file(path, digest)
        shutil.copy2(path, destination / name)
    shutil.copy2(manifest, destination.parent / "manifest.json")
    return descriptor


def copy_metrology_dependencies(source: Path, target: Path) -> dict:
    """装配可审核的锁定清单和受控包；普通依赖由构建机安装到随包 Python。"""
    manifest = json.loads(
        (source / "custom_nodes/metrology3d_nodes/manifest.json").read_text("utf-8")
    )
    requirements = manifest["compatibility"]["pythonDistributions"]
    wheels = []
    for name in ("trimesh", "pypcd4"):
        requirement = next(
            Requirement(item) for item in requirements if Requirement(item).name == name
        )
        version = next(iter(requirement.specifier)).version
        filename = f"{name}-{version}-py3-none-any.whl"
        wheel = source / "runtimes/third_party/python-io" / filename
        build = wheel.with_suffix(".build.json")
        expected = json.loads(build.read_text("utf-8"))["wheel_sha256"]
        with wheel.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"受控 wheel 摘要不匹配: {filename}")
        destination = target / "tools/wheels" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wheel, destination)
        shutil.copy2(build, destination.with_suffix(".build.json"))
        wheels.append(
            dict(path=destination.relative_to(target).as_posix(), sha256=expected)
        )
    # 唯一版本来源仍为节点 manifest，避免 requirements 和节点启用条件各维护一份。
    with (target / "app/requirements.txt").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n# 3D Metrology: generated from node manifest\n"
            + "\n".join(requirements)
            + "\n"
        )
    return dict(
        node_pack_id=manifest["id"],
        version=manifest["version"],
        requirements=requirements,
        wheels=wheels,
    )


def validate_metrology_runtime(root: Path, release: dict) -> dict:
    """检查锁定版本与加载路径，并实际执行三维原生调用，不以 metadata 代替加载。"""
    issues, versions = [], {}
    try:
        pack = json.loads(
            (root / "custom_nodes/metrology3d_nodes/manifest.json").read_text("utf-8")
        )
        descriptor = release.get("metrology_dependencies")
        if (
            not isinstance(descriptor, dict)
            or descriptor.get("requirements")
            != pack["compatibility"]["pythonDistributions"]
            or descriptor.get("version") != pack["version"]
            or descriptor.get("node_pack_id") != pack["id"]
        ):
            raise ValueError("三维发行锁与节点 manifest 不一致")
        expected_wheels = set()
        for item in descriptor["requirements"]:
            requirement = Requirement(item)
            if requirement.name in {"trimesh", "pypcd4"}:
                version = next(iter(requirement.specifier)).version
                expected_wheels.add(
                    f"tools/wheels/{requirement.name}-{version}-py3-none-any.whl"
                )
        wheel_paths = [item["path"] for item in descriptor["wheels"]]
        if len(wheel_paths) != 2 or set(wheel_paths) != expected_wheels:
            raise ValueError("受控 wheel 清单不完整或重复")
        if release.get("target", {}).get("os") == "ubuntu":
            native = json.loads(
                (root / "tools/native/manifest.json").read_text("utf-8")
            )
            if native != release.get("native_libraries") or not native["files"]:
                raise ValueError("原生资产清单不一致")
            for name, digest in native["files"].items():
                if Path(name).name != name:
                    raise ValueError("原生资产路径越界")
                _verify_file(root / "tools/native/lib" / name, digest)
        for item in descriptor["requirements"]:
            requirement = Requirement(item)
            distribution = metadata.distribution(requirement.name)
            versions[requirement.name] = distribution.version
            if distribution.version not in requirement.specifier:
                raise ValueError(
                    f"三维依赖版本不匹配: {item}, actual={distribution.version}"
                )
            if (
                not Path(distribution.locate_file(""))
                .resolve()
                .is_relative_to((root / "python").resolve())
            ):
                raise ValueError(f"三维依赖来自发行目录外: {requirement.name}")
        for item in descriptor["wheels"]:
            path = (root / item["path"]).resolve()
            if not path.is_relative_to((root / "tools/wheels").resolve()):
                raise ValueError("受控 wheel 路径越界")
            _verify_file(path, item["sha256"])
            if (
                json.loads(path.with_suffix(".build.json").read_text("utf-8"))[
                    "wheel_sha256"
                ]
                != item["sha256"]
            ):
                raise ValueError("受控 wheel 构建记录不一致")
        import numpy as np
        import open3d as o3d
        from scipy.spatial import cKDTree
        from trimesh.bounds import oriented_bounds_2D

        import_module("pypcd4")
        import_module("lzf")
        points = np.array(
            [[x, y, 0.0] for x in range(4) for y in range(4)], dtype=np.float64
        )
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
        plane, inliers = cloud.segment_plane(0.001, 3, 10)
        if len(inliers) != 16 or not np.isclose(abs(plane[2]), 1):
            raise ValueError("Open3D 平面原生核验失败")
        if cKDTree(points).query(points[:1])[0][0] != 0:
            raise ValueError("SciPy 空间索引核验失败")
        _, extents = oriented_bounds_2D(points[:, :2])
        if not np.allclose(extents, [3.0, 3.0]):
            raise ValueError("trimesh 几何核验失败")
    except Exception as error:
        issues.append(f"三维运行时校验失败: {error}")
    return dict(valid=not issues, versions=versions, issues=issues)
