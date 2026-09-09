# Workflow Runtime 显示与 App Mode

## 状态与目标

Runtime 显示与 App Mode 已实现。“Runtime 完成后显示到只读画布”和轻量 App Mode 已共用同一观察通道；实际图片/JSON、同步/异步、ZeroMQ/本机共享内存、Directory Trigger、.NET SDK、Runtime 停止/重启恢复和浏览器调用均已覆盖。一小时、16 个大图客户端的资源稳定性门禁已完成，但调用 p95/p99 尾延迟未通过；单客户端对照已把问题定位到多客户端大图广播竞争。当前接受这一已知性能边界，不为多客户端大图广播增加队列、缓存、协议分支或独立服务，也不据此宣称工业长期认证。逐节点进度和强制终止终态不纳入实现范围。当前页面和协议见 [Runtime 预览监视](../../api/workflow-runtime-preview.md)。

项目核心仍是 Workflow 节点编排、长期 Runtime 和 Trigger。显示能力用于查看生产执行产生的图片、JSON、文本等信息，直接复用图中的预览节点和已有显示组件，不复制执行逻辑。

“应用模式”是现有 Workflow App 的一种前端视图，不新增另一种应用资源、执行器或部署单元。不恢复已撤销的 amvar app 组成、独立页面设计器、独立界面发布版本、主题系统或应用打包规划；也不顺带修改既有导航命名。复杂界面后续通过受控节点包展示扩展或独立前端实现，不扩张成通用低代码平台。

长期稳定和结果正确优先，其次是性能；实现保持简单、确定、通用。本文是当前显示架构的详细入口，其他专题仅链接到此，不复制多份规格。

## 组件职责

| 部分 | 当前事实 | 边界 |
| --- | --- | --- |
| 预览节点 | Image、Value、Table、Gallery 等节点已有结构化显示输出，已接入完成后显示 | 保持每次执行完成后一次性交接，不实现逐节点进度 |
| 编辑画布 | 从同步 Preview 返回的 `node_records` 识别 `*-preview` 内容；显示适配已与 Preview Run 解耦 | 与只读画布、App Mode 共用显示组件 |
| 高性能 Runtime | none 等模式不保留完整节点输入输出载荷，显示走独立单次交接 | 保持现有业务链路和有界观察通道，不扩大数据面 |
| 节点过程信息 | 已有事件会清理载荷；Worker 部分节点消息用于超时控制 | 不复用为逐节点显示，不增加过程消息协议 |
| 自定义节点 | 可生成已有标准 payload，Catalog/Node Pack 已有注册体系 | 全新前端渲染组件的受控扩展尚需单独实现 |

不能只增加一个应用模式按钮就宣称 Runtime 已能显示，也不能直接复用现有事件里的脱敏正文作为完整图片。已有 Node Pack 超时控制通道不是图片发送通道，不向其中无条件塞入大图。

## 同一 Workflow，三个使用视图

| 视图 | 操作范围 | 执行与数据来源 |
| --- | --- | --- |
| 节点编辑 | 编辑节点、参数、连线；使用原有调试功能 | 编辑态快照与 Preview Run |
| Runtime 画布监视 | 只读查看实际部署图，在预览节点位置显示内容 | 明确选中的 Runtime 实际执行 |
| 应用模式 | 隐藏连线和无关节点参数，显示 App Entry 的全部公开输入及选中的预览区域 | 与画布监视相同的 Runtime 显示数据 |

两个运行视图共用显示适配器和当前显示状态，不各自创建执行会话。Runtime 监视不是把 Runtime 改成 Preview Run，也不为了显示重新执行一遍图。

- 页面明确当前观察的 Runtime，不凭 App 名称选择首个实例，不混合不同实例的结果。
- 生产运行视图加载实际激活版本的 Application/Template 和节点身份，不使用最新编辑草稿替代。停止态可查看选定版本配置，但不能冒充正在运行或自动启动。
- 监视画布允许查看、缩放和移动视口，不允许直接修改生产节点。编辑仍返回原画布，经过保存、发布、选版后生效。
- Runtime 切版/重启后重新核对实际版本和 generation，旧连接或旧实例回调不能覆盖新状态。
- 打开、关闭、刷新、切换视图不执行 Workflow，不启停 Runtime/Trigger；断线重连只恢复观察，不补发业务调用。

