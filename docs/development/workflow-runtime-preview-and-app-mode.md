# Workflow Runtime 预览显示与应用模式实施基线

## 1. 状态与目标

状态：设计已接受；“Runtime 完成后显示到只读画布”已实现，已覆盖实际图片/JSON、同步/异步、ZeroMQ/本机共享内存、Directory Trigger、.NET SDK 和浏览器验证。一小时、16 个大图客户端的资源稳定性门禁已完成，但调用 p95/p99 尾延迟未通过；单客户端对照已把问题定位到多客户端大图广播竞争。当前接受这一已知性能边界，不为多客户端大图广播增加队列、缓存、协议分支或独立服务，也不据此宣称工业长期认证。逐节点进度和强制终止终态不再纳入实现范围，下一步只实现轻量 App Mode。当前页面和协议见 [Runtime 预览监视](../api/workflow-runtime-preview.md)。

项目核心仍是 Workflow 节点编排、长期 Runtime 和 Trigger。新增能力主要用于查看生产执行产生的图片、JSON、文本等信息，直接复用图中的预览节点和已有显示组件，不复制执行逻辑。

“应用模式”是现有 Workflow App 的一种前端视图，不新增另一种应用资源、执行器或部署单元。不恢复已撤销的 amvar app 组成、独立页面设计器、独立界面发布版本、主题系统或应用打包规划；也不顺带修改既有导航命名。复杂界面后续通过受控节点包展示扩展或独立前端实现，不将本次能力扩张成通用低代码平台。

长期稳定和结果正确优先，其次是性能；实现保持简单、确定、通用。本文是本次方案的详细实施入口，其他专题仅链接到此，不复制多份规格。

## 2. 已有基础与接入缺口

| 部分 | 当前事实 | 待补齐能力 |
| --- | --- | --- |
| 预览节点 | Image、Value、Table、Gallery 等节点已有结构化显示输出，已接入完成后显示 | 保持每次执行完成后一次性交接，不实现逐节点进度 |
| 编辑画布 | 从同步 Preview 返回的 `node_records` 识别 `*-preview` 内容；显示适配已与 Preview Run 解耦 | 共用显示组件，后续再扩展轻量 App Mode |
| 高性能 Runtime | none 等模式不保留完整节点输入输出载荷，显示走独立单次交接 | 保持现有业务链路和有界观察通道，不扩大数据面 |
| 节点过程信息 | 已有事件会清理载荷；Worker 部分节点消息用于超时控制 | 不复用为逐节点显示，不增加过程消息协议 |
| 自定义节点 | 可生成已有标准 payload，Catalog/Node Pack 已有注册体系 | 全新前端渲染组件的受控扩展尚需单独实现 |

不能只增加一个应用模式按钮就宣称 Runtime 已能显示，也不能直接复用现有事件里的脱敏正文作为完整图片。已有 Node Pack 超时控制通道不是图片发送通道，不向其中无条件塞入大图。

## 3. 同一 Workflow，三个使用视图

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

## 4. 两类输出保持独立

```text
图片 → 模型推理 → 绘制结果 → Image Preview ──→ 页面显示
             └→ 结果整理 → Value Preview ──→ 页面显示
                         └→ App 公开输出 ──→ HTTP / SDK / Trigger 返回
```

App 公开业务输出继续使用原有 binding 和协议。节点预览显示输出供画布监视和应用模式使用，不要求为了显示额外连接 App 输出，也不强制进入 Trigger 返回。

需要显示的数据通过节点连线送入预览节点。只交接明确预览节点的显示端口，不采集全部节点输入输出，不通过扫描任意业务字段猜测图片，不按节点名称、画布位置或列表顺序匹配。

应用模式选择显示哪些预览区域，不修改 DAG、节点执行顺序或启用状态；隐藏节点卡片不等于跳过该节点执行。推理、绘制、JSON 组织、统计、规则判定和批次聚合全部留在 Workflow。

基础显示先复用图片、结构化值/JSON、表格、图库组件；文本使用明确的值/文本适配，不作为 HTML 或脚本执行。相同组件在编辑、监视和应用模式下保持相同数据含义，不复制三套类型判断。

## 5. Runtime 到页面的观察链路

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

