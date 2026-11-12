# 设置页面现有实现核对

更新：2026-11-02。已取得当前九页亮暗截图，并核对运行状态DOM尺寸；九页均已逐页视觉核对。下文标注的CSS值与实际截图尺寸分开记录。

## 1. 页面骨架

| 依据 | 当前实现 |
|---|---|
| [设置路由](../../../frontend/web-ui/src/modules/settings/routes.ts) | /settings，fullBleed=true；category和section查询参数定位页面 |
| [页面模板](../../../frontend/web-ui/src/modules/settings/pages/SettingsDiagnosticsPage.vue) | 设置导航+独立滚动内容；偏好、启动页面、运行状态独立；系统环境和访问控制在同一列内分组 |
| [设置样式](../../../frontend/web-ui/src/modules/settings/settings.css) | grid-template-columns:220px minmax(0,1fr)；导航padding20px 12px、40px导航项、16px图标、分组标题15px图标；内容padding clamp(20px,2vw,32px) |
| [全局样式](../../../frontend/web-ui/src/shared/styles/index.css) | 全局导航展开220px、折叠64px；full-bleed内容padding=0；全局导航条目38px高 |
| [导航组件](../../../frontend/web-ui/src/shells/workbench/components/AppSidebar.vue) | 按权限显示入口；折叠时Logo按钮展开，默认不另放独立展开按钮 |

折叠Logo在当前CSS的hover/focus状态会替换成展开符号；这与常态额外增加展开按钮不同。默认设计图保留Logo，不另画第二个按钮。

“系统环境/访问控制”标题及缩进子项属于现有同列导航。不能为了避免第三层常驻栏而改成另一套五项导航。

## 2. 内容尺寸与主题

- 面板padding20px、gap20px、1px边框、8px圆角；保留现有表单/诊断面板，不改成带大片留白的展示卡。
- 偏好字段区最大680px；标签136px、控件280–420px、列间距32px；行最小64px，额外行间距8px。启动表单最大820px，标签152px，操作区同宽。
- 亮/暗按钮最小40px高、横padding16px、间距8px、6px圆角，保留Sun/Moon图标，不改成占满主区的巨大分段条。
- 服务摘要auto-fit，每项最小180px宽、54px高；列数随剩余宽度变化，不固定画成统计仪表盘。
- 信息网格默认两列，诊断表最小640px；长内容滚动，不缩字挤列。
- 用户目录176px+详情，间距20px。这是内容区的记录选择，不是新增第三层常驻导航，保留。
- workbench-main容器≤899px隐藏设置侧栏，改页内TabList及必要的横向子项；用户面板容器≤699px改横向目录；视口≤720px表单/元数据单列。1366×768不因高度较短就一律切成手机导航。
- [品牌token](../../../frontend/web-ui/src/shared/styles/tokens/brand.css)：#00D992、主按钮白字，间距4/8/12/16/20/24/32px；[亮色](../../../frontend/web-ui/src/shared/styles/tokens/light.css)：页面#F6F7F9、白色surface、正文#344054；[暗色](../../../frontend/web-ui/src/shared/styles/tokens/dark.css)：页面/全局导航#101010、surface#171918、正文#F2F2F2。
- 选中用品牌色与软色背景，普通hover中性；输入focus亮色#98A2B3、暗色#8B8B8B。按钮键盘焦点与输入焦点是不同token，不删除可访问焦点。
- settings.css引用--am-radius-lg，但brand.css没有定义；2026-11-02读取根元素计算样式，该变量为空。后续实现可统一到已有8px面板token，本轮未改CSS。

## 3. 功能与数据来源

| 页面/模块 | 当前行为及来源 |
|---|---|
| 偏好 | [preferences.store](../../../frontend/web-ui/src/app/stores/preferences.store.ts)即时更新locale/theme与localStorage；ThemeMode仅light/dark |
| 启动页面 | [SettingsStartupPagePanel](../../../frontend/web-ui/src/modules/settings/components/SettingsStartupPagePanel.vue)；项目由bootstrap，Runtime分页加载；选项为应用名+实例名，次级说明为状态和ID；保存前校验项目、实例、应用身份及app_mode |
| 启动保存 | isDirty/loading/validating控制保存；恢复默认立即重置该账号启动偏好，不影响语言外观；[存储定义](../../../frontend/web-ui/src/app/startup/startup-page-preference.ts)按principalId分键 |
| 诊断 | [service](../../../frontend/web-ui/src/modules/settings/services/settings-diagnostics.service.ts)读取/system/diagnostics，响应含generated_at、request_id、about、system、python_runtime、devices、services |
| 服务摘要 | backend-service、backend-worker、WebSocket、ZeroMQ、Database、LocalBufferBroker六项；不是部署/Runtime/Trigger计数表 |
| Backend Worker | [解析器](../../../frontend/web-ui/src/modules/settings/backend-worker-diagnostics.ts)；六项Topology元数据+Profile/状态/消费者/并发数/进程ID/心跳时间/原因七列表格 |
| 接口/平台能力 | API地址、WS地址、运行模式、Backend状态；平台能力默认收起，含认证、导出格式、摘要topic及Feature flags |
| 关于/环境 | 关于、主机路径/磁盘、Python环境/依赖、设备能力/GPU表分别成页；库安装不等于设备可用 |
| 会话 | 身份摘要、收起的凭据技术信息、可访问项目及账号来源；不展示真实Token明文 |
| 用户管理 | [SettingsAccountsPanel](../../../frontend/web-ui/src/modules/settings/components/SettingsAccountsPanel.vue)；刷新、创建、启停、删除、访问权限、Token创建/撤销/复制、密码重置；创建/权限/删除/撤销使用ConfirmDialog |
| 访问权限 | [UserAccessForm](../../../frontend/web-ui/src/modules/settings/components/UserAccessForm.vue)分允许页面、操作权限、项目范围；页面可见不等于API权限，保留未知权限值 |

