# 项目工作区 Design QA

日期：2026-11-04。范围：公共主题、抽屉/确认框及项目分类。实现为现有 Vue 3 产品，不是静态原型。

## 最新补齐核对

再次复核记录的创建/编辑结果未知、SDK 等待关闭、错误返回、列表定位等缺口已完成。最新证据见[项目分类补齐验证](docs/development/project-workspace-followup-validation.md)，下方首批/收尾记录属于历史范围。

- 同一工具输入并列查看了 1672×941 的已确认列表亮色、编辑亮暗源图与本轮实况。布局、统一遮罩、纯色主题、品牌选中、固定动作区符合规范；生成图示意字形/示例数量不作为产品数据和 CSS 定值。
- 新发现的抽屉焦点丢失已修复并通过真实冲突选择、Esc/内层确认检查；清空说明的恢复、完整 ID 定位优先也补齐测试。
- 69 项前端、2 项后端回归通过，类型检查和构建通过。真实创建、并发编辑、SDK 下载与版本冲突、删除回执、失效链接返回完成。
- 1366×768、1093×614、911×512 CSS 空间已核对；原生浏览器缩放快捷键在当前 IAB 未生效，不把等效空间检查称为原生缩放验收。
- 本批没有未处理的已确认视觉缺陷；已有导航/文字密度保持不变，不重新生成设计图。

final result: passed for reviewed follow-up scope

## 收尾核对结果

后续完整性复核确认的 7 项缺口已修复，本轮范围通过。详细结果见[收尾验收记录](docs/development/project-workspace-completion-validation.md)。本文件下方首批截图、测试数量和限制保留为历史过程，当前状态以本节为准。

| 原问题 | 当前处理与验证 |
| --- | --- |
| 删除未知结果丢失恢复入口 | 按账号/项目保存多项；失败不清除、不重复 DELETE；连续故障测试与真实生命周期通过 |
| 离页草稿与未知创建恢复 | 路由/beforeunload 保护、跨组件请求身份；真实返回/Esc 取消保留输入 |
| 概览展开、资源来源及刷新不全 | 全宽筛选分页、真实版本更新、观察时间；137 条记录跨页核对 |
| 失败混用空态 | 旧数据与时间保留、首次失败独立；失权清除；重复错误提示修正 |
| 资源权限与 SDK 容量 | 服务端裁剪、入口/表单一致；分页查询、明确超限、预览 revision；受控测试和真实下载通过 |
| 资源详情和短屏 | 真实版本数据、正确标签与共享字段样式；520 px 抽屉/760 px SDK，固定动作区可达 |

最终 56 项前端测试、TypeScript 与构建通过；后端 35 个不同用例完成检查及失败项修正后的复测。真实同数据[亮色概览](docs/design/frontend/verification/projects-completion-20261104/overview-light.jpg)/[暗色概览](docs/design/frontend/verification/projects-completion-20261104/overview-dark.jpg)、[信息抽屉](docs/design/frontend/verification/projects-completion-20261104/information-light.jpg)、[短屏 SDK](docs/design/frontend/verification/projects-completion-20261104/sdk-compact-dark.jpg)已核对。没有重新生成设计图。

原生刷新确认框与原生浏览器缩放未单独完成视觉验收；短 CSS 视口与 beforeunload 自动化已覆盖对应布局/逻辑。其他分类专用组件与长期生产稳定性单独验收。本次服务已停止，保留原有前端开发服务。

## 首批对照依据（历史）

- 视觉源：`docs/design/frontend/generated/项目/`，当前 15 组、30 张有效图；行为与 CSS 定值按 `docs/design/frontend/project-complete-design.md`。
- 真实截图：`docs/design/frontend/verification/projects-20261104/`。
- 逐项检查范围：项目列表、概览、信息/编辑、SDK 预览/范围/长列表、删除及短屏。
- 概览源图与 `overview-reference-light.jpg` 同为 1672×941；实际 CSS 视口 1672×941，deviceScaleFactor=1。信息与 SDK 全景截图为 1920×1080、density=1；比较容器和文字时以规格中的 520/760 CSS px 为准，不把不同画布大小直接作为像素偏差。
- 源图有示例数据、偏蓝文字及局部暗纹理。按已确认规范使用实际数据、中性文本、纯色背景；保留现有 220 px 导航和字体密度，不放大整个工作站去模拟生成图片中的文字比例。

源图与实现截图在同一次工具输入中并列查看：概览亮色、信息暗色、SDK 长列表暗色；之前已核对列表与信息亮色。长列表及 911×512 短屏额外检查正文滚动和动作区。信息抽屉标签/数值、概览表头/行以及 SDK 选择控件均可在截图中直接辨识，无需猜测小字。

## 首批发现与修复记录（历史）

| 级别 | 问题 | 修复与复核证据 |
| --- | --- | --- |
| P1 | 忙碌按钮禁用后失焦，SDK 下载后 Esc 不能关闭 | 公共容器恢复焦点；真实下载完成后 Esc 通过，新增组件回归 |
| P2 | 信息切编辑、SDK 范围子视图切换后焦点遗失 | 聚焦新输入；关闭归还原入口，真实页面和组件验证 |
| P2 | 信息标签/值间距散乱，缺少直接编辑入口 | 108 px 标签列、28 px 行距、底部编辑；`information-light.jpg` / `information-dark.jpg` |
| P2 | 长服务列表无限拉长，继续工作被挤出主要区域 | 概览列表有界滚动；`overview-light.jpg` / `overview-dark.jpg` |
| P2 | 最近更新缺少独立状态/时间列及类型图标 | 采用表头与四列表格、复用图标库；`overview-reference-light.jpg` 与源图再次对照 |
| P2 | SDK 范围视图重复显示生成摘要、短屏正文空间不足 | 范围页只保留项目、搜索、计数、分组列表和动作；`sdk-resources-dark.jpg`、`sdk-150-light.jpg` |

以上问题均有修改后重新截图/交互检查。此处记录首批已修复问题，不代表没有剩余问题。2026-11-04 完整性复核发现删除清理结果身份/颜色层级、概览展开和异常交互仍未达到设计要求，详见[完整性复核](docs/development/project-workspace-ui-completeness-review.md)。

## 五项核对

| 表面 | 结论 |
| --- | --- |
| 字体 | 沿用本地字体栈，正文 14 px、次要值 12–13 px，标题加权；普通参数不全加粗。与生成图的示意字形大小存在明确的产品密度差异 |
| 间距布局 | 无新增全局顶栏；四资源指标、双面板、继续工作；信息右侧覆盖、底层无位移；短屏正文滚动、底部动作可达 |
| 颜色 | 统一 #00D992 品牌绿、白色主按钮标记、中性 hover/focus、实色危险按钮；遮罩同时覆盖导航和正文；暗色无纹理 |
| 资产 | 复用现有 AMVAR 品牌组件与图标库。该分类无照片/插画，不引入假截图、装饰图片或自绘图标替代实际控件 |
| 文本数据 | 真实项目名称、资源数、状态和时间；缺失说明为“—”；SDK 依赖/删除错误有短原因，正常状态无长解释；中英日韩项目新增标签完整 |

## 首批交互与限制（历史）

