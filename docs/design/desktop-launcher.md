# amvar launcher 桌面启动器

Windows x64 源码、构建脚本、默认配置和自动化测试已实现。实际验证记录见 [实施记录](../architecture/desktop-launcher-implementation.md)；未验证的环境不视为已通过。

## 目标与技术

`launcher/` 与 backend、frontend 同级。它提供桌面窗口、服务启动管理和现有 Web UI 的入口，固定载入 `http://127.0.0.1:5600`。视觉业务继续使用 Vue 3 前端与 Python 平台，启动器不复制 Workflow、模型、训练或推理功能。

首版使用 .NET SDK 10.0.400 / 运行时 10.0.11、Avalonia 12.1.2、官方 NativeWebView 12.1.0、Newtonsoft.Json 13.0.4。目标为 Windows x64；不增加旧 Windows 兼容分支。其他 x64/ARM64 平台保留分层扩展边界，目前没有对应发行实现。

## 服务行为

| 配置与现状 | 启动 | 退出 |
| --- | --- | --- |
| manage_service=false | 直接载入网页，不检查 Python/full 资产 | 只结束启动器 |
| manage_service=true，已有外部服务可访问 | 只连接，不接管 | 只结束启动器 |
| manage_service=true，确认未运行 | 调用发行根 full batch，等待完整栈及网页 | 停止本次创建的栈，再结束启动器 |

默认 `manage_service=true`。配置不提供任意命令或自由 URL。端口超时、错误页面或其他程序占用端口时显示问题，不冒充“尚未启动”。终端手工开发和第三方启动的服务不会被接管。

服务管理方式、项目目录和启动时限在初始化时固定，设置修改下次启动生效；主题立即生效。退出优先于尚未结束的启动和导航。重试不会重复创建仍在启动的服务；停止失败保留错误与重试入口。

## 窗口与托盘

主窗口默认 1280×800，最小 1024×720；使用 36 DIP XAML 顶部栏，隐藏系统装饰和顶部边线，边缘拖动调整大小。左侧为设置、帮助、后退、前进，帮助下拉只有关于；中间为空白拖动区域，右侧为最小化、最大化/还原、关闭。顶部不显示图标、名称、主页或刷新。图标使用统一线条路径，不依赖字体字形。

F11 在原生界面和已载入网页中切换全屏，隐藏上下外壳栏；再次按下恢复之前的普通或最大化状态。全屏设置位于管理服务开关下方，名为“启动时全屏”，默认关闭、下次启动生效。临时 F11 切换不修改此开关。

关闭按钮、Alt+F4、任务栏关闭均隐藏到托盘，保留同一个 WebView 和未保存的网页编辑。普通最小化保留任务栏入口。第二次运行同一项目的启动器时只激活已有窗口。

托盘原生菜单从上到下固定为：显示窗口、关于、分隔线、退出。左键点击显示窗口。退出不弹通用确认框，只停止本次启动器创建的完整栈；退出处理中禁用重复提交，失败允许重试。托盘尚未建立时不会把窗口藏成无法恢复的进程。

关于与设置是独立原生窗口，宽 560 DIP，高度随内容调整，不使用 WebView 遮罩。辅助窗口保留系统标题栏，只允许关闭。设置只保留管理开关、启动时全屏、目录、等待时间、外观和保存/取消；关于保留构建信息及链接，删除重复描述。表单边框、按钮、悬停、焦点、亮暗色统一使用应用资源。

外壳配色与前端 `shared/styles/tokens/` 一致：暗色页面 #101010、面板 #171918、输入 #141615、悬停 #242825；亮色页面 #F6F7F9、面板白色、悬停 #ECEFF2。顶部文字与图标采用次级文字色。帮助与外观下拉使用圆角、统一边框和中性悬停背景，背景过渡为 120ms，选中项以勾选标记识别。

启动器首次载入、外观保存及系统主题变化时，把解析后的 light/dark 同步到当前 WebView。前端通过 `amvision:launcher-theme-v1` 固定事件调用现有 Preferences store.setTheme，同时更新状态、DOM 和 localStorage；不刷新当前工作流。只接受两个枚举值，不增加本机命令桥。独立浏览器的外观不受影响；当前契约为启动器到网页的单向同步。

