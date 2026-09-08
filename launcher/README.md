# amvar launcher

Windows x64 桌面启动器，源码分为 Core、Infrastructure、Desktop 三个工程；测试在根 `tests/launcher/`。固定打开 `http://127.0.0.1:5600`，不复制 Vue 视觉业务页面。

默认启动并管理本次创建的发行 full 服务。已有外部服务只连接；设置 `launcher/config/launcher.json` 的 `manage_service=false` 时直接载入页面，不调用启停脚本。配置基于程序目录，管理方式与项目目录下次启动生效。

F11 进入/退出全屏，恢复之前的普通或最大化状态。设置中的“启动时全屏”对应 `start_fullscreen`，默认关闭、下次启动生效；临时 F11 切换不修改该偏好。外壳和内嵌前端统一亮暗配色，保存外观后立即同步。

关闭主窗口隐藏到托盘，保留 WebView 和未保存编辑。托盘菜单为“显示窗口／关于／退出”，只有退出才执行服务回收。关于、设置、启动动画为 Avalonia 原生界面。

## 构建与测试

```powershell
dotnet build launcher/Amvar.Launcher.slnx -c Release
dotnet test launcher/Amvar.Launcher.slnx -c Release
```

真实进程测试使用受控短进程和独立端口，不操作开发服务：

```powershell
conda activate amvision
$testPythonDirectory = python -c "import sys; from pathlib import Path; print(Path(sys.executable).parent)"
./tests/launcher/test_process_integration.ps1 -PythonDirectory $testPythonDirectory
```

普通 dotnet test 明确跳过该依赖 Python 夹具的测试；通过上述脚本单独执行，不把跳过算作通过。

## Windows 发布

开发工具需要 .NET 10 SDK。Fixed Version WebView2 x64 解压到 `runtimes/third_party/webview2/win-x64/`，目录直接包含 `msedgewebview2.exe`。运行：

```powershell
./launcher/publish-win-x64.ps1 -OutputDirectory launcher/bin/publish/win-x64
```

输出目录必须尚不存在且位于 `launcher/` 项目内。开发构建与发布不写仓库根目录。输出根只放入口 `amvar.launcher.exe`，程序集、运行时、WebView2、配置和日志集中在其旁的 `launcher/` 子目录。二进制与本地配置不进入 Git。

正式发行时两种 profile 均把 EXE 放在 `release/<profile-id>/` 根，其余启动器文件放入该根的 `launcher/`。`project_root="."` 相对入口 EXE 所在根解析。开发时连接手动服务，或通过设置 project_root 指向完整发行根。

正式发行组装、更新和验收边界见 [部署说明](../docs/deployment/desktop-launcher.md)、[工程架构](../docs/architecture/desktop-launcher.md)、[产品设计](../docs/design/desktop-launcher.md)和[实施记录](../docs/architecture/desktop-launcher-implementation.md)。