## 两类输出保持独立

```text
图片 → 模型推理 → 绘制结果 → Image Preview ──→ 页面显示
             └→ 结果整理 → Value Preview ──→ 页面显示
                         └→ App 公开输出 ──→ HTTP / SDK / Trigger 返回
```

App 公开业务输出继续使用原有 binding 和协议。节点预览显示输出供画布监视和应用模式使用，不要求为了显示额外连接 App 输出，也不强制进入 Trigger 返回。

需要显示的数据通过节点连线送入预览节点。只交接明确预览节点的显示端口，不采集全部节点输入输出，不通过扫描任意业务字段猜测图片，不按节点名称、画布位置或列表顺序匹配。

应用模式选择显示哪些预览区域，不修改 DAG、节点执行顺序或启用状态；隐藏节点卡片不等于跳过该节点执行。推理、绘制、JSON 组织、统计、规则判定和批次聚合全部留在 Workflow。

基础显示先复用图片、结构化值/JSON、表格、图库组件；文本使用明确的值/文本适配，不作为 HTML 或脚本执行。相同组件在编辑、监视和应用模式下保持相同数据含义，不复制三套类型判断。

## Runtime 到页面的观察链路

```text
HTTP / SDK / ZeroMQ / 本机共享内存 / 目录 Trigger
                         ↓
                    现有 Runtime
                         ↓
                  预览节点产生显示 payload
                  ├─ 原 Workflow 继续执行
                  └─ 显示交接 → backend → WebSocket
                                         ├─ Runtime 只读画布
                                         └─ 应用模式
```

统一在 Runtime/执行器的预览显示边界接入，不在每种 Trigger 内实现广播；HTTP 直接调用和外部 Trigger 触发的实际运行都能被观察。仅新增观察能力，不改变业务请求、响应、admission、同步/异步或记录模式。

### 显示时机

只在 Worker 完成本次执行及资源清理后一次性交接显示结果；失败时能够显示失败前已经形成且可安全交付的预览结果。不把全部 `node_records` 打包返回，也不建立跨执行的服务端结果缓存。

不实现预览节点完成即显示的逐节点进度。该能力需要额外处理 Parallel、ForEach、迭代身份、后续失败、迟到回调和图片资源生命周期，与当前查看生产最终结果的目标不匹配。Runtime 被强制停止、Worker 被强制终止或进程异常退出时可能只有连接断开，不补造本次 Run 的成功、失败或取消终态；业务结果仍以原 HTTP、SDK、Trigger 响应及启用的 WorkflowRun 记录为准。

同步、持久化异步以及 none + event-only 临时异步都要覆盖，不能只在 HTTP 成功响应处接入。尚未受理的请求不能伪造执行结果。现有超时、取消及资源清理规则保持原样。

### 关联与页面状态

- 显示身份包括 Runtime、实际版本/revision、generation、worker、指纹、run ID、节点 ID、输出端口和显示类型；字段已固定为[预览观察 v1](../../api/workflow-runtime-preview.md)，本节仅保留设计约束。
- 图片、JSON、表格等按同次执行关联。新执行中未到达、跳过或失败前未执行的预览节点显示相应状态，不能把上次值拼入本次结果。
- 循环内同一节点多次执行须区分调用/迭代身份，不按消息到达顺序拼成数组。当前节点卡片展示有明确身份的一次结果；完整批次由 Workflow 聚合后交给 Gallery/Table Preview。
- 页面只保存当前画面和必要在途数据，不追加历史结果列表。迟到的图片加载和旧运行回调不得覆盖更新后的画面；断线保留的画面明确标记为旧数据。
- 页面区分等待下次执行、最近一次完成的成功/失败、图片失效、连接断开和 Runtime 停止。业务产品合格与 Workflow 执行成功不是同一状态。

### 性能和资源边界