- 27 项前端回归、类型检查和构建通过；真实 Chromium 0 个 pageerror。
- 亮暗同 DOM，项目抽屉 520 CSS px；标题/正文/动作在短视口内可达。
- 真实 SDK 下载、范围草稿取消、隐藏选择保留、信息编辑焦点、默认项目保护、独立测试项目删除回执通过。
- 1366×768 亮暗及 125%/150% 等效 CSS 可用空间检查通过；不是原生浏览器缩放的全面验收。
- 真实数据与源图不同，当前没有运行中的训练任务，因此不使用示例 37% 进度补位。最近更新来自当前任务与运行控制面；不伪造尚未存在的统一资源审计事件。
- 内置浏览器连接失效；上述截图与操作来自本机独立 Chromium。其他模块只做首屏冒烟，不等于全面业务或长期稳定性验收。

## 交付检查

- [x] 修复本批发现的焦点和布局问题并重新截图。
- [x] 亮暗、抽屉遮罩、SDK 长列表和短视口核对。
- [x] 同步 API、实施进度及真实验证记录。
- [x] 保留有效截图与结构化检查事实，移除失败过程截图。

概览全宽分页、筛选、真实资源更新和局部刷新属于已约定的项目分类目标，不能以不建设新审计系统为由从本阶段移除。复用现有资源元数据和控制面查询补齐即可。

首次完整性复核曾因删除响应未知恢复、草稿保护、权限、大清单与视觉差距阻止交付；后续已逐项修复，当前完成情况见上方收尾核对和关联验收记录。

final result: passed for reviewed project scope

### 追加验收状态（2026-11-04）

编辑保存和 SDK 下载的短反馈已补齐，复用现有全局轻提示组件；78 项相关回归和类型检查通过。随后在真实开发环境、内置浏览器完成编辑亮暗反馈和实际 SDK 下载核对，见[追加验证记录](docs/development/project-workspace-followup-validation.md)。用户明确取消浏览器原生缩放验收，不再作为项目分类完成门槛。项目分类本次约定缺口已完成；不将局部截图核对扩大为全平台或长期生产验收。

### 悬停与分隔线复核（2026-11-04）

