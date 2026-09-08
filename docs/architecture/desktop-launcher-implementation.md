# amvar launcher 实施与验收记录

更新日期：2026-09-08。Windows x64 首版源码、根目录发布、服务所有权管理、原生窗口与自动化测试已实现；真实视觉 full 发行包冷启动和干净机器验收尚未完成。以下记录区分代码实现、受控进程验证和实际桌面操作。

类型和状态契约见 [工程架构](desktop-launcher.md)，交互见 [产品设计](../design/desktop-launcher.md)，构建命令与配置见 [部署说明](../deployment/desktop-launcher.md)。

## 分步交付

| 步骤 | 实现结果 | 核对与验证 |
| --- | --- | --- |
| 1 工程骨架 | Core、Infrastructure、Desktop 三个生产工程，三个根 tests 工程 | Release 构建成功，测试可发现；程序集 amvar.launcher |
| 2 Core | 具名配置/状态模型、SettingsService、BackendSessionController、LauncherCoordinator | 7 项行为测试；仅查看不启停、外部服务不接管、退出优先、迟到导航、停止失败、等待重试 |
| 3 JSON 与磁盘 | Newtonsoft.Json、严格类型和 schema、原子配置保存、有界日志 | 配置与单实例等 14 项常规测试通过，几何保存保留外部配置变化 |
| 4 WebView | 官方 NativeWebView、Fixed Version WebView2、Vue 就绪标记、站外导航边界 | 实机 5600 页面、文件导入、JSON 下载、中文文本、画布右键通过 |
| 5 Python full 协议 | 早期 root state、阶段文件、迁移登记、启动中停止检查、身份绑定的 graceful stop | 启停协议和原有发行回归通过；无新参数时保持原停止 CLI 使用方式 |
| 6 Windows 进程适配 | 隐藏 batch、随包 Python 身份检查、祖先链与监听进程归属核对 | 3 项真实短进程测试通过，含中文/空格/& 路径；本次 worker 回收，无关 listener 保留 |
| 7 主窗口与托盘 | 自定义主标题栏、关闭隐藏、单实例激活、显式退出 | 关闭后 PID 保留；重复启动恢复原窗口与未保存工作流；退出后 PID 消失，外部服务仍 HTTP 200 |
| 8 设置与关于 | 原生设置、版本/构建时间/许可证/链接，离线许可证资源 | 主题立即切换；托盘关于的构建信息与许可证窗口可见，Esc 关闭 |
| 9 启动界面接线 | XAML 进度与已等待时间、1 DIP WebView 预载后展开、错误与重试 | Desktop 11 项通过，含实际 XAML Headless 加载；修正 SPA 跳转后导航按钮状态更新 |
| 10 集成回归 | 生命周期竞态、服务归属、配置和网页行为分层测试 | C# 常规 32 项 + 受控进程 3 项、Python 45 项通过 |
| 11 发行集成 | self-contained 脚本、779 文件摘要清单、可选 assemble-release 桌面包 | 实际摘要与 PE x64 检查通过；组装测试验证配置保留与数据目录防误重建 |
| 12 交付记录 | 架构、设计、部署、README 与目录索引同步 | 已提供根目录运行构建；剩余现场验收见下表 |

## 实现取舍

- 现有 Vue 页面承载视觉业务；原生界面负责外壳、启动状态、设置、关于和日志。MainWindow 处理窗口/托盘事件，Core 决定服务行为，Infrastructure 操作磁盘和进程。
- 进程身份通过随包只读 Python/psutil 工具获取，复用 full 协议，不新增 Windows PEB 解析。启动和检查进程清除 PYTHONHOME/PYTHONPATH 开发覆盖。
- 构建信息写入程序集元数据，由具名 C# 模型和 Newtonsoft.Json 导出 JSON；关于直接读程序集。没有手工拼接 JSON 或额外常驻元数据进程。
- 加载界面直接位于 MainWindow XAML，不另建仅透传的 StartupView。原生 WebView 无法由透明 XAML 覆盖，采用预载尺寸和显隐交接。
- 桌面组件采用 `--launcher-publish-dir` 显式选择，不新增旧 profile 必填字段。仅实现 Windows x64，其他平台保留适配边界。
- 已连接页面不自动刷新；当前没有后台 HTTP 心跳监控，不因网页故障自动重启服务。启动超时可继续等待；本次栈已终止时需重新启动应用。

## 验证环境与结果

实际环境：Windows 11 专业版 10.0.26200，.NET SDK 10.0.400、运行时 10.0.11、Avalonia 12.1.2、Avalonia WebView 12.1.0、Newtonsoft.Json 13.0.4、Fixed Version WebView2 152.0.4191.62 x64。WebView2 官方资产 Authenticode 为有效 Microsoft 签名。不以旧 Windows 专项兼容矩阵为实施前置条件。

```powershell
dotnet test launcher/Amvar.Launcher.slnx -c Release
conda activate amvision
$testPythonDirectory = python -c "import sys; from pathlib import Path; print(Path(sys.executable).parent)"
./tests/launcher/test_process_integration.ps1 -PythonDirectory $testPythonDirectory
python -m pytest tests/test_full_launcher_stop_contract.py tests/test_runtime_launcher_common.py tests/test_launcher_release.py tests/test_release_assembly.py tests/test_release_runtime_validation.py --basetemp=.tmp/launcher/pytest-final -q
```