- 无对应页面观察时，不新增显示传输、全量图扫描或数据库记录。图中已经放置的预览/编码节点仍照常执行，不能因页面关闭隐式跳过节点，也不能宣称其编码成本消失。
- 页面发送不是节点完成、同步返回或 Trigger ACK 的等待条件。慢客户端只影响显示，不阻塞或重试实际 Workflow 调用；不增加业务排队、显示历史、重放或补偿系统。
- 显示交接和后台发送必须有界，不把队列换成无界线程池任务、协程或回调。当前发送未完成时允许跳过新显示更新，不保留下一条待发结果；不保证每次执行都能显示。
- 图片复用预览节点已产生的 Base64 或有效存储引用。只能在输入资源有效时准备正文，不在 LocalBuffer/mmap 释放后读取原图，不为慢页面延长核心租约。
- Preview 专属 artifact 路径与清理周期不能直接冒充 Runtime 资源；引用必须实际可读，失效时显示不可用。页面不猜最新文件或用另一张图替代，显示层不创建永久图片副本仓库。
- 浏览器释放被替换的正文、Object URL、读取请求和监听器；关闭页面不删除生产 Save 文件。新链路的消息容量、在途内存和解码限制经实测明确，不顺带改变其他协议限制。
- 复用现有登录态和默认全权限用户 token，与 SDK 接入方式一致，不增加角色或应用权限体系；token 有效性和公开文件路径校验仍保留。

显示序列化和传输仍可能竞争 CPU、内存、磁盘及网络。逻辑隔离不是零成本证明；尤其不能以异步函数或单独线程代替测量。对极低开销生产图，可继续使用独立监视 Workflow 读取保存结果，再交给相同预览节点和视图，不强迫合并图。

## 轻量应用模式配置与使用

当前自动读取当前发布版本 App Entry 配置的全部公开输入，只配置预览节点/显示端口、显示顺序、标题和简单尺寸，提供画布/应用模式切换及全屏。配置界面不是通用页面设计器，不提供公开输入筛选、任意脚本、外部 API 编排或第二套节点参数编辑。

- 输入只来自当前发布版本已有的 App Entry 公开 binding，并按发布版 App Contract 的 `payload_type_id`、`transports`、媒体类型和容量限制渲染，不按 `binding_id` 名称猜测类型。页面不保存输入选择，不增加 App Mode 专用必填规则，只提交本次实际填写的数据。现有 `binding.required` 和 Runtime 输入校验仍是公开调用契约；需要保持可选的 App Entry binding 应在编辑画布中配置为 `required=false`，App Mode 不绕过后端校验。
- 内部节点参数只能在编辑模式修改；应用模式表单只构造本次公开请求，不改变草稿、发布快照或下一次 Trigger 的输入。
- 显示选择配置保存在 `application.metadata.app_mode`，随现有 Workflow 文档进入发布快照，不新增独立界面资源、数据库表或版本体系。配置使用 `amvision.workflow-app-mode.v1`；每个显示项以 `node_id + output_port` 确定性引用 Preview 输出，并可配置标题及 `small/medium/large` 简单尺寸。数组顺序只表示界面显示顺序，不参与运行时数据关联。
- 当前正式显示配置变更沿用 Workflow 发布/选版流程；浏览器临时视口缩放不修改发布文档。不能为只改外观绕过不可变版本管理，也不另造外观热更新服务。

### 配置契约

当前配置固定为以下结构：

```json
{
  "format_id": "amvision.workflow-app-mode.v1",
  "title": "3570 治具检测",
  "displays": [
    {
      "node_id": "image_preview_1",
      "output_port": "body",
      "title": "检测图片",
      "size": "large"
    },
    {
      "node_id": "value_preview_1",
      "output_port": "body",
      "title": "检测结果",
      "size": "medium"
    }
  ]
}
```

