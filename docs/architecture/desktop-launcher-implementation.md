# amvar launcher 详细实施步骤

状态：实施计划，尚未开始。当前 `launcher/` 仅有 README，没有 C# 工程。本文中的新增文件、测试和验证结果均为待完成项。

本文负责实施顺序、工作项和完成条件；类型、依赖及状态契约以 [工程架构](desktop-launcher.md) 为准，交互和配置以 [产品设计](../design/desktop-launcher.md) 为准。实际实现发生变化时同步修改对应契约，不把原计划写成已完成能力。

## 实施范围与推进规则

首版为 Windows x64，目标系统为 Windows 10 1903 及之后版本和 Windows 11。使用实施时最新稳定版 .NET 10，不开展旧版 Windows 专项兼容调查，不为旧系统降级框架或增加兼容分支，也不以 Windows 1903 专项环境作为实施前置条件。源码保留跨平台边界，Ubuntu、macOS、Windows ARM64 的适配与发行在首版之后完成。

服务行为固定如下：

| 配置与现场情况 | 启动行为 | 托盘退出行为 |
| --- | --- | --- |
| `manage_service=false` | 直接载入 `http://127.0.0.1:5600`，不检查 full 资产、不调用服务脚本 | 只退出启动器 |
| `manage_service=true`，外部服务已运行 | 连接现有页面，不接管同目录 full、第三方或手工开发服务 | 只退出启动器 |
| `manage_service=true`，确认未运行 | 调用发行根 full 脚本，等待本次栈和网页就绪 | 停止本次创建的完整栈，再退出启动器 |

`manage_service` 默认 true，与项目目录配置均下次启动应用生效。源码开发前后端继续由终端手动运行，启动器不启动 conda 或 Vite。

每一步采用“核对现状→实现本步→构建和针对性测试→核对契约与实际行为→记录结果”的顺序。失败先修复，不带着已知错误进入依赖该结果的下一步。没有目标系统或原生环境时记录“未验证”，不能用其他系统的成功替代。

测试统一位于根 `tests/`：C# 放 `tests/launcher/`，文件名 `test_*.cs`；Python 沿用 `test_*.py`；前端新增测试放 `tests/frontend/`，使用 `test_*.ts`。测试夹具放对应测试目录，不放生产代码旁。临时输出放 `.tmp/launcher/`，Python 默认使用仓库既有 `.tmp/pytest`；完成且相关进程结束后清理本任务临时产物。正式验收结论记录在本文末尾，不依赖临时日志作为唯一证据。

## 阶段总览

| 步骤 | 交付结果 | 主要前置条件 |
| --- | --- | --- |
| 1 | 可构建的解决方案、三个生产工程、三个测试工程 | 已确认设计 |
| 2 | Core 类型模型、接口、状态机及用例 | 1 |
| 3 | 配置、协议 DTO、磁盘存储及诊断基础 | 2 |
| 4 | 最小 WebView 功能验证 | 3；可用 Windows 环境与 WebView2 资产 |
| 5 | Python full 启动、停止、就绪契约补齐 | 4；源码与契约核对 |
| 6 | Windows 进程适配与真实服务会话 | 5 |
| 7 | 原生主窗口、托盘、单实例和退出入口 | 6 |
| 8 | 设置、关于与构建元数据 | 7 |
| 9 | 启动动画、正式 WebView 交接及完整 UI 接线 | 8 |
| 10 | 两种模式、竞态与桌面交互的集成回归 | 9 |
| 11 | 根目录发布、发行组装与离线资产验证 | 10 |
| 12 | Windows 发行功能验收与文档交付 | 11 |

步骤 4 是建立在正式工程中的最小技术验证，不提前实现全部界面，也不另建永久演示项目。步骤 7–9 使用步骤 2 的用例和状态，不重新维护另一套业务逻辑。

## 步骤 1：创建工程骨架

实施内容：