- 显示身份包括 Runtime、实际版本/revision、generation、worker、指纹、run ID、节点 ID、输出端口和显示类型；第一阶段字段已固定为[预览观察 v1](../api/workflow-runtime-preview.md)，本节仅保留设计约束。
- 图片、JSON、表格等按同次执行关联。新执行中未到达、跳过或失败前未执行的预览节点显示相应状态，不能把上次值拼入本次结果。
- 循环内同一节点多次执行须区分调用/迭代身份，不按消息到达顺序拼成数组。首版节点卡片展示有明确身份的一次结果；完整批次由 Workflow 聚合后交给 Gallery/Table Preview。
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

## 6. 轻量应用模式配置与使用

首版自动读取当前发布版本 App Entry 配置的全部公开输入，只配置预览节点/显示端口、显示顺序、标题和简单尺寸，提供画布/应用模式切换及全屏。配置界面不是通用页面设计器，不提供公开输入筛选、任意脚本、外部 API 编排或第二套节点参数编辑。

- 输入只来自当前发布版本已有的 App Entry 公开 binding，并按发布版 App Contract 的 `payload_type_id`、`transports`、媒体类型和容量限制渲染，不按 `binding_id` 名称猜测类型。页面不保存输入选择，不增加 App Mode 专用必填规则，只提交本次实际填写的数据。现有 `binding.required` 和 Runtime 输入校验仍是公开调用契约；需要保持可选的 App Entry binding 应在编辑画布中配置为 `required=false`，App Mode 不绕过后端校验。
- 内部节点参数只能在编辑模式修改；应用模式表单只构造本次公开请求，不改变草稿、发布快照或下一次 Trigger 的输入。
- 显示选择配置保存在 `application.metadata.app_mode`，随现有 Workflow 文档进入发布快照，不新增独立界面资源、数据库表或版本体系。配置使用 `amvision.workflow-app-mode.v1`；每个显示项以 `node_id + output_port` 确定性引用 Preview 输出，并可配置标题及 `small/medium/large` 简单尺寸。数组顺序只表示界面显示顺序，不参与运行时数据关联。
- 首版正式显示配置变更沿用 Workflow 发布/选版流程；浏览器临时视口缩放不修改发布文档。不能为只改外观绕过不可变版本管理，也不另造外观热更新服务。

### 配置契约

首版配置固定为以下结构：

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
- `app_mode` 不保存输入列表。Runtime 预览快照后续按只读方式新增 `contract` 和规范化后的 `app_mode`；App Mode 按 Application binding 顺序与 Contract binding identity 合并，生成全部公开输入。该加法不创建新执行接口，也不改变现有 WebSocket 消息。
- `displays` 至少包含一个显示项；`node_id + output_port` 在配置内唯一。引用节点必须存在、启用并声明 `ui.preview`，输出端口必须真实存在；`size` 仅支持 `small`、`medium`、`large`。
- 首次创建配置时，编辑器可以明确展示并选中当时已有的全部 Preview 输出；保存后新增 Preview 节点不得自动进入既有配置。删除节点、禁用节点或改变端口时不静默删除配置，编辑器显示失效项并阻止保存或发布。
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

前端 Runtime service 补齐同一 `POST /workflows/app-runtimes/{runtime_id}/invoke?response_mode=run` 的 multipart 封装，根据实际已填写字段选择 JSON 或 multipart；后端继续使用现有入口。一次页面手动请求尚未完成时禁用提交按钮以防重复点击，但不建立请求队列，也不影响 ZeroMQ、本机共享内存或 Directory Trigger 的并行调用。

表单值默认保留，方便现场重复执行；离开页面时释放文件引用和临时 Base64。Runtime 未运行时禁用手动提交并显示实际状态。后端错误原样进入本次手动请求状态，不改写成 Preview 或产品判定。

### 固定显示槽与运行身份

App Mode 在收到结果前就按配置创建固定显示槽，避免布局随消息跳动：

- 尚未执行时显示等待状态；本次 Run 有对应输出时显示结果。
- 本次 Run 没有配置输出时清除该槽上一次内容并显示“本次无结果”，不能把不同 Run 的图片、JSON 或表格拼在一起。
- 图片引用失效时显示不可用；普通断线保留最近画面并标记非实时，Worker、generation 或发布版本换代时清除旧代画面。
- App Mode 复用现有 `useRuntimePreview`、显示适配器和 WebSocket；从 Runtime 监视切换到 App Mode 时关闭旧页面订阅，不能为同一页面创建第二条显示连接。
- 客户端按 `node_id + output_port` 过滤已经收到的完整显示帧。首版不为每个订阅增加后端字段过滤、第二套消息格式或单独缓存。