- `application.metadata.app_mode` 不存在表示尚未配置，不再增加含义重复的 `enabled` 状态。
- `app_mode` 不保存输入列表。Runtime 预览快照按只读方式返回 `contract` 和规范化后的 `app_mode`；App Mode 按 Application binding 顺序与 Contract binding identity 合并，生成全部公开输入。该加法不创建新执行接口，也不改变现有 WebSocket 消息。
- `displays` 至少包含一个显示项；`node_id + output_port` 在配置内唯一。引用节点必须存在、启用并声明 `ui.preview`，输出端口必须真实存在；`size` 仅支持 `small`、`medium`、`large`。
- 首次创建配置时，编辑器明确列出当时已有的全部 Preview 输出，由使用者选择需要展示的输出；保存后新增 Preview 节点不得自动进入既有配置。删除节点、禁用节点或改变端口时不静默删除配置，编辑器显示失效项并阻止保存或发布。
- 纯 App Mode 配置变化进入 Workflow App 内容指纹和不可变发布快照，但不改变 App Contract 指纹，不应被判断为公开输入输出的破坏性变化。应用复制、现有 Workflow 文档导入导出和版本快照自然携带 metadata；读取和导入后仍执行相同校验。
- 运行时遇到历史无效数据或发布节点定义缺失时忽略对应显示项并明确提示，不按名称、节点位置、数组下标或消息到达顺序回退关联。

### 全部公开输入与提交

不能直接把编辑态 Preview 输入面板原样用于 App Mode。Preview 支持的 execution-scoped memory handle、本地路径和把 Base64 图片改投其他 binding 等行为，不属于生产 Runtime 表单的默认语义。应提取共用的字段渲染基础，再分别保留 Preview 与 Runtime transport 策略。

| App Contract payload | App Mode 行为 |
| --- | --- |
| `image-ref.v1` | 默认使用契约允许的 multipart 图片上传；只有契约允许 JSON reference 时才显示 ObjectStore reference，不暴露 Preview 专用 memory/local-path |
| `image-base64.v1` | 读取所选图片并实际构建该 binding 的 Base64 payload，不改投 `image-ref` |
| `value.v1` 及结构化 JSON | 使用 JSON/value 编辑器，按现有 payload schema 构建请求 |
| `text.v1` | 提交文本、媒体类型和 charset |
| `file-ref.v1` | 单文件 multipart |
| `file-refs.v1` | 多文件 multipart，并遵守 `max_files` 和单文件容量 |
| 其他类型 | 只按发布版 JSON Schema 和 transport 生成基础输入，不增加场景专用组件 |

前端 Runtime service 根据实际已填写字段选择现有 JSON `POST /workflows/app-runtimes/{runtime_id}/invoke?response_mode=run` 或 multipart `POST /workflows/app-runtimes/{runtime_id}/invoke/upload?response_mode=run`。一次页面手动请求尚未完成时禁用提交按钮以防重复点击，但不建立请求队列，也不影响 ZeroMQ、本机共享内存或 Directory Trigger 的并行调用。

表单值默认保留，方便现场重复执行；离开页面时释放文件引用和临时 Base64。Runtime 未运行时禁用手动提交并显示实际状态。后端错误原样进入本次手动请求状态，不改写成 Preview 或产品判定。

### 固定显示槽与运行身份

App Mode 在收到结果前就按配置创建固定显示槽，避免布局随消息跳动：

- 尚未执行时显示等待状态；本次 Run 有对应输出时显示结果。
- 本次 Run 没有配置输出时清除该槽上一次内容并显示“本次无结果”，不能把不同 Run 的图片、JSON 或表格拼在一起。
- 图片引用失效时显示不可用；普通断线保留最近画面并标记非实时，Worker、generation 或发布版本换代时清除旧代画面。
- App Mode 复用现有 `useRuntimePreview`、显示适配器和 WebSocket；从 Runtime 监视切换到 App Mode 时关闭旧页面订阅，不能为同一页面创建第二条显示连接。
- 客户端按 `node_id + output_port` 过滤已经收到的完整显示帧。当前不为每个订阅增加后端字段过滤、第二套消息格式或单独缓存。

页面手动 HTTP 请求状态和 Runtime 观察画面是两个明确区域。手动响应显示其返回的 `workflow_run_id` 和状态；WebSocket 区域始终显示该 Runtime 最新实际执行结果，不能把“下一条消息”猜成页面刚提交的 Run。外部 Trigger 的结果按相同方式正常更新显示区，原 SDK/Trigger 返回保持不变。

实际使用顺序：