## 原生启动页与网页交接

主窗口内容区先显示原生 XAML 启动页：项目图标、真实阶段、循环细进度条、已等待时间和日志入口。进度条只表示仍在工作，没有伪造百分比。

| 状态 | 显示 |
| --- | --- |
| 初始化、探测和网页预载 | 正在准备工作台 |
| 已创建 full 任务 | 正在启动视觉服务；展示等待秒数 |
| 等待超时 | 服务仍在启动，提供重试以继续等待 |
| 初始化或导航失败 | 明确错误和日志入口 |
| 退出 | 正在退出，等待本次服务结束 |

Python 阶段文件使用 starting/running/stopping/failed。完整栈 running 后还要检查 HTTP 页面与监听者归属。前端 Vue mount + nextTick 设置 `data-amvision-ui-ready=v1`；NativeWebView 导航成功且标记可读后展开页面，登录页也算就绪。

预载采用 1 DIP 原生宿主，显示 XAML 等待页；就绪后展开宿主。此方式避免原生 HWND 把 XAML 动画覆盖。后续站内导航和页面编辑不重新创建 WebView。

固定版 WebView2 预先指定 `launcher/tools/webview2/win-x64/`，独立浏览数据在 `launcher/data/launcher/webview/`。站内页面留在 WebView，外部 HTTP/HTTPS 交给系统浏览器；不开放通用 JavaScript 到 C# 的命令桥。上传、Blob 下载、剪贴板和 WebSocket 使用原生 WebView 能力，其实机测试范围单独记录。

## 关于

原生关于窗口采用视觉设置页的标签/值布局，显示：

- amvar launcher、启动器版本、构建 UTC 时间转本地显示、Git commit。
- PolyForm Noncommercial 1.0.0，点击后查看嵌入的离线许可证。
- GitHub 仓库 `https://github.com/ammm56/amvision` 和官网 `https://amvar.io`。

构建时间由 MSBuild 写入程序集，不使用应用启动时间或文件修改时间。发行阶段从具名 BuildInformation 对象生成 JSON，配置不能修改该信息。后端版本仍由视觉页面负责显示。

## 配置与保存

示例见 [launcher.example.json](../../launcher/config/launcher.example.json)。真实配置相对程序根目录读取：

```json
{
  "schema_version": 1,
  "manage_service": true,
  "start_fullscreen": false,
  "project_root": ".",
  "startup_timeout_seconds": 300,
  "theme": "system",
  "window": { "width": 1280, "height": 800, "maximized": false }
}
```

配置使用 class/record class 和 Newtonsoft.Json 处理。错误布尔值、未知字段或版本、重复键和不合法值均报告问题。损坏配置不会默认启动服务，也不会因隐藏或退出而自动覆盖；主动修复保存后才恢复正常使用。

窗口尺寸自动保存前重新读取磁盘有效配置，保留外部软件修改的管理设置。WebView 数据、配置、日志均位于程序目录；相对 project_root 基于程序位置解析，不依赖终端工作目录。

## 发行及验收

[发布脚本](../../launcher/publish-win-x64.ps1)仅在 `launcher/` 项目内生成 win-x64 self-contained 包。开发发布与正式发行均为根 EXE + `launcher/` 依赖目录。CPU/NVIDIA 的 `assemble-release --launcher-publish-dir` 显式选择启动器，纯后端发行无需桌面依赖。

发行组装会验证清单、RID、必要运行时和摘要，拒绝混入本地配置和数据。包含用户数据的安装目录不能使用整包清空重建作为升级，应组装新目录后只更新程序文件。详情见 [部署说明](../deployment/desktop-launcher.md)。

产品验收覆盖两种管理模式、启动期间退出、异常停止、原生窗口/托盘、单实例、未保存编辑保留、文件交互和离线运行时。完整视觉发行栈、系统关机、Explorer 重启、多屏 DPI 等未执行场景必须在实施记录中明确列出，不能用单元测试或普通浏览器结果替代。