普通 dotnet test：Core 7、Infrastructure 14、Desktop 11 通过；3 项进程夹具明确跳过，再由受控脚本单独执行并全部通过。Python 合计 45 通过。前端类型检查与生产构建、受影响 Python 的 ruff 检查通过。测试统一位于根 `tests/launcher/` 或 `tests/`。

当前构建输出 `launcher/bin/publish/win-x64-shell-20260908/`。开发输出不再写入仓库根；输出根仅保留 EXE，其余 778 项程序资产位于 `launcher/`。实际进程模块确认 CoreCLR 从该子目录加载。旧版仓库根文件按清单摘要逐个核对后迁入 `launcher/bin/legacy-root/`，旧配置、日志及浏览数据也迁入该处保留；未迁移或清理业务数据。

实机操作创建过仅浏览器内存中的临时说明节点，验证隐藏恢复和 JSON 导入导出，未保存或发布到后端。用户协助打开托盘关于和点击退出，工具核对窗口、进程和服务结果。

最终修正版已通过站内跳转、原生后退/前进及按钮状态实测；设置窗口只保留关闭按钮，外观已恢复为跟随系统。文档本地链接检查和 `git diff --check` 通过。

## 目录与界面调整验证

顶部改为设置、帮助（关于）、后退、前进和窗口控制，中间为空白拖动区。删除顶部品牌、主页和刷新。设置与关于删除重复描述，统一表单边框、按钮和亮暗资源。

当前回归：C# 常规 33 项通过（增加发行根/程序集目录分离测试）；Python 发行相关 41 项通过（CPU 和 NVIDIA 均覆盖新目录布局、配置保留、浏览数据保护，补充目录穿越和私有目录拒绝用例）；前端主题契约测试 1 项、类型检查和生产构建通过。先前 3 项受控进程测试结果仍保留，本轮未修改服务所有权实现。

真实 WebView 首次载入与系统暗色一致，设置为亮色时外壳和网页同时切换，没有刷新页面。帮助下拉和关于窗口也通过实机检查。主题测试核对 Preferences store、DOM 和 localStorage 更新，以及拒绝非法主题值。v2 包的 779 项摘要和 PE 架构检查通过。

## 配色、菜单与全屏验证

外壳采用前端页面/面板/输入/边框/悬停的亮暗色值，顶部文字和图标使用次级文字色，删除主窗口系统顶部边线。帮助 Flyout 和外观选项使用统一圆角及 120ms 背景过渡，去除 Fluent 默认绿色选中条。

增加 `start_fullscreen` 强类型配置，旧配置省略时按 false 读取。F11 由原生窗口和 Windows WebView2 快捷键事件分别接收，共用全屏状态控制器；窗口状态与启动偏好独立。测试位于根 `tests/launcher/`。

本轮 C# 40 项通过，3 项依赖专用进程环境的测试按默认条件跳过，未重新运行；发行包 779 项文件摘要及 x64 PE 校验通过。新增测试覆盖旧配置默认值、严格布尔类型、全屏配置保存、普通/最大化恢复、F11 修饰键与重复按键过滤。两个 Headless 测试类共用串行 collection，避免并行创建 Avalonia 全局平台引起冲突。

最终原生构建已实测：启动时全屏；网页焦点内连续 F11 进入/退出；1280×800 普通窗口恢复；最大化→全屏→最大化；亮暗帮助菜单及悬停；外观下拉选中与悬停；关于入口；外壳与 5600 前端同步亮暗主题。验收配置恢复为跟随系统、启动全屏关闭。边角拖动的工具操作没有产生可核对的尺寸变化，尚未把实机边缘缩放列为通过；多屏和不同 DPI 继续按下表验收。

## 尚待现场验收

| 范围 | 当前证据 | 剩余验证 |
| --- | --- | --- |
| 完整视觉 full 冷启动与退出 | Core 与真实短进程覆盖等待、启动中退出、worker 回收 | 独立发行包实际迁移、Broker、daemon、六类 worker 和业务任务回收；当前 5600 为用户手动服务，未停止它腾出端口 |
| 离线部署 | self-contained + Fixed WebView2 实际使用、摘要和架构校验 | 无系统 .NET/Evergreen/Python/Node 的干净 Windows 环境 |
| 桌面系统事件 | 当前工作站普通窗口、托盘隐藏恢复、退出 | 多屏 150%/200% DPI、Snap Layout、Explorer 重启、注销/关机、反复操作的资源稳定性 |
| 完整 WebView 输入与连接 | 中文文本、单文件导入、JSON 下载、右键、站内导航 | IME 组合输入、多文件 multipart、剪贴板全部编辑场景、WebSocket 断线恢复专项 |
| 其他平台 | 平台边界已划分 | Ubuntu/macOS/Windows ARM64 实现与发行 |

这些事项不标为通过；Windows x64 开发构建已可使用，完整发行认证仍需上述现场环境。已确认 `.tmp/launcher/` 无链接且没有测试进程使用，但本次删除被执行环境策略拦截，临时缓存清理未完成；该目录不属于交付资产。