1. 核对工作区已有修改、根 `global.json` 和本机 .NET SDK，保留其他任务代码。沿用根 SDK 策略，不修改已有 .NET SDK 项目。
2. 创建 `launcher/Amvar.Launcher.slnx`，以及 `src/Amvar.Launcher.Core`、`src/Amvar.Launcher.Infrastructure`、`src/Amvar.Launcher.Desktop` 三个工程。
3. 创建 `launcher/Directory.Build.props`、`Directory.Packages.props`：统一 .NET 10、nullable、编译配置与精确依赖版本。实施时使用最新稳定版 .NET 10 SDK/运行时并记录版本；精确记录 Avalonia、官方 WebView、Newtonsoft.Json 及测试依赖组合。不为旧 Windows 改用旧 .NET，也不升级到其他 .NET 大版本。
4. 创建根 `tests/launcher/` 中三个对应测试工程，显式导入 launcher 范围的构建和包配置。选定统一测试运行器，并验证 `dotnet test` 可以发现测试。
5. 按架构设置引用方向；Desktop 仅 Bootstrap 使用 Infrastructure。只创建最小 App/MainWindow 和启动入口，尚不启动后端。
6. 可执行程序集名设为 `amvar.launcher`；首版显式使用 x64 运行和发布。新增输出目录加入忽略规则，不将 bin、obj、WebView2 二进制或本地配置提交。

验证与完成条件：解决方案 Debug/Release 均构建成功；最小窗口可启动退出；测试被发现并执行；Core 无 UI、平台、文件或 JSON 依赖。构建最小窗口不得触碰 5600 服务。

## 步骤 2：实现 Core 模型、状态机和用例

主要位置：Core 的 `Configuration/`、`Runtime/`、`Lifecycle/`、`Application/`、`Abstractions/`、`Diagnostics/`。

实施内容：

1. 按工程架构逐个定义具名 class/record class、枚举和错误结果；配置、安装目录、会话、进程身份、观察结果、停止结果、快照分开。
2. 定义设置存储、服务探测、栈控制、构建信息、时间与日志边界。接口只返回类型化结果，不返回 JSON 文本、Process 或 Avalonia 对象。
3. 实现 `SettingsService`、`BackendSessionController`、`LauncherCoordinator`；导航请求和导航结果经类型化边界交给 Desktop，不在 Core 操作 WebView。
4. 落实三套独立状态：应用退出、后端会话、Desktop 窗口/WebView；状态迁移单点写入，快照有序发布。
5. `ManageService=false` 直接产生导航意图；true 先探测，已有外部服务只连接，确认空闲才产生一次启动意图。
6. 登记本次创建任务及其身份；短临界区保护迁移，IO 在锁外；退出优先，操作 ID 拒绝迟到回调。停止使用独立清理 token。
7. 重试先观察，等待超时而脚本仍存活时只能继续等待；隐藏窗口不进入退出流程。修改设置不改变已建立会话的管理权限。

测试建议文件：`test_launcher_coordinator.cs`、`test_backend_session_controller.cs`、`test_settings_service.cs`。使用可控时间、探测和栈替身，断言外部动作及最终状态，而非逐行镜像实现。

完成条件：未启动、外部已运行、启动中退出、重复启动/退出、迟到成功、超时继续等待、停止失败均有通过的行为测试；仅显示模式所有路径的 Start/Stop 调用次数均为零。

## 步骤 3：实现 JSON、配置持久化和诊断基础

主要位置：Infrastructure 的 `Contracts/`、`Serialization/`、`Configuration/`、`Diagnostics/`、`Metadata/`。

实施内容：

1. 定义架构中的所有 DTO 与 Core 映射；协议样本从实际 Python 写入和 health 响应核对，新增协议明确标注待步骤 5 接通。
2. Newtonsoft 设置集中维护：显式 snake_case、`TypeNameHandling.None`、必填/缺省/null、严格枚举和布尔值校验。不依赖库的隐式类型转换接受错误配置。
3. 实现加载结果分类、schema 校验、UTF-8 序列化、同目录临时文件和原子替换。写入失败保留旧文件；序列化来自具名对象，不拼字符串。
4. 创建 `config/launcher.example.json`。首次缺失采用默认 `manage_service=true`；损坏或未知版本进入配置错误，不使用默认 true 自动启动服务。
5. 实现已保存快照与设置编辑副本；窗口几何自动保存只写有效配置。隐藏和退出不覆盖损坏文件或未提交编辑。
6. 定义程序根、目标项目根、配置/日志/WebView 数据根的关系；所有相对路径基于程序位置解析。仅显示模式不要求目标目录具备 Python/full 发行资产。
7. 实现有界日志缓冲和文件轮转，记录会话、操作、阶段、退出码与错误；不记录认证 token、Cookie 或网页业务内容。构建信息先提供具名读取接口，真实生成在步骤 8 接通。