页面手动 HTTP 请求状态和 Runtime 观察画面是两个明确区域。手动响应显示其返回的 `workflow_run_id` 和状态；WebSocket 区域始终显示该 Runtime 最新实际执行结果，不能把“下一条消息”猜成页面刚提交的 Run。外部 Trigger 的结果按相同方式正常更新显示区，原 SDK/Trigger 返回保持不变。

实际使用顺序：

1. 在原画布编排 Workflow，并接好需要的预览节点，使用原 Preview 验证。
2. 配置应用模式标题和需要显示的 Preview 区域；全部 App Entry 公开输入自动进入表单，保存后按原流程发布。
3. 为 Runtime 选择并启动相应版本，Trigger 仍按原流程配置与启用。
4. 从现有 App/Runtime 入口进入运行视图，明确选择目标 Runtime，等待后续执行结果；打开页面不产生试跑。
5. 外部 Trigger 调用自动反映到当前观察页面；手动运行通过目标 Runtime 的既有 HTTP 接口提交公开输入，不改用编辑器 Preview。
6. 需要修改逻辑时返回编辑模式；运行视图继续使用激活版本，直到显式切版。

## 7. 自定义节点扩展边界

自定义节点输出已有标准图片、值、表格或图库 payload 时，复用通用渲染器，不按业务场景新增平台专用页面。

全新展示或交互可后续通过节点包的受控前端注册、静态资产和渲染组件扩展。当前 manifest 的能力声明不等于已经实现任意 Vue 组件加载；需单独补齐安装、版本、启停及前端注册约定，但不作为首版前提。不执行结果 payload 携带的任意 JavaScript，也不直接依赖 `projectsrc/`。

完整客户界面可以由独立前端项目实现，复用标准接口。仓库内仍使用 Vue 3 和本地静态分发，不为本次任务维护另一个前端框架，不新增模型生成页面或复杂主题设计功能。

## 8. 实施顺序与验证

每阶段完成后先核对行为和边界，再做链路审计及验证，通过后继续下一步。不因界面可见就认定性能和长期稳定已通过。阶段 0、1 已完成；App Mode 按以下顺序继续。

| 阶段 | 实现内容 | 阶段门禁 |
| --- | --- | --- |
| 2.1：冻结配置契约 | 增加独立的 App Mode v1 配置模型和解析函数；统一 `output_port` 并删除 `enabled` | 合法、重复、未知节点、禁用节点、非 Preview、未知端口和非法尺寸测试；无数据库迁移 |
| 2.2：接入保存和发布校验 | Workflow Application 保存、bundle 保存、导入读取和发布前均校验 `application.metadata.app_mode` | 失效引用不能落盘或发布；配置进入内容指纹但不改变 App Contract 指纹；复制和版本快照保持一致 |
| 2.3：扩展只读 Runtime 快照 | 从同一发布版本读取 `contract`，返回规范化 `app_mode`；不存在时返回 `null` | 停止态、运行态、切版和历史无配置版本正确；不启动 Runtime、不读取草稿、不解析动态节点参数 |
| 2.4：编辑器配置面板 | 加载 App Mode draft，列出 `ui.preview` 节点输出，配置标题、顺序和简单尺寸，并写回 Application metadata | 全部 App Entry 输入只显示数量和自动使用说明、不出现输入勾选；dirty/save/preflight/发布一致；四语言通过 |
| 2.5：通用输入表单与 Runtime invoke | 从 Preview 输入实现提取共用字段渲染，增加 Runtime transport builder 和 JSON/multipart 调用 | 六类输入单独及混合调用；空字段不提交；Base64 不改投 binding；文件限制和后端错误保持原契约 |
| 2.6：App Mode 运行页 | 新增 `/workflows/runtime/{runtime_id}/app-mode`，显示全部公开输入、手动请求状态和固定 Preview 槽 | 明确 Runtime 身份；不显示节点图、不编辑内部参数；手动 Run 与外部 Trigger 结果不混淆；只有一个 WebSocket |
| 2.7：入口与回归 | App 详情中对选定 Runtime 增加 App Mode 入口，复用查看器和重连状态机 | 未配置时不猜测页面；Runtime 停止、重启、切版、容量已满、离页释放和四语言浏览器测试通过 |
| 3：实际数据与稳定性验收 | 开发环境模型、Workflow、Runtime、Trigger 和 SDK 对照；桌面与一小时运行验证 | 结果正确性、双实例合理负载、慢页面/断线/多页面、核心与 Preview 性能、浏览器/Backend/Worker 内存及句柄稳定 |

测试至少包括：