顶部分类和“继续工作”已统一为内缩圆角、中性灰悬停，禁用时不高亮；查看入口补齐相同的圆角与键盘反馈。最近更新、全部记录和当前运行移除逐行横线。真实亮暗页面、数据跳转、分页、空筛选及抽屉操作已核对；75 项相关回归与生产构建通过。[修复与证据](docs/development/project-workspace-followup-validation.md#追加分类入口悬停与列表细节2026-11-04)。本次检查再次表明，自动化通过不能替代实际悬停等视觉状态核对。

### 整格入口修订（2026-11-05）

按最新要求取代上轮内缩悬停方案：顶部分类和“继续工作”整格响应中性灰悬停、整格可点击，移除分类竖线、箭头及快捷入口标题下的多余横线。容器保留外侧圆角，键盘焦点在内侧显示；少量入口均分宽度，窄窗口双列。真实亮暗截图、边缘点击、Enter/Tab 和窄窗口检查通过，39 项相关回归和类型检查通过。详见[最新验证](docs/development/project-workspace-followup-validation.md#追加整格分类入口2026-11-05)。

### 列表与操作边界修订（2026-11-05）

保留概览设计布局，项目活动列表与触发入口复用 ResourceTable、StatusBadge；概览记录整行点击，不新增查看操作列。主项目列表原有操作列使用公共 Button，编辑和删除仍在原有菜单。移除重复刷新提示；长名称单行省略，状态完整显示，概览记录统一 72 px 行高，中性悬停两端 6 px 圆角。亮暗真实数据、操作按钮、筛选及跳转已核对，53 项相关测试和类型检查通过。见[验证记录](docs/development/project-workspace-followup-validation.md#追加资源列表复用与操作边界2026-11-05)。

### 密度与重复信息修订（2026-11-05）

主列表恢复原有行距，实测默认项目 74 px；概览记录仍为 72 px。名称／类型占至少六成，状态和更新时间紧凑排列，保持完整显示。删除快捷栏的可见标题、空任务分组及当前运行内重复分类入口。原有布局、整行导航和操作列按钮不变；亮暗真实页面、窄窗口和导航复核通过，46 项相关回归及类型检查通过。见[最新核对记录](docs/development/project-workspace-followup-validation.md#追加列表密度与概览精简2026-11-05)。开发服务按用户要求保持运行。

### 普通反馈移除装饰色条（2026-11-05）

删除“项目已创建”提示的品牌绿左边框，恢复四边一致的中性细边框和 6 px 圆角；提示文字、查看及关闭操作保留。内置浏览器直接核对当前创建成功提示，四边颜色和宽度相同，无伪元素色条，见[真实截图](docs/design/frontend/verification/projects-overview-density-20261105/notice-neutral.png)。规则已写入[视觉与组件系统](docs/design/frontend/design-system.md#22-语义色)，普通反馈不得使用装饰性彩色侧边条。此次仅删除 CSS 装饰声明并补充规范，未重复运行业务回归或修改业务数据。

### 搜索输入框边框修订（2026-11-05）

项目搜索栏聚焦时，内部 input 被全局 `:focus-visible` 添加内侧阴影，与外框形成重复边框。已复用公共 `.input-with-icon`，由外框统一显示中性灰焦点边框，删除页面重复定义；公共输入区补齐宽度收缩约束，长项目 ID 不再挤压搜索图标。此规则同步写入视觉与组件系统。

代码核对覆盖数据集版本选择、训练数据选择、Workflow 节点库及自定义节点搜索；这些同类输入已有内框排除规则。实际浏览器验证项目与自定义节点搜索的亮暗外观、项目默认与鼠标／键盘聚焦、Enter 搜索真实“测试”项目通过，无页面横向溢出，搜索图标保持 18 px，内部边框为 0、阴影为 none。用户原筛选条件和项目数据保留，外观恢复亮色。

项目页面回归 10 项及 Vue TypeScript 检查通过。截图：[项目亮色](docs/design/frontend/verification/projects-search-focus-20261105/project-search-light.png)、[项目暗色](docs/design/frontend/verification/projects-search-focus-20261105/project-search-dark.png)、[节点搜索亮色](docs/design/frontend/verification/projects-search-focus-20261105/catalog-search-light.png)、[节点搜索暗色](docs/design/frontend/verification/projects-search-focus-20261105/catalog-search-dark.png)。开发服务保持运行。

### 项目原表格密度与重复操作修订（2026-11-05）

进一步追溯工作台重做前的 `e49b1050`：项目列表使用公共 `.resource-table`，单元格内边距为 `12px 14px`，并非新工作台的 `18px 16px`。本次据此恢复表头及数据行内边距；窄屏只缩减水平内边距，不再增加垂直留白。真实页面带“当前项目”第二行的记录由约 74 px 降为约 62 px，普通单行记录约 55 px；未设固定高度裁切内容。此项取代前面“74 px 已恢复原行距”的结论。

查看按钮补齐 16 px Eye 图标；更多菜单移除重复的 SDK 配置包及对应组件参数、事件类型，保留项目信息、编辑、删除，顶部 SDK 按钮保持可用。真实菜单核对和项目页面 10 项回归、Vue TypeScript 检查通过，见[实际页面](docs/design/frontend/verification/projects-compact-actions-20261105/list-and-menu.png)。

### 项目列表直接操作与满高布局（2026-11-05）

按最新要求替代更多菜单：查看、项目信息、编辑、删除全部使用直接图标按钮，保留 title 和 aria-label；默认／受保护项目隐藏删除按钮，无写入或删除权限时不显示对应操作。删除不再使用的 ProjectMenu 组件。选中行仅以已有品牌色背景和 aria-pressed 表达，不再追加“当前项目”第二行。

搜索栏宽度缩至 240 px，清除占位文字，保留搜索图标和可访问名称。列表单独使用满高布局：表格面板填满工作区余高，正文内部滚动、表头吸顶、分页位于面板底部；空态也保留满高容器，查看后返回恢复正文滚动位置。概览页布局不变。

真实数据验证两行均约 55 px，默认项目只有三个图标，普通项目四个图标；详情和编辑均能直接打开原抽屉。1236×1036 与 1236×640 视口均无外层溢出，分页保持可见，测试结束恢复原视口。新增受保护项目及只读权限、直接抽屉操作回归，共 12 项页面测试和 Vue TypeScript 检查通过；未删除或修改项目业务数据。见[列表截图](docs/design/frontend/verification/projects-direct-actions-20261105/list-light.png)、[短屏截图](docs/design/frontend/verification/projects-direct-actions-20261105/list-short.png)。

### 项目列表恢复内容高度与条件分页（2026-11-05，当前有效）

用户确认项目数量通常较少，满高白色区域削弱卡片层次、产生空白占位。本次撤回上节的满高布局、正文独立滚动及底部分页固定，恢复表格随实际行数增高，返回列表时恢复外层滚动。紧凑行距、直接图标操作、受保护项目隐藏删除及短搜索栏继续保留。

分页栏仅在 `offset > 0`、`hasMore` 或已知总数超过当前页容量时显示，避免末页记录少时丢失返回上一页入口。空态、不足一页及恰好一页均不显示分页栏。真实两条记录的表格面板约 151 px，分页不渲染，见[最新有效截图](docs/design/frontend/verification/projects-direct-actions-20261105/list-content-height.png)。项目页面 17 项回归通过，包括已知／未知总数与末页边界；视觉规范同步更新。前节满高截图仅为已撤回方案的检查记录，不再作为实施依据。

### 创建后的完整列表与中性下载反馈（2026-11-05）

创建成功不再调用项目 ID 搜索定位，清空已有筛选、返回第一页并选中新项目，保留简短创建反馈和查看入口。后端已有按更新时间倒序排序，使用原列表接口即可显示新记录；用户主动定位的行为保留。

公共 Toast 的普通成功／信息样式改为中性色，警告和错误语义色保持；SDK 下载使用信息提示“已开始下载”。创建前有／无筛选、分页恢复、同名项目、SDK 成功／请求失败／浏览器触发失败、轻提示计时和关闭等 40 项回归通过，Vue TypeScript 检查通过。真实开发环境以不包含访问凭据的配置包触发下载，提示背景为白色、边框 `rgb(228,231,236)`、图标灰色，见[实际下载反馈](docs/design/frontend/verification/projects-feedback-20261105/sdk-neutral-light.png)。本次未额外创建或改写项目业务数据，创建后的列表逻辑由组件回归覆盖。

### 项目切换与创建入口（2026-11-05）

行点击不再等待重复的项目详情请求，直接使用列表已有的项目与摘要更新当前上下文；“查看”直接导航，最新数据及权限由概览页原有请求核对。连续选择和重复点击不新增请求，不保留上一项目的摘要。顶部及创建抽屉命名恢复为“创建新项目”。

26 项相关回归、Vue TypeScript 检查通过。内置浏览器使用现有三个项目验证名称／整行选择、查看／返回及创建抽屉打开／取消，控制台无 error，页面无横向溢出；未改变项目业务数据。见[实际页面](docs/design/frontend/verification/projects-switch-20261105/list.png)。

### 项目操作列补回文字（2026-11-05）

按最新要求，操作列改为带图标与文字的“查看／详情／编辑／删除”，替代前面的纯图标方案。沿用公共小型按钮，默认项目仍不显示删除，其他权限条件及点击行为不变。操作列宽度增加到 330 px，按钮文字保持单行，窄屏使用表格容器横向滚动。

20 项页面回归与 Vue TypeScript 检查通过。内置浏览器验证普通项目四个按钮、默认项目三个按钮，以及详情抽屉打开／关闭。1280 px 视口无页面横向溢出，按钮高度 30 px、数据行约 55 px，控制台无 error。见[操作列截图](docs/design/frontend/verification/projects-actions-text-20261105/list.png)。

### 项目抽屉动效和删除层级（2026-11-05）

先核对实际详情、编辑、创建及删除流程，再修复共用动效和信息层级：

| 检查步骤 | 发现与修复 | 核对结果 |
| --- | --- | --- |
| 详情／创建打开 | 条件挂载缺少 appear；补齐右侧 200 ms 滑入与遮罩过渡 | 真实页面亮暗可用，布局保持不变 |
| 编辑、取消、保存 | 直接卸载截断退场；改为退场后关闭并恢复焦点 | 自动化覆盖保存和快速重开；实际草稿继续编辑／放弃正常 |
| 删除预检 | 长 ID、全部内部资源数同时展开；改为名称确认、主要数量和按需明细 | 面板由 640 px 收紧到 520 px，亮暗一致，危险动作仍受预检限制 |
| 阻止与结果未知 | 保留直接可见的原因与恢复动作，技术编号按需展开 | 回归覆盖阻止、响应未知、清理失败，核对不会重复发起删除 |

55 项相关回归和 Vue TypeScript 检查通过；真实页面关闭后无残留模态隔离，控制台 warning/error 为空。本轮没有删除或改写业务记录。截图与详细记录见[追加验证](docs/development/project-workspace-followup-validation.md#追加项目抽屉动效与删除确认2026-11-05)。样式规范已同步；本结论限定为本次项目抽屉与删除流程，不扩大为所有页面已无缺陷。

### 项目操作收回菜单（2026-11-05，当前有效）

按最新要求替代逐项按钮：保留“查看 + …”，详情／编辑／删除收回菜单，操作列从 330 px 缩为 144 px。“查看”改用打开文件夹图标，移除 Eye 图标。默认项目不显示删除，只读账号菜单仅有详情；菜单不重复加入 SDK 操作。复用 Reka UI 菜单，并在其关闭焦点回收后打开业务面板，避免菜单把抽屉焦点抢回背景。

20 项项目页面回归及 Vue TypeScript 检查通过。真实内置浏览器验证普通项目菜单、默认项目删除保护、详情与删除确认入口、关闭后焦点返回、Escape 关闭菜单；未提交删除或修改业务数据，控制台 warning/error 为空。见[实际菜单](docs/design/frontend/verification/projects-menu-20261105/list-menu.png)。服务保持运行，本次未创建 `.tmp` 临时产物。

### 删除确认与完成反馈继续精简（2026-11-05，当前有效）

删除明细、资源数量汇总、技术信息及手动“核对结果”全部移除。确认面板只保留名称、不可撤销说明和名称确认；完成面板只保留“项目已移除”、项目名称、绿底白勾和关闭按钮。完整资源预检、权限和后端 Project ID 校验继续有效。

后端原有后台清理不变。前端自动读取删除回执：处理中串行间隔 1 秒查询，短暂网络故障间隔 5 秒再读；结果明确完成或失败后停止，失权停止；只重读、不重发 DELETE。关闭面板终止未完成 GET 和定时器，原有未完成记录仍保留；相同状态不反复刷新项目列表。只有后端返回 `deleted` 才显示成功，失败原因保持直接可见。

45 项组件与页面回归、Vue TypeScript 检查通过，覆盖清理完成、断线后恢复、失败／失权停止、取消查询及迟到响应。内置浏览器核对真实项目的简化确认、菜单返回和默认禁用状态，控制台 warning/error 为空；未删除现有业务项目。成功状态及自动查询链路由组件回归验证，本轮未另建项目执行真实删除。证据：[简化确认](docs/design/frontend/verification/projects-delete-simple-20261105/confirm-light.png)。开发服务保持运行，本次未产生 `.tmp` 产物。

### 创建成功统一轻提示（2026-11-05，当前有效）

移除列表内“项目已创建 · 名称 · 查看”提示条及其状态、关闭入口、专属样式；创建成功与编辑成功共同使用右上角公共中性 Toast，显示“项目已创建”，按现有规则 4.5 秒后自动消失。仍在服务器确认成功并完成抽屉退出后触发；创建失败不提示成功。创建后显示完整列表首屏并选中新项目，不添加搜索条件。

45 项组件／页面回归及 Vue TypeScript 检查通过；内置浏览器确认当前提示条已消失、真实两条项目记录保留。Toast 事件与默认时长由已有组件回归核对，本次未另外创建业务记录。样式规范已同步，开发服务继续运行。

### 数据集工作区实现核对（2026-11-05）

实现依据：[数据集列表母版](docs/design/frontend/generated/数据集/数据集列表-亮色.png)、[标注样本网格](docs/design/frontend/generated/数据集/标注样本网格-亮色.png)，以及数据集的抽屉、结构、导入/导出、管理与异常状态规格。对照使用源图与真实浏览器截图；桌面视口统一为 1672×941，另检查 1280×640 短屏。没有生成替代实现截图的设计图。

| 核对范围 | 结果与适配 |
| --- | --- |
| 全页布局 | 保留平级主导航、四类管理标签、页面内工具栏、浮动表格；版本页保留统计、五个内容标签、筛选和样本网格。无额外全局顶栏 |
| 导航与密度 | 复用已完成项目分类的实际导航宽度、字体、控件尺寸；不逐像素复刻生成图的放大文字。短屏可由 Logo 展开，未增加另一个展开按钮 |
| 字体与内容 | 名称强调、说明弱化；普通内容不全加粗。真实数据替代示意名称与版本号，任务类型中文化，长名称单行省略并提供完整 title |
| 颜色与图标 | 品牌绿用于主操作和选择；悬停/输入焦点中性。复用 Lucide 与公共按钮。标注颜色按类别区分，不能把所有对象染为品牌绿 |
| 表格 | 使用 ResourceTable 原有圆角、行距和悬停；少量数据不强行铺满剩余高度，无分页时不显示分页栏。早期的划分列与窄容器水平滚动方案已由同日下方修订替代 |
| 抽屉 | 复用 SideDrawer，右侧覆盖不挤压背景，遮罩覆盖导航和内容；200 ms 进出动画、焦点恢复及未保存草稿确认；实际验证取消放弃后输入保留 |
| 图像 | 缩略图、大图使用真实图片和真实框；类别、尺寸及对象坐标可查看，开关标注与前后切换不改写源数据 |
| 细节修正 | 样本深链接改用请求代次而非 Vue 代理对象身份比较；切版先使旧样本请求失效；格式检查状态和比较计数标题可读化 |

已在同一次核对中查看完整页面，并重点检查列表表头/行、样本网格首行、抽屉头部/底部和标注区域。最终证据：

- [列表亮色](docs/design/frontend/verification/datasets-workspace-20261105/catalog-desktop-light.png)、[列表暗色](docs/design/frontend/verification/datasets-workspace-20261105/catalog-desktop-dark.png)、[列表短屏](docs/design/frontend/verification/datasets-workspace-20261105/catalog-short-light.png)。
- [样本网格亮色](docs/design/frontend/verification/datasets-workspace-20261105/samples-desktop-light.png)、[样本网格暗色短屏](docs/design/frontend/verification/datasets-workspace-20261105/samples-short-dark.png)、[样本大图](docs/design/frontend/verification/datasets-workspace-20261105/sample-viewer-light.png)。
- [编辑抽屉](docs/design/frontend/verification/datasets-workspace-20261105/edit-drawer-dark.png)、[样本信息](docs/design/frontend/verification/datasets-workspace-20261105/sample-info-short-dark.png)、[文件关联样本](docs/design/frontend/verification/datasets-workspace-20261105/file-associated-samples-dark.png)。

相关后端 112 项、前端 63 项回归通过，生产构建通过。真实 worker 已完成独立副本的导入、检查、派生、比较及所选样本导出。用户授权后已正常重启 worker，补验版本更新时间、排队/运行中取消、失败后继续处理均通过；服务 ready，部署 6/6、Runtime 10/10、Trigger 8/8 就绪。设计中的未来异常、连接器参考和三维资产专属管理不以本轮二维工作区替代；本轮结果不等于长期生产全面验收。详细范围、迁移、接口和验证见[实施记录](docs/development/dataset-workspace-implementation.md)。

### 数据集列表与版本修订复核（2026-11-05 22:50）

以用户最新修订覆盖旧图的多余字段，保留已确认的整体布局、公共控件、主题和抽屉交互。

| 项目 | 最终结果 |
| --- | --- |
| 列表 | 删除数据划分、重复项目名称；列宽随容器分配，长名称及说明省略，查看/更多保持可操作 |
| 版本 | 自动 v1/v2/v3，实际 worker 创建 v4；详情下拉与来源/版本表使用同一持久化序号，不替换资源 ID |
| 查看页 | 补版本选择与完整列表入口，修正类别颜色点、文件名省略、操作列和来源链接；切版数据匹配 |
| 导入详情 | 类别 ID/名称按实际报告显示，卡片标题与内容顶端对齐；划分表、类别表不横向滚动 |
| 原始报告 | 完整长路径在容器内换行；纵向滚动，未截断 JSON 原值 |
| 1024×768 | 展开导航时根宽 1024，类别表 746px、导入表 365px、报告 683px，测得各自 scrollWidth 与 clientWidth 一致；收起导航也已核对 |
| 亮暗与错误 | 同源布局、主题中性色和品牌绿用途一致；最终独立验收标签页未记录 warning/error；恢复亮色并清除临时视口 |

最新证据（同名文件只保留最终结果）：

- [列表亮色](docs/design/frontend/verification/datasets-refinement-20261105/dataset-list-1024-light.png)、[列表暗色](docs/design/frontend/verification/datasets-refinement-20261105/dataset-list-1024-dark.png)。
- [版本选择与真实标注](docs/design/frontend/verification/datasets-refinement-20261105/dataset-versions-1024-dark.png)。
- [导入详情](docs/design/frontend/verification/datasets-refinement-20261105/import-details-1024-light.png)、[长报告](docs/design/frontend/verification/datasets-refinement-20261105/import-report-1024-light.png)。

版本/迁移/工作区/导入导出相关回归 57 项、前端数据集 10 项通过；最后接口修订复核 4 项通过，TypeScript 和 Vite 正式构建通过。既有 Workflow/CloudViewer 构建体积警告未在本次数据集修订中处理。只读生产数据与独立副本验证的边界见实施记录。

### 目录树与样本更新（2026-11-05 至 2026-11-06，历史阶段，版本语义已修正）

按用户最新要求简化功能，保留已确认的导航、主题、表格和抽屉。关联样本、人工复核、外部标注交接/回传检查入口与闲置组件已移除；早期设计及验收截图中的这些入口仅属历史记录。当前规则和中文提示词已同步。

| 核对项 | 结果 |
| --- | --- |
| 数据结构切换 | 使用真实目录树，独立维护展开与选中状态；离开标签仅隐藏，不卸载重建。返回原目录立即显示已加载文件；异步旧响应不能覆盖新目录或新版本 |
| 目录与预览 | 分层按需读取目录、文件分页，叶目录不保留无效展开箭头；图片/文本使用共享 SideDrawer，关闭后返回原位置；无关联样本入口 |
| 添加与删除 | 添加 ZIP 和删除所选进入同一更新页，来源版本、现有数、移除数及撤回操作明确；确认才创建新版本；没有改变旧版本或其外部引用 |
| 结果与异常 | 版本创建结果只显示来源/移除/剩余数量与查看入口，不显示无关分组说明；空更新、全删不补样本、坏包、错误来源、关键点冲突均有阻止；未知提交不自动重发 |
| 草稿与权限 | 沿用数据集读写权限；离开有文件或删除选择的草稿先确认，取消离开保留输入；无法生成空版本 |
| 1024×768 | 展开导航时主区 763px、文件表 575px、抽屉 679px，scrollWidth 与 clientWidth 一致；暗色更新表单 761px 无水平滚动，路径和文件名省略保留完整 title |
| 亮暗与控制台 | 中性色悬停、品牌绿选择、同一遮罩覆盖导航和内容，抽屉不挤压背景；最终验证时段没有新增 warning/error。日志内 23:24 的开发热更新失败早于最终修复，后续页面与正式构建通过。检查后恢复亮色和默认视口 |

真实开发 worker 完成独立副本 v4（2 张）→ v6（4 张/6 对象）→ v7（3 张/5 对象），首轮临时 v5 已清理且编号不复用。最终 COCO ZIP 含 4 张图片、6 个对象，图片 ID/文件名唯一、标注引用有效，旧版本不变。[真实验证数据](docs/design/frontend/verification/dataset-sample-management-20261105/live-validation.json)。

后端本轮 47 项回归通过，图片 ID 合并修订后复测其中 2 项集成测试；前端 6 文件/14 项通过，TypeScript 与 Vite 正式构建通过。现有 Workflow/CloudViewer 分包体积警告仍存在。服务 ready，部署 6/6、Runtime 10/10、Trigger 8/8；独立 worker generation 52 正常运行，服务按要求保持运行。

最终截图：[更新样本](docs/design/frontend/verification/dataset-sample-management-20261105/sample-update-before-submit.png)、[删除选择确认](docs/design/frontend/verification/dataset-sample-management-20261105/remove-sample-confirm.png)、[目录亮色](docs/design/frontend/verification/dataset-sample-management-20261105/structure-1024-light.png)、[目录暗色](docs/design/frontend/verification/dataset-sample-management-20261105/structure-1024-dark.png)、[图片抽屉](docs/design/frontend/verification/dataset-sample-management-20261105/file-preview-1024-dark.png)、[暗色更新表单](docs/design/frontend/verification/dataset-sample-management-20261105/update-form-1024-dark.png)、[新版本样本](docs/design/frontend/verification/dataset-sample-management-20261105/samples-updated-final.png)。

### 当前版本样本修改与手动创建版本（2026-11-06，当前有效）

用户修正版本语义后，添加 ZIP、删除所选改为保存到当前版本，只有独立的“创建新版本”分配新 vN。页面保留当前版本编号与样本数量，提交按钮为“保存修改”。旧图中的自动新建版本不再作为实现要求。`_verified` 来自验收副本的类别重命名，不是系统标注状态。

- 真实验收副本：v7 样本 3 → 5 → 4，版本 ID 不变；显式创建的 v8 保留创建时 5 个样本，图片均可读取。更新失败、过期提交、并发修改、导出图片关联与原版本快照隔离均已回归。
- 目录树在初次展示时区分分支与叶目录；不再需要先点击叶目录才能消除箭头。
- 筛选控件保持可读宽度，窄屏不互相覆盖；网格/列表和标注显示移至选择操作行右侧。1024px 亮暗、展开/收起导航根宽和内容宽均为 1024px，无水平溢出。检查后恢复亮色、收起导航和默认视口。
- 后端相关 56 项覆盖，最终样本集成 2 项复核通过；前端 6 文件/15 项、TypeScript 通过，正式构建通过（既有大分包提示仍在）。完整语义、接口、部署边界与故障保护见[实施记录](docs/development/dataset-sample-management.md)。

最新证据：[真实数据](docs/design/frontend/verification/dataset-polish-20261106/live-validation.json)、[样本页](docs/design/frontend/verification/dataset-polish-20261106/samples-after-light.png)、[更新当前版本](docs/design/frontend/verification/dataset-polish-20261106/update-current-light.png)、[目录树](docs/design/frontend/verification/dataset-polish-20261106/tree-after-light.png)、[1024 亮色](docs/design/frontend/verification/dataset-polish-20261106/samples-1024-light.png)、[1024 暗色](docs/design/frontend/verification/dataset-polish-20261106/samples-1024-dark.png)、[展开导航](docs/design/frontend/verification/dataset-polish-20261106/samples-1024-expanded-light.png)。开发服务保持运行。

### 数据集设计逐页对照与样本生命周期核对（2026-11-06）

已对照数据集已确认的列表、样本网格、目录树、类别与划分、版本与来源、创建版本两步、抽屉、大图和导出设计。遵循最新要求：添加/删除保存当前 vN，创建版本由独立按钮明确执行；不恢复已删除的复核、交接等入口。

修正创建版本表单/单选样式、检查摘要和版本说明；版本切换原子更新、过期响应隔离、旧选择校验、版本下拉重复载入、历史分页缓存；目录保留内容加载、标注对象高亮、同序切图；历史导入计数和历史任务重开不受后续样本修改影响。1024px 亮暗、四个管理标签、编辑和文件抽屉核对通过，无水平溢出。

真实验收副本 v8（5 样本）手动创建 v9；v9 添加 2 后为 7、删除 1 后为 6，ID/编号不变，v8 仍为 5。全部图片可读，导出 COCO 为 6 图片/10 标注，历史导入保持 7/新增 2。过期写入返回 409。前端 20 项回归、后端相关 14 项及补充 API 3 项、TypeScript、生产构建通过。服务 ready，部署 6/6、Runtime 10/10、Trigger 8/8，开发服务保持运行。

[完整修复、边界和截图](docs/design/frontend/verification/datasets-design-alignment-20261106/README.md)。本轮未将旧完整产品设计中的 RGB-D/点云数据集专用查看器视为已实现；未改 Runtime/Trigger/.NET SDK 数据面。

### 数据集列表七列与操作样式（2026-11-06，当前有效）

对照来源：[亮色设计](docs/design/frontend/generated/数据集/数据集列表-亮色.png)、[暗色设计](docs/design/frontend/generated/数据集/数据集列表-暗色.png)。同尺寸参考截图与页面截图对照，保留业务布局、七列、普通正文版本与数量、品牌绿文字查看、简短菜单。

| 核对项 | 结果 |
| --- | --- |
| 工具栏 | 搜索、任务类型、可用状态、刷新整组右对齐；控件不相互遮挡 |
| 列与文字 | 恢复数据划分；版本与数量均为正文 14px；样本单位为张，类别单位为类；数据集说明放详情 |
| 行与操作 | 行高 44px，查看无文件夹图标/外框；省略菜单为详情、编辑、导入、导出；普通悬停中性灰 |
| 1024×768 | 展开导航：页面 1024/1024、表格 762/762（client/scroll）；亮暗无横向溢出，长名称/划分/时间单行省略，title 保留原值 |
| 交互 | 搜索测试1为唯一结果，清空恢复五项；更多菜单和详情抽屉正常；查看进入真实最新 v9，返回列表正确 |
| 工程检查 | TypeScript 通过，git diff --check 通过；浏览器本轮 warning/error 为空；服务保持运行 |

按已确认的后续约定，保留公共导航尺寸与折叠方式、不重复项目名、没有第二页时隐藏分页，并使用纯色主题；不复制早期生成图的暗角、纹理或放大的控件比例。页面使用五项真实数据，不替换成设计图三项示例。相关布局一致性已验证，本记录不声称截图与示例数据逐像素相同，也不扩大为其他数据集页面的全量验收。

最终证据：[默认列表](docs/design/frontend/verification/dataset-catalog-style-20261106/list-final-light.png)、[桌面亮色](docs/design/frontend/verification/dataset-catalog-style-20261106/desktop-light.png)、[桌面暗色](docs/design/frontend/verification/dataset-catalog-style-20261106/desktop-dark.png)、[1024亮色](docs/design/frontend/verification/dataset-catalog-style-20261106/1024-light.png)、[1024暗色](docs/design/frontend/verification/dataset-catalog-style-20261106/1024-dark.png)、[更多菜单](docs/design/frontend/verification/dataset-catalog-style-20261106/menu-light.png)。

Final result: passed（本轮列表范围）。

### 数值色块与矩形提示（2026-11-06，历史，已由分组表头替代）

用户最终选定原参考图的颜色关系与分行提示，仅调整 EVA 色调并删除底部尖角。此前单行原生提示与珊瑚/石墨颜色分组已被替换。搜索框靠左，筛选靠右。

- 已打开并核对最新生成局部图及真实页面截图：两组数字分别蓝/紫和青绿/橙黄/紫，24px小色块，普通矩形提示没有箭头。实际页面保留既有导航和纯色主题，不照搬生成图的比例或阴影误差。
- 亮暗配色文字对比度均大于4.5:1；1024×768展开导航时页面1024/1024、表格762/762（client/scroll），25个数值未截断，所有行44px。搜索与表格左边缘一致。
- 真实数据1,174样本、3类、train939/test117/val118映射正确，零值保留；两行/三行提示、键盘聚焦及Escape关闭已实测。没有鼠标移动API，本轮不声称实际鼠标悬停已自动化验收；使用已有Tooltip组件的标准hover处理。
- TypeScript通过；本轮没有更改数据、后端、Runtime/Trigger或公共表格。完整色值、截图和边界见[验证记录](docs/design/frontend/verification/dataset-count-badges-20261106/README.md)。

Final result: passed（本轮数值色块、布局与矩形提示范围）。

### 版本、记录与样本工作区（2026-11-06）

按已确认数据集设计及最新数值要求，统一版本列表、导入/导出记录、详情、类别和版本来源的数值组件；补齐列表来源、文件、vN 信息，历史统计保持任务快照。样本页修正统计条、筛选/视图控件、卡片与批量选择层级，文件树操作移至文件区；空态可继续添加样本。

真实条码版本 609 张 / 982 对象 / 2 类，划分 520/89/0；v9→v8 切换与图片/统计同步、选择/取消修改、清除筛选、大图切换均正常。三个列表、工作区、报告和详情在 1024px 无水平溢出；亮暗同源布局，矩形提示无箭头、键盘可达。前端 22 项、API 3 项、TypeScript 和差异检查通过。服务保持运行。[完整核对与亮暗截图](docs/design/frontend/verification/dataset-pages-polish-20261106/README.md)。

Final result: passed（本轮指定页面与交互范围）。

### 数据集分组表头（2026-11-06，历史，已由原图斜线显示替代）

用户确认第 2 张分组表头后，撤销此前数值色块方案。已同步数据集、版本、导入/导出记录和相关详情的同类显示。搜索靠左、筛选靠右；两层表头、普通中性数字、无箭头矩形提示。旧记录保留当时的证据，不作为当前实现目标。

同次对照所选原图及 1356×1160 实际截图，核对布局、字体、间距、颜色、图标和文本。修正 1024px 样本子标题截断、展开导航时导出状态过窄，以及详情统计继承等宽字体的问题。四类列表在亮暗、展开/收起导航时无横向滚动，真实数值及历史快照正确，搜索/菜单/详情/版本切换正常。TypeScript、数据集 22 项回归及差异检查通过；控制台 warning/error 为空。

[所选设计](docs/design/frontend/generated/数据集/列表数值分组表头-亮色.png) · [实际页面](docs/design/frontend/verification/dataset-grouped-counts-20261106/datasets-light-1356.png) · [完整验证和亮暗截图](docs/design/frontend/verification/dataset-grouped-counts-20261106/README.md)。已恢复亮色及默认视口，开发服务保持运行。

Final result: passed（本轮分组数值、指定页面交互及窄屏适配范围）。


### 数据集原图斜线数值显示（2026-11-06，最新有效）

依据最新确认，四类列表恢复单层表头，样本/类别显示“1,174 张 / 3 类”，数据划分显示“train 939 / test 117 / val 118”。移除分组子表头，收窄版本列。修正公共表格样式误将数值设为小号灰字的问题：统一14px、21px行高和正文颜色。重复点击当前标签不再清空列表。历史任务快照及数据语义保持不变。

同次对照原设计与1672×941实际截图；在真实开发环境核对四类列表、亮暗主题、1024px展开与收起导航，均无水平溢出。数据行44px，表头单行，完整数值提示无箭头。浏览器控制台无warning/error，专用数值测试2项通过，TypeScript检查通过。恢复亮色、收起导航和默认视口；服务保持运行。

截图：[实际列表](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/slash-final.png) · [原图尺寸对照](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/slash-light-desktop.png) · [暗色1024px](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/slash-dark-1024.png)。

Final result: passed（本轮四类列表的数值、表头、布局与标签切换范围）。


### 数据集查看页细节与生命周期复测（2026-11-06）

对照标注样本网格设计，恢复统计区数值在上、标签在下的层级，数据划分保持普通斜线文本；列表“最新版本”简化为“版本”。目录读取失败时清除旧目录文件，避免新路径配旧文件，并保留重试入口，不误报空目录。复用现有 Vue 组件与主题，无 API 或持久化变更。

真实开发环境使用验收副本 dataset-5996dd3c8b7e421dbe9ad64bd2ee2585：手动创建 v10（dataset-version-2274c0f135b5，6 样本），上传现有 detection-coco-min.zip 后8样本，删除本轮新增 train-1.jpg/val-1.jpg 后恢复6样本，整个样本修改过程保持 v10。切换 v8 为原有5样本，切回 v10 为6；目录树叶节点、目录切换、网格与标注显示核对正常。1024px暗色网格和目录宽度均为1024，无横向溢出。恢复亮色与默认视口；开发服务保持运行。

TypeScript检查通过；现有数据集前端22项通过，新增目录失败重试回归通过（目录文件4项）。控制台无warning/error。未修改生产数据或Runtime/Trigger调用链路。截图：[查看页](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-view-final.png)。

Final result: passed（本轮查看页、样本增删、手动版本创建和切换范围）。


### 版本创建结果与版本列表（2026-11-06）

对照数据集版本列表和创建新版本检查图，修正结果页通用键值列表造成的层级缺失、过多纵向留白、全宽操作按钮。完成态改为标题与来源、横排样本摘要、数据划分、右侧主操作。其他任务的失败/取消/运行展示保持原逻辑。版本列表调整列宽并统一任务名称。

真实历史任务 task-7a6fdcc2293259deb2f2887f016cb107 展示6来源样本、6结果样本、移除0、train5/test0/val1；点击查看新版本成功进入v10。本轮未创建额外任务或修改数据。结果页和版本列表1024px无水平滚动，亮暗主题核对，控制台无warning/error。类型检查与2项针对性回归通过。服务保持运行。

[完成页截图](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-created-light.png) · [版本列表](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/versions-list-final.png)。

Final result: passed（本轮完成态布局、真实结果跳转与列表适配）。当时尚缺的磁盘可用状态已由下节实现与验证补齐。

### 版本可用状态、筛选与创建流程（2026-11-06）

依据数据集版本列表、创建新版本检查设计图，新增真实基础资源状态及筛选。复用公共 Select、StatusBadge、ResourceTable，状态采用圆点与短文本，异常原因保留普通提示；不增加正常状态长说明。预检查增加来源数据集/vN、检查图标和中性摘要区域；完成态沿用已确认的报告层级。

- API：状态检查使用当前 content_revision；有状态条件时先筛选再分页，只有一页执行样本/标注聚合。字段与检查范围见 `docs/design/frontend/dataset-pages-design.md`。不扫描每张图片，不将基础资源可读等同于全量完整性校验。
- 隔离后端测试5项覆盖资源缺失/恢复、空清单、无样本、权限/磁盘错误、更新锁冲突、真实导入、组合筛选、过滤后分页和非法状态；已有工作区 API/任务5项通过。前端数据集25项通过；TypeScript、ruff、diff空白检查通过。
- 真实开发环境：验收副本 v10 经预检查创建 v11（dataset-version-f26305f71daf），6样本、10对象、4类别，train5/test0/val1。查看新版本与切回v10正常，来源统计不变。
- 仅对本轮v11的 categories.json 临时改名，缺失筛选准确返回这一条。恢复后缺失筛选为空，全列表14条均可用；文件 SHA256 恢复前后相同。未修改生产数据集或 Runtime/Trigger 链路。
- 1024px 亮暗、导航展开/收起无水平溢出；44px行高，状态和操作保留完整显示，长内容省略并提供提示。修正展开导航时的创建时间列过窄。浏览器控制台无 warning/error。
- 前端开发页出现旧模板缓存，核对服务实际输出并刷新Vite后，用新验收标签页确认最新模板。开发前后端保持运行，视口恢复默认、主题恢复亮色。

[版本列表亮色](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-availability-1024-light.png) · [版本列表暗色展开导航](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-availability-1024-expanded-dark.png) · [预检查暗色](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-check-1024-dark.png)。

Final result: passed（本轮版本基础资源状态、筛选、创建流程和设计细节范围）。


### 版本表头、导入导出记录与详情对照修订（2026-11-06）

对照 `generated/数据集/数据集版本列表-亮色.png`、`导入记录列表-亮色.png`、`导出记录列表-亮色.png`、`导入详情-已完成-亮色.png`、`导出详情-已完成-亮色.png`，并按本轮标注修正：版本首列“数据集”、只显示样本、来源“创建”。导入只显示样本和可跳转目标版本；导出移除样本列，补文件状态、直接下载及筛选。搜索支持文件名，导入支持近7/30天。

详情恢复来源/检查、映射/划分、结果操作的层级；导出文件结构置于映射前。修复报告缺失误报正常、结构化错误未显示、名称查询失败阻断文件浏览、切换记录复用旧文件分页、目录按钮沿用原生样式等问题。类别ID来自真实映射；未知ID不伪造。保留既有样本修改与手动版本语义，不使用历史报告覆盖当前版本统计。

验证：

- 后端48项通过：导入API、导出API、文件清理、记录筛选、工作区API。覆盖项目权限、过滤后分页、文件状态和搜索组合、非法参数等。
- 数据集前端13个文件、27项通过；TypeScript、作用范围内ruff、diff空白检查通过。开发中发现的 filePreviewOpen 初始化顺序错误已修复并覆盖详情初始化/切换回归。
- 真实开发环境：按 detection-coco-min.zip 搜索返回1条；近7天返回6条，旧记录被过滤。导出可下载返回6条、已清理返回0条，与当前数据一致。
- 从列表下载真实验收副本v9的COCO ZIP（3,474,648字节、9个文件），CRC校验通过；6张图片、10个标注、4类，train5/val1。浏览导出annotations目录、打开instances_train.json抽屉正常，叶文件不显示展开箭头，下载提示“已开始下载”。
- 导入详情历史报告为更新后8张/新增2张，正确保留当时结果；当前v10后续已删除这2张、保持6张。未以当前统计改写历史记录。
- 1024×768亮暗、导航展开/收起核对；导出列表收起918px/展开762px，scrollWidth与clientWidth相等，行高44px。版本列表展开746px无溢出；详情表格及展开报告/JSON抽屉无水平滚动。修复导出操作列被公共100px规则覆盖导致的溢出。
- 最终浏览器操作在修复后的15:55至结束无新增warning/error。保留早先开发异常日志，不将其误报为当前错误。主题恢复亮色，临时视口覆盖已重置，开发服务保持运行。

截图：[导入记录](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/imports-light.png) · [版本列表](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/versions-light.png) · [导出暗色1024](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/exports-dark-1024.png) · [导出详情](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/export-detail-light.png)。

Final result: passed（本轮版本列表标注、导入导出列表/详情、筛选、文件浏览下载与1024px适配范围；未用本轮短测宣称所有未来数据任务或长期运行已验收）。

### 导入导出状态和列宽再次修订（2026-11-06）

- 对照已确认导入/导出列表设计，修正前轮遗留的胶囊状态标签，改为圆形图标及普通正文；成功、失败、处理中通过图形和文字共同区分。仅这两个列表启用新外观，公共任务状态组件默认外观不变。
- 短字段固定、长字段分配余宽，减少宽列空白并避免挤压状态、时间和操作。长名称、格式、文件信息单行省略；导出文件提示同时显示文件状态、大小和完整文件名。
- 真实8条导入、6条导出记录核对；1024×768亮暗主题及导航展开/收起检查，表格762px或918px，scrollWidth等于clientWidth，页面宽1024px，无水平溢出，行高44px。当前真实记录均为完成态，未伪造失败记录进行实测。
- 前端数据集27项回归通过，TypeScript及diff空白检查通过。首次沙箱测试因缓存重命名EPERM未进入用例，正常开发环境重跑通过。
- 中途开发进程退出后按开发文档恢复 backend、inference daemon、六类Worker与Vite。HTTP liveness为ready，daemon probe通过，Worker topology ready；服务保持运行。最后恢复亮色、折叠导航，浏览器默认视口1280×720。

最新截图：[导入记录](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/record-columns/import-light-final.png) · [导出记录](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/record-columns/export-light-final.png) · [1024暗色](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/record-columns/export-dark-1024.png)。前轮记录列表截图不作为本轮状态样式基准。


### 查看页、详情、样本大图与结构（2026-11-06）

参考：`docs/design/frontend/generated/数据集/` 中标注样本网格、数据集详情抽屉、样本大图、样本对象信息抽屉、数据结构及样本结构亮暗设计。将源图与实现截图同轮并列检查。保留已确认布局与信息层级，控件尺寸使用项目公共组件，数据来自真实开发环境；不复刻生成图中的示例图片或恢复后来明确删除的外部标注功能。

本轮修正：统计条和工具栏层级、四列卡片及默认8张分页、详情抽屉真实摘要、专用大图工作区与右侧对象信息、文件/样本树。实测修复标注开关重置缩放：watch 改为分别比较 open 和样本标识；补同名文件不同 Sample ID 切换验证。对象表首列截断、标注文字过小同步修正。

验证：

- 数据集前端及公共视口合计16个文件、32项测试通过，覆盖详情统计/失败占位、目录请求、版本过期响应、样本树缓存/分页、标注切换保留缩放和同名样本重新适配。TypeScript检查通过。
- 真实609张条码样本显示982个对象、2个类别、train520/test89/val0；8→16每页数量切换正确；大图前后切换、缩放、标注开关、对象抽屉与对象选择核对正常。
- 验收副本v11为6样本/10对象，切换v8为5样本/8对象，切回v11恢复对应统计及目录；未修改生产样本，也未新建版本。
- 1024×768亮暗、导航收起/展开检查；网格、文件结构、样本结构、大图及详情抽屉 document.scrollWidth 等于1024，无水平滚动。长名称省略；侧栏展开时筛选行允许换行，保持控件可操作。
- 浏览器控制台未见 warning/error。开发服务保持运行，验证结束恢复亮色、折叠导航与默认视口。

截图目录：`C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-view-alignment/`，包含 samples-light.png、image-light.png、details-dark-1024.png、structure-light.png、structure-light-1024.png。

Final result: passed（本轮查看页及相关交互范围；真实数据核对与前端回归，不等同于所有未来标注格式或长期生产运行验收）。

### 查看页逐图复核后的再次修正（2026-11-06）

前轮“已对齐”不足以说明视觉细节完成。本次重新读取详情抽屉、标注网格、批量列表、大图、对象信息、文件结构、样本结构及不同任务样本的原图和提示词，按参考分组逐项修正。完整差异、最新截图、接口说明和验证边界记录在[逐图核对表](docs/design/frontend/verification/dataset-view-fidelity-20261106/README.md)。

- 修正抽屉信息分组与日期／ID排列、卡片比例、批量栏左右布局、页码、列表缩略图和文件名字体。
- 样本结构显示实际对象裁切图；文件结构包含文件叶子并正确识别空目录，重复请求合并、缓存与版本隔离保留。
- 大图对象面板改为真正的非模态检查面板，背景图像仍可缩放操作；选中对象平移到可见区，关闭恢复位置，Esc 优先关闭面板。共享资源抽屉默认模态行为不变。
- 45 项前端测试、4 项后端测试、TypeScript、ruff 和 diff 空白检查通过。1024px 亮暗主题实测无水平溢出。首次受限环境 API 测试停在 Python 回环 socket 初始化，正常本机环境重跑 4 项通过。
- 浏览器中途 HMR 的旧 `undimmed` 属性警告来自替换属性期间，最终源码已统一为 `nonmodal`。最终刷新后另行核对，不将历史热更新日志当作当前接口错误。

本轮结论仅覆盖上述查看页面和交互。不同标注类型有组件分支验证，真实浏览器用的是已有条码检测数据；不据此宣称全部未来类型和全部 112 张状态图均已完成验收。

## 2026-11-06 样本页面细节复核

final result: passed（仅本轮范围）

按标注样本网格、样本列表批量选择、样本对象信息抽屉三组原图和最新用户要求，修正搜索、排序图标、任务矩形标签、选择栏、分页摘要、大图分组和坐标信息层级。补齐样本列表标注状态，修正旧公共样式造成的文件名字号与颜色偏差。保持当前版本样本管理语义，不恢复已明确移除的外部标注功能。

真实开发环境使用 609 张条码／二维码样本，检查亮暗外观、1024×768、排序、分页、全选／清除、网格列表切换、大图翻页和对象面板。页面无水平溢出，浏览器未记录 error/warn。49 项相关前端测试及 Vue TypeScript 检查通过。

截图及逐项记录：[样本页面核对](docs/design/frontend/verification/dataset-sample-polish-20261106/README.md)。无本轮范围内未处理的 P0/P1/P2；不将本轮结论扩展到全部设计状态。

### 2026-11-06 标签与内容分隔线追加核对

final result: passed（本次两处样式修改）

查看页标签仅移除白色底，保留绿色文字／下划线；样本对象抽屉仅移除内容区分隔线。真实页面样式计算值与截图已核对，记录见 dataset-sample-polish-20261106/README.md 的追加核对。纯 CSS 修改未改变选择、导航或数据逻辑。

## 数据集导入向导、导入详情、导出向导和导出详情（2026-11-10）

17 组亮暗状态已对照，短屏检查为 1024×768。检查数据来自本地开发服务，上传中断通过浏览器故障注入复现。逐图结果、截图和边界见[核对记录](docs/design/frontend/verification/dataset-transfer-20261110/README.md)。

final result: passed（上述状态与数据范围）

## 数据集导入向导细节复核（2026-11-10）

以原图核对上传区、已上传文件行、数据定义、类别映射、划分统计及提交检查。数据定义同时验证新建和已有数据集，切回新建保留输入。真实 COCO 文件生成 v1，提交前与记录中的样本、对象、类别数量为 2、2、1。删除文件、重新选择同一文件、缺失图像阻止提交均在内置浏览器验证。用独立本地测试端口中断首次上传连接，点击重新上传后得到开发服务回执。亮暗短屏 1024×768 无水平溢出。服务端正式校验与本地清单预查分别显示。

[亮色对照](docs/design/frontend/verification/dataset-import-refinement/compare-light.jpg) · [暗色对照](docs/design/frontend/verification/dataset-import-refinement/compare-dark.jpg)。按设计稿与真实状态比较，使用当前工作站导航及真实样本；上传中断交互实测为亮色。

final result: passed（导入向导上述状态）

## 数据集导入、导出设计对照（2026-11-10）

使用本地工作站和 dataset worker，按原图核对两个四步向导、完成／失败详情、记录列表和确认框。桌面参照为 1672 × 941，短屏实测为 1024 × 768，亮暗主题分别截图；短屏目录树默认收起，仍可展开。核对时修正了导出兼容检查的左右栏比例、表头与类别行错位、文件名前图标换行、不兼容时的格式对照以及确认框中的清理／保留范围。

真实 COCO ZIP 的两张图片、两条标注和映射后的类别通过导出 ZIP 的完整性与 JSON 校验。另测上传连接中断后重传、缺图阻止提交、错误边界框导入失败、格式不兼容阻止导出及清理后的下载禁用。没有为凑齐设计稿的示例值补造时间、预计包大小或目标标注；类别映射按现场要求默认收起。数据集前端回归 18 个文件、44 项通过；生产构建通过。

[亮暗设计图与实测截图逐项对照](docs/design/frontend/verification/dataset-transfer-records/导入导出设计实测对照.html)

## 导入与导出字体、日期和图标复核（2026-11-10）

工作站使用本地分发的 Noto Sans SC 可变字体，普通表格正文 14 px、辅助信息 13 px。实心状态图标仅内部符号使用白色描边。文件树的省略号按目录展开，键盘可以操作。亮暗两套 22 组[原图和实测对照](docs/design/frontend/verification/dataset-transfer-records/导入导出设计实测对照.html)已更新。[现有 1,224 张样本的导入详情，1024 × 768 暗色](docs/design/frontend/verification/dataset-transfer-records/实测-导入详情-1024-dark.png)显示同一次执行的四个时间、对应状态以及无白色外圈的结果图标。