验证与完成条件：往返、中文/空格路径、缺省值、显式 null、错误布尔类型、未知字段/版本、损坏文件、写入失败、几何合并均通过；v1 示例与 DTO 一致；配置文件中不出现 Task、窗口对象或运行时句柄。

## 步骤 4：提前验证 WebView 功能

主要位置：Desktop 的 `Services/WebViewSession`、`Platforms/Windows/`、最小 MainWindow；前端 [bootstrap.ts](../../frontend/web-ui/src/app/bootstrap.ts)。

实施内容：

1. 在正式工程内接入官方 NativeWebView，初始化前指定 Fixed Version WebView2 和独立用户数据目录，验证实际控件 API 支持这些设置；不假定设置环境变量就足够。
2. 使用 `manage_service=false` 打开受控测试页面，验证最小导航、错误与重试；测试页面和服务夹具位于根 tests，程序仍使用正式固定地址约定。
3. 在可用 Windows x64 环境验证并记录 OS build 与依赖组合；在隔离发行环境验证无系统 .NET、无 Evergreen 的固定版运行方式。不要求准备 Windows 历史版本矩阵。
4. 验证文件选择、多文件 multipart、Blob/JSON 下载、中文输入、Ctrl+C/V、右键、WebSocket、存储、站内导航及外链打开。下载覆盖文件沿用系统保存交互。
5. 在 Vue 挂载且首轮更新完成后设置 `data-amvision-ui-ready="v1"`；仅对当前 origin 和导航轮次检查标记，登录页也算就绪。验证导航成功但 Vue 启动失败的区别。
6. 验证 XAML 与原生 WebView 显隐交接、缩放和自定义标题栏命中区域；Windows 11 Snap Layout 只按该系统能力验证，不能强求 Windows 10 具有该菜单。

验证与完成条件：桌面最小程序与实际 Vue 页面均通过关键能力检查；前端类型检查和构建通过，新增标记的测试放根 `tests/frontend/`。普通浏览器验证可检查 Vue 回归，但不能代替原生 WebView 验收。

本步只验证启动器使用的 WebView 功能和部署方式，不增加操作系统兼容专项。实际发现控件或程序错误时修复并记录；结果仅描述已验证的环境，不推断所有 Windows 版本均通过。

## 步骤 5：补齐 Python full 启停和就绪契约

修改入口为 [start_amvision_full.py](../../runtimes/launchers/full/start_amvision_full.py)、[stop_amvision_full.py](../../runtimes/launchers/full/stop_amvision_full.py)、[common.py](../../runtimes/launchers/common.py)，必要时同步根脚本模板。

实施内容：

1. 核对现有 Supervisor 锁、进程身份、状态写入和清理路径，先建立回归用例。维持迁移、Broker、daemon、service、Worker 的既有编排职责。
2. root 身份建立后、迁移前写入早期 state；迁移子进程纳入观察。启动边界和等待循环响应绑定身份的停止请求，收到退出后不继续拉起组件。
3. 原子写入 `launcher-status.json`：采用架构确定的 format ID、root_process、state 和可选 error。完整启动完成后才写 running，失败保留同轮诊断。
4. 增加 `--expected-root-identity-file` 和 `--graceful-only` 可选参数。未传参数时保持既有命令行兼容；桌面停止不自动降为强杀。
5. 比较预期完整身份与实际状态；旧停止请求不得作用于新 root。清理 state、request、status 与启动/写状态互斥，不能无条件删除同名文件。
6. 验证状态缺失、旧文件、启动失败、迁移中退出、停止超时、原实例已退出而新实例出现。最终成功判据是目标任务与进程回收，不能仅看脚本返回 0。

测试：复用 [test_runtime_launcher_common.py](../../tests/test_runtime_launcher_common.py)，补充根 `tests/test_full_launcher_lifecycle.py` 和 `tests/test_full_launcher_stop_contract.py`；与 C# 使用一致协议样本。测试优先用受控短进程，不真实训练或结束开发服务。

完成条件：新旧 CLI 调用均通过回归，早期停止与换实例竞态通过，Python/C# DTO 样本可相互读取；同步生产启停文档。状态文件和参数属于此步新增能力，之前步骤不能将其标记为已存在。

## 步骤 6：接入 Windows 进程和真实会话适配

