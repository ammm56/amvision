# Windows / Ubuntu CPU 离线发行

## 范围

复用 `assemble-release`、统一 full Supervisor、A11 点云客户端和配方工具。目标为 Windows x64 与 Ubuntu 24.04 x86_64；Ubuntu 验收使用 WSL Ubuntu 的原生文件系统。没有新增调度器、安装器或三维专用服务。Ubuntu NVIDIA 和其他 Linux 发行版不在本次范围。

构建机准备依赖，客户机运行时不安装 Python 包、不运行 npm、不读取源码仓库，不要求系统 Python、Conda、Node 或 CDN。CPU 包采用 CPU-only PyTorch，不包含 CUDA/TensorRT/cuDNN 资产。

## 构建资产

1. 构建机激活 `amvision`，按 lockfile 构建 Vue 静态前端。
2. 准备目标平台 FFmpeg：`runtimes/third_party/ffmpeg/windows-x64` 或 `linux-x64`。
3. 准备受控 `trimesh`、`pypcd4` wheel 及 `.build.json`，目录为 `runtimes/third_party/python-io`。版本唯一来源为三维包 manifest。装配器核对 SHA256，复制至 `tools/wheels`，并将精确依赖追加至生成的 `app/requirements.txt`。
4. Ubuntu 的 Open3D 需要 libusb。资产及许可文本位于 `runtimes/third_party/native/ubuntu-x64`，来源和文件 SHA256 见 `runtimes/manifests/native-libraries/ubuntu-x64.json`。构建机从清单指定的 Ubuntu 官方 deb 解包，复制库为 `libusb-1.0.so.0`，并保留 copyright 和 LGPL-2.1 文本；不在客户机运行 apt。装配器复制并核验，统一 launcher 将 `tools/native/lib` 加入 Linux 子进程的库路径。
5. Ubuntu 仍需操作系统自带 glibc >= 2.38、libudev、libcap 等基础库；`validate-layout` 实际加载 Open3D 并执行几何计算，不能以包元数据替代原生库验收。

## 同目录 Python

装配器仍不复制构建机 Conda、不联网创建 Python。构建人员准备完整、可搬运的 Python 3.12 x64，不能用指向系统解释器/标准库的 venv 冒充自带 Python。

| 目标 | 入口 | 本轮运行时 |
| --- | --- | --- |
| Windows CPU | `python/python.exe` | Python 3.12.15，CPU-only torch 2.12.1 |
| Ubuntu CPU | `python/bin/python3` | python-build-standalone CPython 3.12.16，CPU-only torch 2.12.1 |

Ubuntu 本轮使用 [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 的 `20261026` 发行：`cpython-3.12.16+20261026-x86_64-unknown-linux-gnu-install_only.tar.gz`，SHA256 `6a79e922e50006b601f29e688407659da1c2b86ebcd4e9c7254cf234be8b89de`。保留分发包与各依赖自带的许可证和 dist-info，不能只复制一个可执行文件。

先安装匹配的 CPU-only torch/torchvision，再用该目标解释器安装生成的 requirements 和受控 wheel。例如 Ubuntu 构建阶段：

```bash
./python/bin/python3 -I -m pip install torch==2.12.1 torchvision==0.27.1 --index-url https://download.pytorch.org/whl/cpu
./python/bin/python3 -I -m pip install -r app/requirements.txt --find-links tools/wheels
./python/bin/python3 -I -m pip check
```

Windows 使用 `python/python.exe`。网络和 pip 只用于构建阶段；完整 Python、原生库和静态文件装好、验证后才交付。升级构建须再次记录依赖版本并验收，不能将本轮记录当任意新版本的证明。

## 装配与启动

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root release --force
```

Ubuntu 在构建环境执行同一命令，仅换为 `full-ubuntu-x64-cpu`。不能用待重建目录自身的 Python 运行装配器；运行中的目录会被保护并拒绝覆盖。构建机需要 Node；客户机不需要。已构建前端可通过已有 `ReleaseAssemblyRequest.frontend_dist_dir` 交付给同一装配器，不另建打包流程。

`--force` 保留 `python/`，其余生成目录重建，仅用于隔离构建输出，不用于覆盖生产数据。源码修改后重新装配，不手改生成的 `app/`。`*.local.json` 不从开发仓库带入现场，配置必须在目标包显式设置；三维容量可使用已批准的 `workstation.example.json`，不能称为所有客户机默认。

进入 Ubuntu 发行根：

```bash
./launchers/maintenance/invoke-backend-maintenance.sh -- validate-layout
./start-amvision-full.sh --host 127.0.0.1 --port 5600
# 另一终端
./stop-amvision-full.sh
```

Windows 使用对应 `.bat`。Shell 入口缺少随包 Python 时失败，不回退系统 Python。Ubuntu 不包含 Windows 桌面 EXE；静态页面由 FastAPI 同源提供。数据库、对象存储、控制文件、临时目录和 IPC 位于 Ubuntu 原生文件系统，不使用 `/mnt/c`、`/mnt/w`。

`validate-layout` 检查目标系统、64-bit、Python 入口和标准库根、CPU-only torch、全部直接依赖、三维精确版本/受控 wheel、原生库摘要，并实际执行 Open3D/SciPy/trimesh 与唯一 owner 文件锁。full 启动仍沿原有数据库迁移、Broker、daemon 和六 worker 就绪链路；停止沿原有进程归属机制。

## 交付核验

- 空环境从页面或 API 导入 A10 配方携资源 ZIP，核对引用映射后发布。
- 正式 AppVersion → WorkflowAppRuntime → 完整原云 → 50 项测量 → Result Record / 文件输出。
- 停止 Runtime 和 full 进程组，重启相同目录，再运行持久发布与资产；不从构建机恢复数据。
- 检查静态页面和资产，运行阶段禁用外部依赖下载；保留启动、停止和异常日志。
- A11 客户端、工件生成工具及文档随装配复制，不要求客户机存在 `tests/` 或源码仓库。

具体结果见 [A12 验收记录](../development/3d-metrology-offline-release.md)。十秒节拍、近 1 GB 显示索引和实物计量准确度不由本项代替，也不阻塞本项交付。