- 无页面、单页面、多个页面和慢连接；不新增显示结果持久化或无界积压。
- 图片/JSON/文本/表格/图库、空值、缺失输出、大图、引用失效、失败前部分显示；不串用不同 run 内容。
- Runtime 停止、重启、切版及强制终止只断开不补造终态；编辑草稿与激活版不同；界面选显示项不改变图执行。
- 手动调用与 ZeroMQ、本机共享内存、目录 Trigger；App Entry 全部输入自动显示，前端不增加必填规则，原 Runtime 校验及原响应不变。
- 配置输出缺失时固定槽清除旧内容；手动调用和 Trigger 交错时按真实 run identity 显示，不根据到达顺序关联。
- p50/p95/p99、下一次核心调用延迟、CPU、Private/Working Set、原生句柄、LocalBuffer lease、发送任务数和浏览器内存；区分节点编码与新增传输成本。
- 原编辑器 Preview、节点取参及默认值行为回归；四语言和桌面工作站显示，未测移动端时明确标注。

第一阶段通过后不自动扩大实现范围。当前已有实际顺序调用、连接反复打开/关闭、慢页面和一小时 16 客户端测试。2026-09-05 的一小时结果为 1,115 次调用全部成功、17,840 个大图消息全部收到、Runtime Worker 句柄净增 0；p50 为 101.143 ms，p95 为 1,775.461 ms，p99 为 2,048.877 ms，最大值为 4,775.529 ms。资源释放通过，尾延迟未通过。短时尝试复用 binary JSON 帧没有改善 p95，已撤回，避免增加无收益的协议分支。

显示连接发送和 `ready` 等待超时为 30 秒，用于容忍页面无需实时性的系统短暂停顿；仍然每连接最多一份在途、没有队列、缓存或重放，且不进入业务响应路径。Backend 在一次开发态热重载后的整小时测试中出现单次全局内存/句柄台阶，之后稳定；显示连接关闭时对应句柄全部释放，因此当前不能归因为逐次 Preview 泄漏。2026-09-05 对运行中 Backend 的进一步核对显示：完成完整节点目录动态参数解析后的 Windows `PrivateMemorySize64`/pagefile commit 约 1.95 GiB，Working Set 约 778 MiB、USS 约 566 MiB；同一 Backend 热重载后、动态参数解析前分别约为 1.21 GiB、266 MiB、228 MiB。增长与 Backend 为 SAM3 设备/精度下拉选项导入 Torch 后出现的 Torch/CUDA DLL 映射一致，另有 workflow-trigger mailbox 等 mmap；约 1.95 GiB 既不能等同为物理常驻内存，也不是纯启动基线。Runtime 监视页现明确跳过编辑器参数 UI 解析，不再因只读画布主动加载 Torch/CUDA；编辑器功能保持不变。Backend 其他入口仍可能按功能加载 Torch，整体 Working Set、USS、线程和映射来源继续纳入项目级运行时门禁。

相同内容和节拍的单客户端 3 分钟对照为 58/58 成功，p50 94.801 ms、p95 230.403 ms、p99 236.021 ms、最大 247.644 ms，Worker 与 Backend 资源无增长。因此无需继续修改捕获、默认值注入或 Runtime Worker；尾延迟来自同一 Backend 的 16 路 2.63 MB WebSocket 扇出。若 16 个大图页面属于真实生产要求，应单独评估显示数据面进程隔离；当前不为未确认需求增加服务和部署复杂度。

Runtime 停止/启动和异常退出自动恢复均已按“监视页面保持打开”实际验证。旧 Worker 通道关闭后，页面按 2、4、8、10 秒封顶退避重新读取权威快照；新 Worker 身份出现时清除旧代显示、重置序号并自动订阅，随后可接收新执行结果。普通同身份网络重连和手动刷新保留最近完成画面；关闭页面立即停止重连。连接名额已满时页面明确显示状态且不自动重试。该恢复只属于浏览器观察连接，不启动 Runtime、不补发历史、不调用 Workflow。

监视快照现只携带发布图实际引用且与发布依赖摘要一致的节点定义，不再请求全量实时 Node Catalog。节点定义缺失或变化时使用 Template 连线和 App binding 回退显示并提示，不能把新目录端口和名称静默套用到旧发布版本。这既收口发布图确定性，也避免多个停止态页面高频读取大目录；没有引入定义快照的新存储格式或第二套版本体系。