主要位置：Infrastructure 的 `Http/`、`Processes/`、`Runtime/`、`Platforms/Windows/`。

实施内容：

1. 实现固定 health/HTML 探测：区分拒绝连接、超时、占用、无关响应与成功，不把任意失败当成未运行。仅显示模式不调用该启动前探测链。
2. 用绝对路径和固定参数启动根 full 脚本，工作目录为目标发行根，窗口隐藏、异步排空 stdout/stderr。清除发行不应继承的开发解释器覆盖。
3. 正确处理 `.bat` 的 shell 引号与空格、中文和特殊字符目录；参数不来自自由命令字符串，不使用 JSON 转义代替 shell 转义。
4. 原子登记创建任务，通过进程链和完整身份绑定本次 root；第三方抢先启动导致本次脚本退出时不得接管对方。
5. 实现 state/status 的有界读取和一致性核对；启动等待默认 300 秒、单次探测 2 秒、间隔约 1 秒。读取旧 running 不能掩盖当前失败。
6. 实现停止请求文件的具名序列化、graceful stop、停止后身份核对与请求文件清理。覆盖 root 尚未出现、重复退出、停止失败后重试。
7. 本次 root 已终止而外部新 root 接替时，不因 5600 仍存在就认定旧栈未停止；也不停止外部新 root。仅查看退出不进入此链路。

测试建议文件：`test_http_service_probe.cs`、`test_full_stack_controller.cs`、`test_windows_process_identity.cs`。替身进程覆盖大输出、非零退出、超时、错误身份、同目录替换与目录引号。

完成条件：Core 替身测试与真实适配契约都通过；只管理本次创建任务的证据可追溯；测试结束无本任务遗留进程。尚未接正式 UI 时不以人工杀进程代替正常退出验证。

## 步骤 7：实现主窗口、托盘和单实例

主要位置：Desktop 的 `Views/MainWindow`、`Controls/`、`Services/WindowService`、`TrayService` 与 Windows 单实例适配。

实施内容：

1. 实现默认 1280×800、最小 1024×720、自定义标题栏及统一窗口按钮。支持拖动、双击、缩放、最大化还原、Alt+Space、多屏 DPI。
2. 主窗口关闭、Alt+F4、任务栏关闭统一隐藏到托盘；普通最小化到任务栏。WebView 实例和后台任务仍由应用持有。
3. 托盘菜单固定“显示窗口、关于、分隔线、退出”，左键显示窗口。退出统一调用 Coordinator；仅查看跳过服务停止。
4. 使用显式 Shutdown；停止失败恢复窗口并显示原因与重试，托盘创建失败不能隐藏成无法找回的应用。
5. 同一用户和目标安装目录实现单实例锁与激活消息；重复启动不创建第二套服务，主窗口隐藏时恢复原窗口。激活 IPC 只传固定动作，不提供命令执行入口。
6. 验证初始化中重复启动、退出中重复启动和 Windows Explorer 重启；系统注销/关机按操作系统允许的期限尽力收尾，记录与正常托盘退出的差别。

完成条件：窗口关闭与应用退出分离，重复实例只激活已有窗口，隐藏再显示保留网页未保存编辑；所有退出入口汇入同一个用例，ViewModel/窗口事件无直接 Process 操作。

## 步骤 8：实现设置、关于和构建信息

实施内容：

1. 设置窗口绑定编辑副本：服务管理开关、目标项目目录、等待时间、主题；显示配置保存错误及“下次启动应用生效”。仅查看模式不要求补装 full 资产。
2. 保存和取消遵守 SettingsService 规则；目录/管理开关变更不改本次会话，窗口尺寸恢复限制在实际工作区。
3. 关于使用 Avalonia XAML/C#，显示 amvar launcher、自身版本、构建时间、Git commit、项目许可证、GitHub 和 amvar 官网。具体内容按产品设计，不复制后端版本为启动器版本。
4. 构建流程从具名元数据 class 序列化 JSON 并嵌入，复用 Infrastructure 的序列化边界；MSBuild 只组织生成步骤，不拼接 JSON 字符串，不新增常驻工具进程。
5. 构建时间使用构建时 UTC 并本地化显示；许可证随包离线读取，外部链接由明确点击交给系统浏览器。
6. 设置与关于各保留单一窗口，Esc/关闭仅关闭自身；未登录、后端离线或主窗口隐藏时仍可用。