## 4. 源码可确认的细节缺口

以下是设计待处理项，不代表已复现故障或已修复。

1. 诊断模板没有独立loading状态；空数据经Worker解析器默认成offline、0/0。首次读取应区分未获取与已确认故障。
2. 响应含generated_at，但页面未显示检查时间或刷新控件；只在进入相关页面/查询参数变化时读取，不是实时监控。
3. 启动已有脏状态判断，未见离开草稿保护；[浏览器存储](../../../frontend/web-ui/src/platform/storage/browser-storage.ts)直接写Storage，未见该页面存储失败专用反馈。
4. Token表用revoked_at决定徽标，过期时间另列；后续设计需区分过期与撤销，未撤销不能直接等同有效。
5. Frontend build、Backend version、Project可见范围、Auth mode等日常标签可改直观中文，不改数据模型。
6. [account-protection](../../../frontend/web-ui/src/modules/settings/account-protection.ts)保护唯一amvar用户，模板另限制删除自身/系统默认用户；不是完整的最后管理员角色保护。

## 5. 运行状态截图核对（2026-11-02）

- [亮色原页](references/设置/运行状态-当前实现-亮色.jpg)、[亮色下部](references/设置/运行状态-当前实现-亮色-下部.jpg)、[暗色原页](references/设置/运行状态-当前实现-暗色.jpg)，取得自当前IAB页，未设置视口覆盖。
- 浏览器视口1133×1142 CSS px，devicePixelRatio=1.5；导出截图1133×1142。未操作浏览器缩放，未独立读取缩放百分比。全局导航实际64px，设置导航220px；二者与源码相符。
- 实测表格约712.67px；七列依次116.78、99.77、290.93、50.48、53.08、54.30、47.32px。消费者长内容占用过宽，数字列缺少最小宽度/不换行保护，表头、PID及秒数被挤成竖排。此问题由截图与DOM共同确认。
- 元数据保持两列三行；下部接口配置和平台能力按原顺序存在，主内容独立滚动，侧栏保持固定。
- 本轮设计只优化表格列宽/单元格padding/自然换行和healthy→正常的显示文案。原始状态语义、字段和数据未改；刷新和最近检查留在后续状态设计，不进入此次母版。
- 亮暗实页心跳会随重新进入页面变化；设计配对固定使用亮色截图同一份值，避免造成主题差异。历史激活时间保留。
- 完成截图后已恢复亮色与原运行状态路由。未改源码、服务配置和业务数据。

## 6. 全页截图补充核对

已逐页取得偏好、启动页面、关于、系统信息、Python运行时、设备信息、会话与权限、用户管理的亮暗实际截图，保存在`references/设置/`。保留1133×1142视口和64px折叠导航，未调整浏览器缩放；完成后恢复亮色运行状态页。所有账号与启动配置均未改动。

本次确认的必要细节：

- 系统内存来自`available_bytes / total_bytes`，应明确显示“可用 / 总量”，不是已使用量。多个目录所在磁盘不能重复累加容量。
- OpenVINO、TensorRT、ONNX Runtime当前状态取`installed`；设计显示“已安装”，不得据此声称设备可执行。CUDA取`available`。
- 会话页的普通标签改为认证方式、操作权限、项目范围、项目ID和账号来源，保留必要专有名称。
- 用户Token表状态被截成“已启…”，需给状态列足够宽度；受保护amvar用户的禁用和删除保持不可操作。密码重置保持折叠，真实凭据不进入资产。
- 关于的动态品牌固定采用`amvar vision`静态帧，字体与Community Edition一致；不是重新设计品牌区。
- 偏好即时生效不加保存；启动页面是浏览器入口偏好，不是后端自启动控制。

九页正常主图均已完成配对核对。后续补异常、管理弹窗与短屏，范围见[状态覆盖](settings-state-coverage.md)。仅撤回被否定的设置图和失效提示词，其他分类及bak1保留。

## 当前设计优化与原始基线的关系

以上记录保留实际产品观察值；新设计的表单密度、权限选择控件、Worker信息层级和消费者展开方式见[细节优化](settings-detail-refinement.md)。原始基线用于核对功能，不要求所有细节保持原样。
