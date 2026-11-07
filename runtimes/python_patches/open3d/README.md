# Open3D 受控原生修复

## 范围

此目录是构建输入，不进入业务模块的导入路径。复用
`scripts/build_controlled_python.py`，生成正常平台 wheel，不运行时打补丁。
上游为 Open3D 0.20.0，固定提交、归档和文件摘要见 `manifest.json`；
候选版本为 `0.20.0+amvision.1`，许可证沿用上游 MIT。

修复仅调整 `GetCoordinateSystemOnPlane` 的切平面基选择条件，避开正负 Z
法向时的零分母；不改变邻域查询、角排序、角阈值或边界算法。
CMake 补丁写入受控包版本，并修复 Linux bundled curl/BoringSSL 静态库分组：
将实际归档纳入 LINK_GROUP RESCAN，避免接口 target 展开后分组为空、出现未解析符号。
不是重写解析器或边界算法，不通过旋转输入规避缺陷。

当前构建为 CPU 几何候选，关闭 GUI、浏览器可视化、硬件桥接、ML 算子和 GPU
模块，项目界面继续使用已有前端查看器。具体选项全部记录于 manifest 和构建记录。
ISPC 在该候选中关闭；不能据此声明与上游 wheel 的全套模块或性能等价。
运行依赖仍固定原版本，只有双平台完整原生与既有几何回归后才更新节点、发行锁和产物。

## 开发笔记本离线安装

适用于已有相同 `amvision` 环境的 Windows x64 开发笔记本。此包为 CPython 3.12 的 CPU wheel；
安装不需要 Visual Studio、Windows SDK、CMake 或 Ninja，也不需要重建 conda 环境。

**交接顺序：** 笔记本先同步 Git；由操作者手动复制文件，再通知笔记本会话执行安装。
Git 只管理构建脚本、补丁和说明，不管理 `runtimes/third_party/`。仅完成 Git 同步时不启动下载、安装或编译。

**复制清单：** 构建机和笔记本使用同一仓库相对目录
`runtimes/third_party/python-geometry/open3d-candidates/0.20.0+amvision.1/`。

| Windows 所需文件 | 大小 | 用途 |
| --- | ---: | --- |
| `open3d-0.20.0+amvision.1-cp312-cp312-win_amd64.whl` | 31,217,075 B | 已含原生 DLL 和 Python 扩展，不另行解压 |
| `open3d-0.20.0+amvision.1-cp312-cp312-win_amd64.build.json` | 2,162 B | 核对版本、平台和 wheel SHA-256 |

不需要复制上一级目录的原版 `0.20.0`、Ubuntu 的 `open3d_cpu` wheel 或
`open3d-build-inputs/`（约 1.38 GiB，仅重新构建时使用）。上述两文件是已有开发环境的增量，
不是空机器的完整依赖包。

**收到安装通知后**，从笔记本仓库根目录执行以下 PowerShell 步骤。先核对文件与解释器；
任何一项不匹配都应停止，不从 PyPI 取同名包替代。

```powershell
conda activate amvision
python -c "import platform,struct,sys; print(sys.executable, sys.version); sys.exit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,12) and platform.machine().upper() in ('AMD64','X86_64') and struct.calcsize('P') == 8 else 1)"
if ($LASTEXITCODE -ne 0) { throw '需要 CPython 3.12 x64' }
$dir = 'runtimes/third_party/python-geometry/open3d-candidates/0.20.0+amvision.1'
$stem = 'open3d-0.20.0+amvision.1-cp312-cp312-win_amd64'
$wheel = (Resolve-Path -LiteralPath "$dir/$stem.whl" -ErrorAction Stop).Path
$record = Get-Content -Raw -LiteralPath "$dir/$stem.build.json" -ErrorAction Stop | ConvertFrom-Json
$expected = 'dc18e527be4816b375b9156ffc5a2d449af6cce97a57a3749010369b25d78563'
if ($record.version -ne '0.20.0+amvision.1' -or $record.wheel_sha256 -ne $expected -or
    (Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash -ne $expected) { throw 'Open3D 构建身份不匹配' }
```

当前候选**不覆盖业务 conda 环境**。在同一 PowerShell 窗口创建独立验证环境，复用已有依赖；
使用明确的解释器路径，无需切换激活状态：

```powershell
$venv = Join-Path $env:LOCALAPPDATA 'amvision/venvs/open3d-0.20.0-amvision.1'
python -m venv --system-site-packages $venv
if ($LASTEXITCODE -ne 0) { throw '创建验证环境失败' }
$py = Join-Path $venv 'Scripts/python.exe'
& $py -m pip install --no-index --only-binary=:all: $wheel
if ($LASTEXITCODE -ne 0) { throw '离线安装失败；核对缺少的依赖，不在线回退' }
& $py -c "import open3d,sys; from pathlib import Path; print(open3d.__version__, open3d.__file__); assert open3d.__version__ == '0.20.0+amvision.1' and Path(open3d.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())"
if ($LASTEXITCODE -ne 0) { throw '实际加载的 Open3D 与候选不一致' }
& $py -m tests.integration.metrology3d.sampling_boundary_native_audit
if ($LASTEXITCODE -ne 0) { throw '原生边界验证失败' }
```