完成条件：配置往返、取消、写入失败、下次生效、离线关于及构建元数据均有验证；重复打开无窗口/订阅泄漏；构建时间不是启动时间或 EXE 修改时间。

## 步骤 9：实现启动动画并完成界面接线

实施内容：

1. 实现 `StartupView.axaml`：统一资源、状态文字、不确定进度条、真实已等待时间及日志/重试入口，不显示虚构百分比。
2. ViewModel 将有序快照投影到文字、命令可用性和动画；隐藏、失败和退出时暂停无用动画，恢复窗口显示真实阶段。
3. 接入 WebView 初始化、导航、首屏标记与 30 秒首屏超时；加载失败属于网页错误，不擅自停止或重启后端。
4. 加载页与原生网页显隐交接，页面内动效统一约 180ms；不依赖透明 XAML 遮罩覆盖原生控件。
5. 接入首页、前进、后退、刷新、连接状态和设置入口；现有网页优先接收输入、复制粘贴、画布缩放和右键。
6. 短暂断连、打开设置、缩放和隐藏不重建 WebView，不自动刷新 Workflow；站外链接、下载及用户数据按步骤 4 已验证的适配执行。

完成条件：浅色/暗色、100%/150%/200% DPI、最小窗口和最大化均可用；无首屏闪烁、错误悬停色或标题栏被 WebView 遮挡；网页就绪不抢焦点。仅显示模式不出现“正在启动/停止视觉服务”的错误文案。

## 步骤 10：执行功能与竞态集成回归

使用受控测试服务、独立数据和测试工作流。固定 5600 被开发服务占用时，完整启动验收改在独立机器/虚拟机进行，不停止开发服务腾端口。

| 场景 | 必须确认的结果 |
| --- | --- |
| false，无 Python/full 资产 | 能启动桌面并载入外部页面 |
| false，外部服务迟到/断开/恢复 | 重试仅导航，Start/Stop 始终零调用 |
| true，已有第三方或同目录 full 栈 | 仅查看，退出后原服务仍活着 |
| true，无服务 | 只创建一轮 full 任务，完整栈就绪后显示网页 |
| 第三方与启动器同时启动 | 不把对方 root 当成本次目标 |
| 状态文件缺失、过期、不同轮次 | 不假报 running，不接管其他实例 |
| 迁移前/中、预热中、网页运行时退出 | 本次任务回收，后续组件不再启动 |
| 启动超时后继续等待 | 不重复创建服务 |
| 停止失败、超时、身份改变 | 原因准确，允许重试，不误停新实例 |
| true/false 配置切换 | 当前会话权限不变，下次启动采用新设置 |
| 隐藏恢复、重复启动 | 原窗口与网页编辑保留，没有重复会话 |
| 损坏配置后隐藏/退出 | 原配置不被默认值覆盖 |
| Vue 启动失败、WebView 初始化失败 | 与服务错误区分，退出仍可用 |

验证现有 Vue 关键路径：登录、Workflow 编辑、节点复制粘贴、文件导入导出、多文件上传、下载和 WebSocket。对测试工作流产生的修改在独立数据范围内清理。NativeWebView、托盘、窗口命中和输入法必须原生实测；浏览器工具仅验证网页部分。

完成条件：上述矩阵有通过结果或明确未验证原因；无隐藏的失败项；针对变更运行 C#、Python 和前端回归。测试名称和数量来自真实执行，不提前填入文档。

## 步骤 11：接入根目录发布和离线发行

修改入口为 [release_assembly.py](../../backend/maintenance/release_assembly.py)、[release_runtime_validation.py](../../backend/maintenance/release_runtime_validation.py)、[维护命令](../../backend/maintenance/main.py)及相关 release profile。

实施内容：

1. 在 launcher 范围提供可重复的 Release publish 步骤：`win-x64`、self-contained、禁用 trimming/AOT/单文件；先输出到 launcher 的构建目录。
2. 形成明确的启动器文件清单：EXE、.NET/Avalonia/native 依赖、固定版 WebView2、构建元数据、图标、项目许可证和第三方声明。
3. 由 assemble-release 显式选择桌面组件并复制到发行根；纯后端/edge 不强制包含桌面。新增 profile 字段按既有 schema 方式定义、校验并说明旧 profile 默认行为，不把计划字段称为当前已有。
4. 布局校验检查 RID、必要文件与 WebView2；错误路径、缺失资产、错误架构在组装/校验时报告。
5. 初次发行带默认示例；更新已有安装时保留配置、WebView 数据、业务数据和日志。先核对现有 `--force` 清理行为，不能用整目录覆盖冒充无损更新；必要时先组装到新目录，再按清单应用程序文件。
6. 验证普通用户、离线、无系统 Python/Node/.NET、无 Evergreen 环境；GPU profile 额外记录驱动和厂商运行时要求。