1. 在原画布编排 Workflow，并接好需要的预览节点，使用原 Preview 验证。
2. 配置应用模式标题和需要显示的 Preview 区域；全部 App Entry 公开输入自动进入表单，保存后按原流程发布。
3. 为 Runtime 选择并启动相应版本，Trigger 仍按原流程配置与启用。
4. 从现有 App/Runtime 入口进入运行视图，明确选择目标 Runtime，等待后续执行结果；打开页面不产生试跑。
5. 外部 Trigger 调用自动反映到当前观察页面；手动运行通过目标 Runtime 的既有 HTTP 接口提交公开输入，不改用编辑器 Preview。
6. 需要修改逻辑时返回编辑模式；运行视图继续使用激活版本，直到显式切版。

### 启动页面偏好

设置页提供独立的“启动页面”分类，可选择默认项目页面或一个明确的 Runtime App Mode。选择项使用 `project_id + application_id + workflow_runtime_id` 三个稳定标识，不按名称或列表顺序关联。

- 配置保存在当前浏览器按用户区分的版本化 `localStorage` 值中，键名为 `amvision.web-ui.startup-page.<encodeURIComponent(principal_id)>`，没有 TTL。退出登录清空内存中的当前用户偏好，不删除该用户的本地配置；此隔离用于偏好选择，实际资源访问仍由后端鉴权控制。当前没有数据库字段或后端偏好保存接口。
- 存储按浏览器 profile 和 origin 区分；不同端口、域名或浏览器不共享配置。启动器使用固定的 `<ProgramRoot>/data/launcher/webview/` 数据目录和 `amvar` WebView2 profile，正常重启保留配置，升级需保留该目录。清除站点数据、恢复默认或更换未迁移数据的安装目录可能使配置消失；仅删除浏览历史与删除站点存储不同。
- 保存前读取目标 Runtime 的权威预览快照，核对三层身份并确认当前发布版本存在 `app_mode`；Runtime 可以处于停止或失败状态，设置过程不自动启动。
- 已登录后从根地址进入前端时应用该偏好。显式 URL、登录回跳和路由守卫携带的 `redirect` 始终优先，不能被启动偏好劫持。
- 目标返回 403/404 或身份不一致时恢复项目页面并清除失效偏好；短暂网络或服务错误保留偏好，由 App Mode 自身的重试和错误状态处理。
- 恢复默认值会删除本地配置。该能力只决定浏览器首次落点，不执行 Workflow，不建立观察连接，也不进入 Runtime/Trigger 热路径。
- 页面名称、字段、状态和反馈均使用现有中文、英文、日文、韩文 i18n 体系。

当前阶段保留按账号区分的浏览器本地存储方案，不引入后端账号默认或跨终端同步配置。

## 自定义节点扩展边界

自定义节点输出已有标准图片、值、表格或图库 payload 时，复用通用渲染器，不按业务场景新增平台专用页面。

全新展示或交互可后续通过节点包的受控前端注册、静态资产和渲染组件扩展。当前 manifest 的能力声明不等于已经实现任意 Vue 组件加载；需单独补齐安装、版本、启停及前端注册约定，但不作为当前前提。不执行结果 payload 携带的任意 JavaScript，也不直接依赖 `projectsrc/`。

完整客户界面可以由独立前端项目实现，复用标准接口。仓库内仍使用 Vue 3 和本地静态分发，不维护并行的其他前端框架，不新增模型生成页面或复杂主题设计功能。


## 性能与验收边界

已有真实图片/JSON、同步/异步、HTTP、ZeroMQ、本机共享内存、目录 Trigger、.NET SDK、浏览器和 Runtime 恢复验证。一小时 16 个大图客户端测试通过调用正确性与资源稳定性检查，但调用 P95/P99 尾延迟未通过；后续有界复测仍观察到多客户端大图广播竞争。单客户端或短时结果不能替代该持续负载结论。

当前保留这一性能边界，不通过增加队列、历史缓存、协议分支或独立显示服务扩大实现。观察发送有界且允许跳过更新；不保证每次 Run 都显示，也不提供逐节点进度、强制终止终态或工业长期认证。

实现入口：`backend/service/application/workflows/runtime_preview.py`、Workflow Worker manager/process、Runtime Preview API 和前端 Workflow 编辑器。持续验证应分别记录无观察、单观察连接与多客户端大图观察的调用延迟、内存、句柄、线程和释放后的基线。