笔记本会话应报告解释器路径、wheel 摘要、实际模块路径及原生审计结果（预期 40/40）。
缺少依赖时记录具体包名，核对两机环境或补复制相应 wheel；不要以 `--no-deps` 隐藏缺项。
Fit Plane 的业务版本准入和生产发行锁尚未切换，候选导入成功不等于可以替换在用节点依赖。

## 构建

开发环境先执行 `conda activate amvision`，构建使用显式 x64 Python 3.12
环境；客户机不需要编译工具。Windows 使用官方 MSVC C++ 和 Windows SDK，
Ubuntu 使用原生文件系统、GCC/CMake/Ninja 与上游要求的开发库。
本轮验证 CMake 3.31.6，LINK_GROUP 要求至少 CMake 3.24。
工具及构建依赖仅用于开发构建，不能以客户机安装编译器代替自带 Python 发行。

```text
python scripts/build_controlled_python.py open3d --archive <source.tar.gz> --work-dir <new-directory> --wheel-dir <wheelhouse> --prepare-only
python scripts/build_controlled_python.py open3d --archive <source.tar.gz> --work-dir <another-new-directory> --wheel-dir <wheelhouse> --cmake <cmake> --generator Ninja --jobs <explicit-count>
```

`--build-prefix` 用于显式开发库前缀；Windows Ninja 须在 x64 开发工具环境中运行。
`--jobs` 同时传递给外层和独立子 CMake 构建；它是每个构建进程的并发上限，
不是整个进程树的统一任务槽或内存预算，构建机仍须留出组合资源。
该前缀传递给上游子 CMake，`include` 目录进入 GCC/Clang 的 `CPATH`；
解压式 Linux 开发库还须由构建调用明确设置
`PKG_CONFIG_PATH` 和 `PKG_CONFIG_SYSROOT_DIR`，不能因此安装或覆盖系统库。
`--download-dir` 可复用原生依赖归档缓存，上游仍逐文件校验固定摘要；失败构建的
源码/对象目录不复用，重新使用空目录。缓存路径不是运行时依赖。
归档、原文件、补丁和修复后文件均校验 SHA-256；构建目录必须为空。
独立 Git 索引避免宿主仓库造成补丁静默跳过，显式 LF 避免系统行尾改变源码身份。
上游归档唯一编辑器说明链接按归档目标复制，不要求 Windows 符号链接特权。
最终构建先在独立进程导入构建目录内实际原生模块；加载失败不收集 wheel。
随后检查平台发行名、版本及当前 0.20 的唯一根原生模块 `open3d/pybind`，拒绝旧
`cpu/pybind` 目录或缺失/重复模块，记录 wheel 和 CMakeCache 摘要；不安装到业务环境。
CPU 发行名沿上游：Windows 为 `open3d`，Linux x64 为 `open3d-cpu`；
两者 Python 导入名均为 `open3d`，不能把 Linux 产物锁成另一个发行名。

已验证候选位于现有本地资产目录
`runtimes/third_party/python-geometry/open3d-candidates/0.20.0+amvision.1/`，未进入生产锁。
Ubuntu 候选基于 glibc 2.39，验证环境提供 EGL/OpenGL 系统库；尚不能当作任意
Ubuntu 客户机的独立离线发行。原生链接路径、系统库装配、包身份及现有 Fit Plane
版本准入必须随正式依赖升级同批核定。

## 验证层次

1. 构建器回归：坏归档、原文件/补丁/结果身份、链接和重复目录拒绝。
2. 原生坐标基：从已核验上游文件提取原函数和叉乘函数，使用 GCC/MSVC 编译
   同一测试；64 个方向与精度案例检查有限性、正交和单位长度。这不是完整 wheel 验收。
3. 完整原生算子：安装候选 wheel 到隔离解释器后执行
   `python -m tests.integration.metrology3d.sampling_boundary_native_audit`。
   40 案例覆盖独立外圈/缺口真值、float32/64、正负法向、轴变换及平移，逐行比较。
4. 既有节点的 Open3D 调用与 B09 完整邻域/饱和/无效点/重复点/预算/取消回收，
   然后才进行资产、公开节点和真实发布验收。

原函数审计支持 `--compiler-family msvc --compiler cl` 或默认 GCC。
测试不得以 xfail、调整阈值或删除反例将原生失败改为通过。
进度和真实覆盖统一记录于 `docs/development/3d-metrology-edge-evidence.md`。
