# amvar launcher 部署

Windows x64 启动器采用 .NET 10 self-contained、Avalonia 和随包 Fixed Version WebView2。开发输出全部位于 `launcher/` 项目内；正式发行入口为 `release/<profile-id>/amvar.launcher.exe`。网页固定为 `http://127.0.0.1:5600`。

## 构建

开发需要 .NET 10 SDK；Python 回归使用 `conda activate amvision` 后的解释器。下载 Microsoft 官方 Fixed Version WebView2 x64，解压到 `runtimes/third_party/webview2/win-x64/`，该目录直接包含 `msedgewebview2.exe`。这些本地二进制不进入 Git。

```powershell
dotnet test launcher/Amvar.Launcher.slnx -c Release
./launcher/publish-win-x64.ps1 -OutputDirectory launcher/bin/publish/win-x64
```

输出目录必须尚不存在。脚本输出 EXE、.NET/Avalonia 依赖、`launcher/tools/webview2/win-x64/`、许可证、`launcher-build-info.json` 和带 SHA-256 摘要的 `launcher-release.json`。不启用 trimming、AOT 或单文件打包。WebView2 与应用资源支持本地载入，目标机不需要额外安装 .NET、Node 或 Evergreen WebView2。

开发构建和发布只写 `launcher/` 项目内部，不再提供写入仓库根的选项。输出根只有 `amvar.launcher.exe` 和 `launcher/`。正式发行布局为：

```text
release/full-windows-x64-cpu/     # NVIDIA 为 full-windows-x64-nvidia/
├─ amvar.launcher.exe
├─ launcher/
│  ├─ amvar.launcher.dll、coreclr.dll 等依赖
│  ├─ launcher-build-info.json、launcher-release.json
│  ├─ tools/webview2/win-x64/
│  ├─ config/launcher.json
│  ├─ data/launcher/webview/
│  └─ logs/launcher/
├─ python/
├─ app/
└─ start-amvision-full.bat 等视觉服务文件
```

根 EXE 使用 .NET SDK CreateAppHost 直接定位子目录程序集，没有额外引导进程。清单版本为 `amvar.launcher-release.v2`，位于 `launcher/`，文件路径相对发行根；v1 平铺包需重新构建。`project_root="."` 指向 EXE 所在的发行根。

## 完整发行包

桌面组件由组装命令显式选择，原有 profile 无需修改；省略参数保持纯视觉服务发行方式。

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --launcher-publish-dir launcher/bin/publish/win-x64
```

完整 Python 依赖和静态前端准备步骤仍见 [生产环境](production-environment.md)及[同目录 Python](bundled-python-deployment.md)。启动服务时必须具备发行 full 脚本、`python/python.exe`、`launchers/inspect_process.py`、发行 manifest 和静态前端。GPU 驱动、CUDA Toolkit 和厂商运行时遵循对应 profile 的系统依赖边界。

组装检查清单格式、路径、文件摘要、必要资产，并检查启动器、CoreCLR 和 WebView2 的实际 PE 架构。`release_manifest.json` 记录桌面组件清单，布局校验也会重新校验这些文件。

已有桌面发行目录的 `data/`、`logs/`、`launcher/data/` 或 `launcher/logs/` 非空时，拒绝使用整目录 `--force` 重建。更新应先组装到新目录并验收，再在服务和启动器退出后按程序文件清单更新；保留用户配置、业务数据、WebView 数据和日志。当前没有自动更新器。空数据目录重建仍保留已有 `launcher/config/launcher.json` 原始内容。

## 配置与生命周期

配置路径基于启动器程序目录，而非终端工作目录。缺少配置时使用默认值；示例见 [launcher.example.json](../../launcher/config/launcher.example.json)。使用强类型模型与 Newtonsoft.Json 读写，不通过字符串拼接 JSON。

| 情况 | 启动 | 托盘退出 |
| --- | --- | --- |
| `manage_service=false` | 直接载入页面，不检查服务资产和启停状态 | 只退出启动器 |
| 默认 true，已有外部服务 | 连接页面，不接管服务 | 只退出启动器 |
| 默认 true，服务未运行 | 从 `project_root` 启动完整发行服务，显示真实启动阶段 | 停止本次创建的 full 栈，确认结束后退出 |

管理方式与项目目录下次启动生效，主题立即生效。手动 conda/Uvicorn/Vite 开发进程和第三方服务不受启动器管理。服务身份依据进程创建时间、可执行路径和本次进程祖先链确认；不能仅凭端口或旧 PID 文件停止进程。

`start_fullscreen` 默认 false，设置中的“启动时全屏”在下次启动生效。F11 临时进入/退出全屏，恢复原普通/最大化状态，不改动启动偏好。旧 schema v1 配置缺少该字段时按 false 读取，无需迁移。

关闭主窗口或 Alt+F4 会隐藏至托盘，保留 WebView 和未保存内容。再次运行同一安装的启动器会恢复原窗口。托盘菜单依次为“显示窗口／关于／退出”。停止失败保留启动器并显示问题，可查看日志和重试退出。

`launcher/logs/launcher/` 保存启动器日志；`logs/full-stack/` 保存 full 服务日志、`runtime-state.json` 和 `launcher-status.json`。构建信息同时写入程序集和发行 JSON；“关于”的许可证来自内嵌资源，不需要联网。

## 验收边界

本机已验证 self-contained 根目录运行、随包 WebView2、外部服务连接、隐藏恢复及单实例、原生关于和许可证、文件导入与 JSON 下载。受控进程测试覆盖完整栈所有权、启动期间退出、无关监听进程隔离。详细结果见 [实施记录](../architecture/desktop-launcher-implementation.md)。

真实视觉 full 发行包的冷启动与业务任务回收、干净离线机器、多屏 DPI、Explorer 重启和系统关机尚需专项验收。当前手动运行的开发服务不作为真实 full 栈验收对象。其他平台适配尚未完成。
