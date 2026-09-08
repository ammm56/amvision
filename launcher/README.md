# amvar launcher

状态：设计阶段，尚未创建可运行的 .NET 工程或发布桌面程序。

本目录是桌面启动器源码入口，与 `backend/`、`frontend/` 同级。技术基线为最新稳定版 .NET 10、C#、Avalonia 稳定版、官方 NativeWebView 和 Newtonsoft.Json；仅支持 x64、ARM64，首先实现 Windows x64。

配置文件 `config/launcher.json` 的 `manage_service` 默认 true：启动后检测 `http://127.0.0.1:5600`，已有外部服务只连接；未运行时调用发行项目根目录的 full 启动脚本，只管理本次会话实际启动的完整服务。设为 false 时直接载入该地址，不启动或停止服务，也不要求本机 full/Python 资产。第三方软件启动服务及终端手动开发均使用仅显示模式，启动器不启动开发后端或 Vite。配置改动下次启动应用生效。

Windows 首版目标为 Windows 10 1903 及之后版本、Windows 11 x64，不开展旧 Windows 专项兼容调查或以此阻塞实施。关闭主窗口时隐藏到系统托盘，右键菜单依次为“显示窗口”“关于”和底部的“退出”。退出仅停止本次启动器创建的 full 完整服务并结束启动器；外部已有服务始终不接管，包括同目录的 full 栈。主窗口使用自定义标题栏，启动等待页与关于窗口使用 C#、Avalonia XAML 原生实现。

工程层级、模块依赖、强类型模型、JSON 序列化和状态机见 [启动器工程架构](../docs/architecture/desktop-launcher.md)；逐步工作项、测试和完成条件见 [详细实施步骤](../docs/architecture/desktop-launcher-implementation.md)。采用 Core、Infrastructure、Desktop 三个生产工程，测试统一位于仓库根 `tests/launcher/`。下一步先建立可构建的解决方案和工程骨架，再实现模型、接口与状态迁移。

用户交互、配置内容和发布行为见 [桌面启动器设计](../docs/design/desktop-launcher.md)。本目录后续保存工程源码，构建结果复制到实际使用的项目根目录；发行包中的根目录是 `release/<profile-id>/`，安装后是该包的解压目录。