测试复用 [test_release_assembly.py](../../tests/test_release_assembly.py)、[test_release_runtime_validation.py](../../tests/test_release_runtime_validation.py)，新增桌面组件和更新保留用例。正式根目录内容从源码重新组装，不手工修补 `release/`。

完成条件：独立输出中双击 `amvar.launcher.exe` 可运行，两种模式符合契约；错误架构/资产缺失被正确识别；更新测试中的配置和业务文件内容保持一致。二进制资产不进入 git。

## 步骤 12：系统验收与交付

在可用 Windows x64 环境记录 OS build、依赖组合、测试日期与结果；验收重点为启动器自身功能和发行完整性。不以 Windows 1903 专项验证或完整历史版本矩阵作为发布前置条件，不将未测试环境写为已通过。

验收内容：

1. 两种管理模式、首次长启动、热启动、托盘运行、反复隐藏恢复及退出；记录等待时长、内存和句柄是否随重复操作持续增长，发现异常先定位再给结论。
2. 实际 WebView 的页面与输入能力，自定义标题栏/DPI/多屏，Explorer 重启和系统会话结束的差异行为。
3. 完整栈服务停止与遗留进程核对，第三方服务不被影响；采用独立发行包与测试数据。
4. 离线发布及覆盖更新保留，许可证、构建信息、日志和配置位置正确。
5. 完成受影响测试和 `git diff --check`，更新产品设计、工程架构、launcher README、生产部署说明与本计划的进度记录。
6. 确认本任务进程结束后清理测试临时目录；保留简明验收结论、版本组合和可复现步骤，不保留临时缓存为交付物。

交付包括可构建源码、发行构建步骤、默认配置示例、完整测试、实际功能验收记录、部署/使用说明及明确的未解决问题。未完成启动器功能和发行验收时可交付开发构建，但不能标注正式发行完成。

## 验证命令与结果记录

下列命令在相应工程和测试已创建后执行，本轮尚未执行。命令在仓库根运行；具体新增测试按本步实际文件选择，不因示例而运行需要真实服务的全部测试。

```powershell
dotnet restore launcher/Amvar.Launcher.slnx
dotnet build launcher/Amvar.Launcher.slnx -c Release --no-restore
dotnet test launcher/Amvar.Launcher.slnx -c Release --no-build
```

Python 源码回归先进入项目环境：

```powershell
conda activate amvision
python -m pytest tests/test_runtime_launcher_common.py tests/test_release_assembly.py tests/test_release_runtime_validation.py
```

前端标记变化使用现有工具链：

```powershell
npm --prefix frontend/web-ui run typecheck
npm --prefix frontend/web-ui run build
```

真实 full 栈验收参考 [test_release_full_stack_acceptance.py](../../tests/integration/test_release_full_stack_acceptance.py) 的显式环境约定；仅在隔离发行环境运行。新增参数和桌面发布命令在实现后补充经过验证的完整调用，不预写不存在的 CLI。

每步完成后在本表填写实际结果，禁止把未执行步骤勾选完成：

| 步骤 | 状态 | 构建/测试/环境结果 | 剩余问题 |
| --- | --- | --- | --- |
| 1–3 工程与 Core/JSON | 未开始 | 未执行 | 无 C# 工程 |
| 4 WebView 前置验证 | 未开始 | 未执行 | 需要可用 Windows x64 环境及固定版 WebView2 |
| 5–6 full 协议与进程适配 | 未开始 | 未执行 | 新启停/就绪协议尚未实现 |
| 7–9 原生界面与完整接线 | 未开始 | 未执行 | 依赖前置验证与用例 |
| 10 集成回归 | 未开始 | 未执行 | 需要受控服务与测试数据 |
| 11 发行集成 | 未开始 | 未执行 | 桌面发行组件尚未实现 |
| 12 发行功能验收 | 未开始 | 未执行 | 需要独立发行包与测试数据 |