连续 5 次实际 Runtime 停止/启动时，Backend 句柄采样为 1373、1373、1375、1376、1376，等待清理后为 1375；相对测试前净增 1，没有出现按重启次数线性增长。第 5 次恢复后的真实调用成功，保持打开的页面显示了新 Worker 的图片与 JSON。Backend 源码热重载导致服务进程和全部 Runtime Worker 换代时，同一页面也自动回到等待状态并在后续调用继续显示。

只读节点目录修复后的 3 分钟、16 客户端复测共 57/57 次调用成功，912/912 个 2,628,477-byte 消息全部收到，零丢帧和客户端错误；Backend Private/RSS 分别净增 0.04/0.08 MiB、句柄净减 32，Runtime Worker 句柄净增 0。调用耗时 p50 89.479 ms、p95 206.727 ms，但 p99 仍为 1,744.649 ms、最大 1,757.144 ms。常态延迟和 Backend 内存基线得到改善，偶发大图扇出尾延迟仍未通过；不据短测覆盖一小时失败结论，也不为此引入队列、缓存、协议分支或新显示进程。

本轮状态机和发布定义修复后的 40 次四阶段顺序 A/B 对照中，无观察两轮 p95 为 119.051/118.619 ms，单个 2,628,465-byte 观察连接为 237.618/155.458 ms；160 次业务调用全部成功，Worker 内存、句柄和线程无增长，连接结束后 Backend Private 约净增 0.25 MiB。包含 4 个在用节点定义的权威快照响应为 9,970 bytes，连续 50 次读取 p50/p95 为 15.692/24.012 ms。随后 60 秒、16 客户端复测完成 31 次调用且零调用失败，客户端无错误，489 次大图交付中单客户端最多跳过 1 帧，符合无队列和慢客户端可跳帧约束；Worker 句柄净增 0，Backend Private/RSS 约净增 0.21/0.23 MiB且句柄回落 32。该轮 p95 仍为 1,037.104 ms、最大 2,749.395 ms，再次确认多客户端大图广播尾延迟未通过，不扩大数据面实现。

开发环境 4 个实际 YOLO11 classification Deployment 已完成双实例有界对照：每个 Deployment 同时发起 2 个请求并执行 20 次，`instance-0`/`instance-1` 各完成 10 次，80 次总调用全部成功，4 个模型进程的错误、句柄和线程净增均为 0。该项验证路由和资源回落，不把 4 模型同时承压的 HTTP base64 延迟当作单 Workflow 性能门禁。

多客户端大图广播尾延迟作为已知边界保留，当前实现已经满足简洁、有界且不影响业务正确性的阶段目标，不再以增加队列、缓存、协议分支或独立显示服务的方式优化。下一步直接实现轻量 App Mode；它复用现有完成后显示通道，不实现逐节点进度或强制终止终态，也不能把既有 16 客户端大图尾延迟解释为已经通过高性能认证。

短测不能替代长期稳定认证。测试使用明确选择或独立创建的开发资源，不为页面验收隐式执行真实生产清理；临时产物只在 `.tmp/<task-name>` 中使用，确认本次进程停止后清理，不作为长期文档资产。

## 9. 事实来源与参考

- [现有 Workflow 编辑器](../architecture/workflows/editor.md)、[App 版本管理](../architecture/workflows/app-versioning.md)：草稿、发布版、Runtime 和 Trigger 的现有边界。
- [Preview 显示适配](../../frontend/web-ui/src/workflows/workflow-editor/preview/useWorkflowPreviewDisplays.ts)、[Image Preview](../../backend/nodes/core_nodes/io/image/image_preview.py)：当前节点显示 payload 和前端识别实现。
- [图执行器](../../backend/service/application/workflows/graph_executor.py)、[节点事件](../../backend/service/application/workflows/execution/events.py)、[执行清理](../../backend/service/application/workflows/snapshot_execution.py)：载荷保留、事件清理与资源生命周期。
- [Runtime 服务](../../backend/service/application/workflows/runtime_service.py)、[Worker](../../backend/service/application/workflows/worker/process.py)：同步/异步出口及现有超时控制消息，不视为已实现显示数据面。
- [Node Pack 规范](../nodes/node-pack-manifest.md)：区分能力声明与真正的前端扩展实现。
- [ComfyUI App Mode 文档](https://docs.comfy.org/interface/app-mode)、[本地参考 appModeStore](../../projectsrc/ComfyUI_frontend/src/stores/appModeStore.ts)：只借鉴同一 Workflow 在编辑视图与应用视图间切换的思路；本项目输入固定来自全部 App Entry，显示项按 Preview 端口显式配置，不复制其执行、队列或分享体系，参考仓库也不是本项目运行时依赖。
