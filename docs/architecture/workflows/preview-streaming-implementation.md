# Preview 实时执行代码实施清单

日期：2026-09-10。状态：S00–S09 代码已落地，S10 本机验证已执行；逐项证据和未覆盖范围见 [验证记录](preview-streaming-verification.md)。

依据：[Preview 实时执行方案](preview-streaming-design.md)。本文固定具体实现选择、依赖、完成条件和迁移规则；发生冲突时先修正文档，不由实现者自行扩大范围或增加兼容分支。

## 1. 不可偏离的结果

| 编号 | 必须实现 | 禁止替代 |
| --- | --- | --- |
| R1 | 节点完成后立即增量显示，后续节点仍可继续执行 | 整图终态才加载图片/值；WS 只通知前端再 GET 完整结果 |
| R2 | Preview 输入、快照、事件和显示只在应用内存/OS shared memory 中流转 | JSONL、临时 ZIP/JSON/图片、multipart spool、文件支持 mmap、磁盘降级 |
| R3 | 常驻 Preview Worker 执行重任务，API 独立处理连接与存活 | 请求处理器跑模型/OpenCV；将长执行或进度静默当作服务故障 |
| R4 | 正式 Runtime/Trigger 保留现有同步高性能数据面及已有异步语义 | 把 Preview 流式协议、磁盘改造或缓存策略套用到正式执行 |
| R5 | 保留现有节点业务、模型输出、原图坐标和显式保存行为 | 重写模型算法、改阈值、以缩略图替代模型输入、静默忽略保存配置 |
| R6 | 有界资源、有限恢复、显式失败 | 无限缓存、浏览器慢则阻塞执行、内存不足转磁盘、自动重放业务 |
| R7 | 开发阶段统一 v1，只保留最新 Preview 实现 | 双版本、旧接口适配、历史只读层、双写、回退开关和不可达“保险”代码 |

“无磁盘”针对平台 Preview 数据流，不禁止读取现有模型/业务文件、明确保存节点写目标文件或普通有界日志。自定义节点主动写盘必须按能力声明核对，不宣称平台能拦截任意 Python 的一切副作用。

## 2. 已确定的实现选择

### 2.1 边界与保留项

- 新建 `PreviewSessionManager`，不继承持久化 `WorkflowPreviewRunManager`，不使用其 DB/JSONL 恢复方法。
- 复用进程池的启动、复用、监督、取消及退出回收逻辑，替换其请求/响应交接和状态归并；不用磁盘快照路径作为 Worker 输入。
- 使用单 API 进程拥有会话表的本地部署形态。装配时检查该前提；若目标部署为多 API 进程，应先设计会话归属路由，禁止悄悄创建多份互不相通会话，也不增加 Redis。
- 每会话最多一条 active run；全局并发沿用 `preview_worker_count`（当前默认 2），满载立即返回容量错误，不新增持久化排队系统。
- 业务执行超时沿用现有策略和 `preview_default_timeout_seconds`（当前默认 1800 秒）；三分钟只限制本次验收过程，不改变节点或业务 timeout。
- `12c3ba27` 的节点目录刷新、并行分支单节点范围、文档身份隔离和 Viewer 关闭语义保留。禁止整提交回滚。
- `runtime_preview.py`、`useRuntimePreview.ts`、正式 Broker/Trigger 协议保持职责。若需抽取纯函数，只允许可验证的行为等价提取，不把 Runtime capture 改成 PreviewSession。

### 2.2 API 定稿

API：`/api/v1/workflows/preview-sessions`；WS：`/ws/v1/workflows/preview-sessions/{session_id}`。数据格式为 `amvision.workflow-preview-session.v1`。按用户确定的开发阶段规则，在 v1 内直接替换 Preview 合约，前后端、调用方、测试与文档一次同步；不保留旧持久化 Run 合约或兼容层。正式 Runtime/Trigger 的既有 v1 合约保持原有职责。

| 操作 | 接口/消息 | 返回与语义 |
| --- | --- | --- |
| 创建 | POST sessions | 201：session_id、epoch、有效预算；服务器绑定账号/项目/应用，不能信任客户端 owner 字段 |
| 建立订阅 | WS connect | 首次返回 session.snapshot；完成后才上传和提交 |
| 上传 | WS input.begin / 二进制块 / input.commit | 返回 input_id；分配前检查预算，全部完成且校验成功才可执行 |
| 执行 | POST sessions/{id}/runs | JSON 内存快照、input_id 引用、request_id、execution_scope、document_revision；202 返回 run_id，忙返回 409，容量满返回 429 |
| 取消 | POST sessions/{id}/runs/{run_id}/cancel | 请求取消；只有 Worker 实际停止才发 cancelled 终态 |
| 请求显示 | WS display.get / value.get | 按 blob_id/revision 或输出端口分页读取内存，不访问任意路径 |
| 恢复 | 同一 WS 重新订阅 | 返回当前状态快照和最新显示描述；不读取事件文件、不自动重跑 |
| 释放 | DELETE sessions/{id} | 幂等，关闭活动连接、取消未结束执行、待借用解除后释放；返回受理后仍须监督实际回收 |

模型、部署和既有应用查询仍可读取原数据库；不因此创建 Preview 运行记录。控制接口可以使用现有 REST 鉴权，WS 复用已有认证机制；无新增静态令牌配置。

request_id 在同一会话内去重；同 ID 同内容返回同一 run，同 ID 不同内容返回 409。开始执行前固定不可变的内存快照，编辑器之后修改不影响正在运行的图。首次提交必须已完成订阅，避免极快节点在前端初始化前完成。

每会话最多保留 256 个已受理 request_id 的小型摘要，达到上限后拒绝新执行并允许显式创建新会话；不淘汰去重记录后把旧请求当作新业务执行。旧会话已失效的重试直接返回失效，不跨 session 自动重放。保存或协议节点的副作用不能据连接断开推断为未发生。

### 2.3 消息与状态

事件公共字段：`format_id, session_id, epoch, run_id, seq, type, document_revision, payload`。`run_id` 在会话事件可为空；`seq` 由服务端会话归并线程生成。节点事件携带 `node_id, invocation_id, scope_path`；scope_path 包含嵌套分支/循环调用身份，不能只用 node_id。

- `run.accepted` → `run.started` → `run.finished(status)`，终态只能一次提交；非法逆向转换拒绝并记录有界诊断。
- `node.started` → 可选 `node.progress` → `node.finished(status)`。异常、超时、取消必须区分；未到达的节点显示未执行，不伪造失败。
- `display.updated` 表示指定节点/端口/revision 的完整显示可请求；小值可直接内嵌，图片传 Blob 描述。
- `run.finished` 不表示所有图片都已解码。已完成业务状态和显示可用性分别处理。
- `session.snapshot` 带 watermark，先原子订阅再取得快照，之后仅应用 `seq > watermark` 的事件。进度合并允许序号间隙，不能因每个间隙都 GET 或报错。
- 并行节点各自有状态；循环保持当前调用和有界摘要，不保存无限调用历史。父子调用正确归属，耗时不能因显示合并重复计数。
- 无内部进度的算法只显示执行中/耗时；completed/total 由节点真实报告。节点进度能力作为最新 v1 执行上下文的可选扩展；未报告内部进度的节点仍可正常运行，不另建旧节点兼容分支。

二进制消息采用固定 32 字节头：magic 4、version 1、kind 1、flags 2、transfer_id 16、chunk_index 4、payload_length 4，整数大端；总大小、块数、媒体类型和摘要在 begin JSON 中声明。单块 256 KiB，接收验证顺序、长度、归属和预算。浏览器不得获得 SHM 名称/句柄；只获得授权 session 中的 blob_id。单连接只设一个发送协程，按块调度，控制事件优先。

### 2.4 初始资源默认值与所有权

以下为实施初始默认值，不宣称已经测得最优；修改须在步骤记录中给出测量依据。

| 资源 | 初始值/规则 |
| --- | --- |
| 单次 JSON 快照 | 8 MiB，结构深度与元素数量另校验 |
| 同时保留会话 | 全局 8 个；与执行进程数分开限制，空会话也计数 |
| 单个上传文件 | 64 MiB，并遵守原节点输入限制，取更严格者 |
| 受管会话数据 | 512 MiB/会话，全局 1 GiB；包含输入、输出、编码、SHM 和保留显示，不按对象数量代替字节 |
| 控制队列 | 1024 项且不超过 4 MiB/会话，进度合并；溢出恢复规则见下文 |
| WS 图片发送窗口 | 最多 4 个已发送未确认块，4×256 KiB；ACK 在浏览器完成接收归档后返回 |
| WS 心跳 | 15 秒；无节点进度不影响心跳 |
| 断线宽限 | 60 秒；所有订阅者离线才开始计时，恢复任意合法订阅后取消计时 |
| 空会话 | 创建后 60 秒未订阅回收；未完成上传 60 秒无数据回收 |
| 页面保留 | 每会话最新结果；新 run 期间旧图明确标记且占同一预算；有连接不按业务耗时淘汰 |

上述受管预算不是进程总 RSS/GPU 的硬上限。模型、第三方算法工作区、Python 对象和驱动缓存另计；不得声称只设置字节计数就能防止所有 OOM。模型加载受独立缓存/并发限制，超限拒绝或失败，不改变模型精度/设备来“省内存”。

SHM 由会话资源管理器统一登记名字、容量、owner epoch 和引用数；分配、发布、借用、释放都有明确状态。API 创建并持有控制所有权，Worker 请求分配后附加；生产者结束不提前删除仍借用的块。Windows 最后句柄关闭才释放，其他平台验证 close/unlink 的唯一所有者及资源跟踪行为。

Worker 死亡由父进程回收该 Worker 的登记资源；API 死亡由现有父进程监视使 Worker 退出。先停止生产、撤销借用、关闭附加映射，再释放登记所有权；不能边发送边释放 memoryview。每会话结束必须通过所有权计数归零断言。

控制传输与大图请求使用分离的有界队列，不把 allocate/free 响应挤在图片发送队列后。控制状态先归并为当前快照再入 WS 队列：慢客户端溢出时关闭并允许重连快照，不能影响 Worker。Worker 到父进程的控制通道若失效/溢出且无法继续保证事件正确性，则终止该 Preview 并明确失败；不得让业务静默成功、丢掉终态或无界等待。

显示观察必须在节点输出仍有效时取得自己的只读借用或有界副本，再异步编码；不能仅保存可能被下游原地修改的 numpy/Tensor 指针。不能为了显示给业务数组强制设置只读或改变算法行为。node.finished 先交付状态；图片编码由 Worker 内有界显示任务处理，display.updated 在完整编码发布后发送。编码队列满时合并旧显示或明确 display.unavailable，不阻塞业务线程等待浏览器；所有复制/编码成本计入预算与测量。

## 3. 文件职责和变更边界

所有路径相对仓库根目录。新增目录只在对应步骤实施时创建。

| 文件/目录 | 处理 |
| --- | --- |
| `backend/contracts/workflows/preview_session.py`（新增） | v1 Pydantic DTO、事件/错误/二进制常量；不引入持久化实体 |
| `backend/service/application/workflows/preview/session.py`（新增） | 会话状态、所有权、受理、当前快照及去重 |
| `.../preview/events.py`（新增） | 节点观察、归并、进度合并；保持小而具体 |
| `.../preview/buffers.py`（新增） | SHM/内存对象、预算、借用和释放；不新建通用 Broker |
| `.../preview/worker.py`（新增） | 内存请求执行、资源注入、模型作用域；承接旧进程入口 |
| `.../preview_execution_pool.py` | 去掉 DB/磁盘回读依赖，复用监督和超时；迁移完成后归入 preview 目录或保留单一入口，不能两份池实现 |
| `backend/service/api/rest/v1/routes/`、`api/ws/v1/` | 在现有 v1 路由体系注册 Preview Session，删除旧 Preview Run 路由；不创建新的 API 版本目录 |
| `backend/service/api/bootstrap.py`、`settings.py`、根路由 | 生命周期装配、限额配置、退出清理；避免热更新中途切换活动会话 |
| `backend/service/application/workflows/execution/contracts.py`、`graph_executor.py` | 注入可选观察/资源访问边界，覆盖正常/并行/循环/选择路径；正式无订阅执行无新增序列化或后台线程 |
| `backend/nodes/runtime_support.py` 和图像公共读写 helper | Preview reader/writer 注入；禁止散落 node_id 判断 |
| `backend/nodes/core_nodes/support/deployment_model.py`、`core_nodes/model/inference/sahi_inference.py` | Preview 模型输入及 gateway 适配，单张/批量均覆盖；保留正式调用默认实现 |
| `backend/service/application/workflows/model_sessions/` | 复用模型版本/设备/参数缓存及关闭机制 |
| `backend/nodes/core_nodes/io/image/image_preview.py`、`debug_image_panel.py`、`core_nodes/video/windows/frame_window_preview.py`、`video_runtime_support_payloads.py` | 使用 Preview 内存显示 sink，显式保存行为独立 |
| `frontend/.../services/workflow-preview-session.service.ts`（新增） | v1 控制/WS/Blob 协议，与 runtime service 分离 |
| `frontend/.../preview/useWorkflowPreviewSession.ts` | 单一事件 reducer 和会话管理，替换旧终态加载 |
| `frontend/.../preview/useWorkflowPreviewInputs.ts`、`useWorkflowPreviewDisplays.ts` | 上传/显示的 v1 内存引用、原图请求与 URL 回收；保护 Runtime 共用 helper |
| `frontend/.../actions/`、`pages/WorkflowEditorPage.vue`、节点显示与 Viewer 组件 | 受理/取消/状态/进度接线，局部更新，不增加页面切换动画 |
| `.../previewDisplayResults.ts`、后端 `preview_result_store.py` | 完全删除，连同无调用方的旧读取/写入代码及对应旧测试；不得搬入历史适配目录 |

实施前生成实际调用清单，覆盖所有 `build_preview_run_artifact_object_key`、LocalBuffer 写入口、PreviewRun 创建、WS/REST 调用方、测试和文档。当前检索未在仓库 SDK 中找到 `/preview-runs` 调用；不能据此假定外部用户不存在。

## 4. 顺序实施卡片

每步格式固定为：前置证据 → 代码变更 → 验收命令/场景 → 结果 → 遗留项。验收未通过不把该步标记完成；后续可做独立只读准备，不把失败隐藏到最终阶段。

### S00：冻结范围、建立回归锚点

- [x] 记录基线提交 `12c3ba27` 和开始实施时 HEAD、工作区差异。
- [x] 按第 3 节生成完整调用方/写盘入口矩阵，标记 Preview 专有、Runtime 共用、明确业务保存三类。
- [x] 核对既有节点目录，按 port/body 契约生成显示测试集合，不把历史“41”写成永久固定上限。
- [x] 保留用户编辑器未保存状态；不用刷新或 HMR 获取基线。真实执行在隔离应用、独立输出目录进行。
- [x] 保存现有测试中模型输出、取消、单节点范围和 Viewer 行为断言；建立“前节点显示、后节点还未结束”的失败用例。

门禁：调用矩阵有真实代码位置；不可遗漏上传 spool、模型 gateway、视频/debug helper。此步不运行 30 分钟测试。

### S01：实现合约与纯状态归并

- [x] 实现第 2 节 DTO、事件、二进制 codec、版本拒绝和错误分类。
- [x] 实现后端会话/运行/节点状态转换及前端纯 reducer；临时使用可控内存假事件源。
- [x] 覆盖重复/旧 epoch/旧文档事件、并行 invocation、快照 watermark、0/false/null、终态幂等和取消竞争。

门禁：同一组黄金事件序列在前后端归并得到相同状态；不得依赖时间 sleep 模拟正确性。合约定稿后不随意改字段名。

### S02：实现资源所有权与无磁盘输入

- [x] 实现有界内存/SHM 管理器、分块校验、分配响应通道、pin/unpin、超额错误及清理。
- [x] 把 JSON 内存快照和 image input_id 变成 Worker 内部请求，禁止传 `*_snapshot_object_key`。
- [x] 为既有节点资源上下文注入 Preview 内存 reader/writer；Preview 私有内存引用按最新 v1 合约显式定义，正式 image-ref.v1 数据面不增加 Preview transport 分支。
- [x] 在 Windows conda 与发行 Python 下验证父/子进程附加、取消、强制退出、最后句柄回收；POSIX 单独覆盖或标明尚未测试。

门禁：57.1 MiB 实际 BMP 可上传与解码；人为禁止 Preview 临时写文件时仍通过；所有失败分支无遗留 SHM。此步不声称模型已接入。

### S03：纵向打通纯值图和常驻 Worker

- [x] 装配内存 SessionManager，复用池监督机制，从内存执行快照。
- [x] Worker 从既有执行器回调生成 started/finished；可选 progress 单独接入，消息不先写 JSONL。
- [x] 内存记录业务终态与已完成节点；失败后不从 DB/文件恢复。保留模型目录空闲边界刷新。
- [x] 提供 v1 创建/执行/取消/释放 API 和 WS，先以 Value→Preview→Delay 图贯通。
- [x] Vite `/api/v1`、`/ws/v1` 代理及发行服务 WS 路由均实际验证，沿用既有认证/会话失效策略；不把默认静态页回退返回的 HTML 当作成功协议响应。

门禁：值节点完成时 WS 已收到值，Delay 仍在运行；池复用、满载拒绝、超时和不协作取消正确，HTTP 保持响应。内存执行路径不存在 PreviewRun DB insert 或结果文件。

### S04：前端实际逐节点更新

- [x] v1 session service 接入 Actions/Page/Inputs；为新会话独立处理连接状态。
- [x] 事件直接更新节点状态、耗时、端口摘要和值；去除当前页面对 Preview 资源流快照的依赖。
- [x] 顶部区分 Runtime 状态和 Preview 状态；长节点显示真实执行中/耗时，无伪百分比。
- [x] 修改文档、新 run、切换应用和多标签页均隔离；显示失败不改业务终态。

门禁：浏览器录制前节点值已经显示、Delay 尚未完成；网络中无 Preview 周期 GET 或每事件 GET；节点不整体重建，选择/滚动位置不跳变。

### S05：迁移图片、调试图和所有显示 helper

- [x] 实现 v1 内存显示描述与二进制 Blob，Display sink 截获显示输出，不让通用 helper 写临时文件。
- [x] 覆盖 Image/Value/Table/Gallery/Frame Window、当前全部 debug panel，以及普通节点结果摘要/分页。
- [x] 分离显式保存参数和显示 transport；具有有效显式保存位置的已有节点不能被静默改变副作用。
- [x] 缩略图、原图、overlays、ROI/圆/线/模板/掩码交互保留同一坐标定义；原图按需读取和 pin。
- [x] 每种 transport 和自定义显示输出的兼容方式写入矩阵；不能只让真实 Hough 一例通过。

门禁：禁止 Preview 写入的完整图像流程可逐节点显示；原图尺寸与坐标一致，旧图只在新 Blob 完整后替换，缺失/超额有明确状态；显式保存仅写授权目标。

### S06：模型与批量执行的内存适配

- [x] 清点 deployment detection/classification/segmentation/pose/obb、批量和 SAHI 等模型入口及相关图像转换。
- [x] 在 Preview Worker 注入具体 gateway 适配，复用既有 ModelRuntime 和模型 Session，保持部署快照、模型格式、设备、精度、阈值和前后处理相同。
- [x] 移除 Preview 中 `_TemporaryLocalBufferInput` 对正式文件 arena 的交接；不可通过改全局默认 gateway 影响 Runtime。
- [x] 实现模型作用域命中/换版本/禁用/失败关闭/缓存容量；当前真实部署为 CPU，已实现有界模型缓存；GPU 显存计量列入具备相应模型和设备后的验收，不用 CPU 结果代替。
- [x] 现有平台支持的模型入口不能以“尚不支持 Preview”替代迁移。缺少真实模型时先做契约与适配测试，真实精度状态单列未验收。

门禁：YOLO11 真实分类输出与同条件正式路径一致；结构化与数值容差提前按后端确定，不能失败后放宽。其余类型通过适配契约，所有 Preview 输入输出禁止进入 images.mmap；不能以只检查没有 JSON 文件代替。

### S07：并行/循环、进度及交互完整性

- [x] 从实际执行上下文构造 invocation_id/scope_path，覆盖 Parallel、ForEach、Selection 及其嵌套。
- [x] 完整图与单节点 scope 分别校验；保留已验证 Parallel 修复，补齐循环/选择内部目标的前置依赖语义，禁止为单节点调试多执行无关副作用分支。
- [x] 为能提供真实进度的批量/循环入口发 progress；普通 OpenCV 调用无内部进度时不编造事件。
- [x] 查看器“预览/应用并预览”、只更新目标、新结果就绪替换、主动关闭后不重开全部接入 v1。

门禁：并行有多个执行中节点；循环调用不串结果、完成计数不重复；单节点目标只执行正确上游闭包，无法定义的 scope 在执行前报错，不补跑整图。

### S08：背压、断线、退出和异常资源回收

- [x] 对慢接收、停止 ACK、断线、二进制半包和乱序块做故障注入。
- [x] 验证 node.progress/旧缩略图合并，控制终态不静默丢失；重连快照切换无竞争窗口。
- [x] 多订阅者退出仅释放所属借用；最后订阅者断线开始 60 秒宽限，显式释放不等待宽限。
- [x] 测试提交响应丢失后 request_id 去重、取消同时完成、Worker/API 崩溃、旧 epoch、输入未 commit。
- [x] 禁止按 Viewer 持续打开无限保留多个原图版本；旧版本释放与新版本 pin 原子衔接。

门禁：慢客户端不阻塞 HTTP 或执行；队列字节、Blob/SHM 计数有界；取消确认后资源归零；失效提示明确且不自动重跑。

### S09：统一 v1 并完整删除旧 Preview 实现

- [x] 前端仅调用最新 v1 Preview Session；删除 Preview 两秒轮询和“终态 GET 完整结果”分支，不改 Runtime 的资源流。
- [x] 删除旧 `/preview-runs` 创建、multipart、GET/list、events、displays、display-outputs、artifacts、cancel、DELETE 以及旧 WS 事件路由。旧地址自然不存在，不保留专用 410、重定向或兼容适配。
- [x] 删除旧 PreviewRun DTO、前端类型/服务、Manager、Repository 方法、装配项、配置项及 Preview 专有持久化模型；共用代码按实际引用拆分，不能误删正式 Runtime/Trigger 依赖。
- [x] 删除 snapshot/JSONL/result 文件写读、旧进程入口、旧上传临时目录交换与清理、终态加载、preview_run_id 历史恢复和历史视图；不新建 legacy reader。
- [x] 清理旧 sessionStorage key、旧 URL 查询参数读取、测试 fixture、示例、脚本与失效文档。行为回归断言迁移到新测试，不能为让测试通过而继续维护旧实现。
- [x] 列明 Preview 专有表/字段/索引/外键，通过一次性 Alembic 迁移移除；现有开发数据库与全新初始化都验证。审查既有迁移的依赖，保留升级所必需的迁移记录，但不得在服务中保留旧 schema 兼容执行逻辑。
- [x] 旧 Preview 临时目录由一次性清理步骤按已核对的绝对路径处理，不保留后台历史资产管理器。数据不是新内存会话的输入来源；业务保存文件、应用/模型版本和正式运行记录不属于清理范围。
- [x] 更新 OpenAPI、WS 合约、所有调用方、配置说明和索引，使文档只指导最新 v1 实现；旧审计记录仅可作为明确标注的历史事实，不能作为可执行接口说明。

门禁：旧 Preview 路由未注册，旧运行时代码/类型/调用方零引用，无双写、回退、历史只读或版本过渡层。迁移记录中的旧符号只用于一次性结构升级；没有废弃的当前 ORM 模型或 Repository。正式 Runtime/Trigger 入口、payload、默认选项及数据面保持原行为。切换前确认旧活动 Preview 已结束，不在运行中热切换；前后端一起更新。

### S10：真实环境与发布前验证

- [x] 自动测试按下节矩阵通过，前端类型检查和构建通过；发行 Python 的 spawn/SHM/取消通过。
- [x] 使用 `workflow-app-20260831130620` 的确认快照建立隔离副本，图片来自 `data/files/developer/图片/3570`；保存输出只指向本次验证目录。
- [x] 先短执行验证图片、3 个值、Hough 调试图、原图、单节点和部分失败；再一次 90 秒 Delay 的整体验证（实测含真实模型共 108.407 秒，遵守三分钟观察限制），总观察不超过约三分钟。
- [ ] 记录逐节点可见时延、HTTP 探测、最后业务输出、RSS/Private Bytes、GPU、SHM/Blob/队列字节；结束后确认下降/归零，不只截最终成功图。
- [x] 核对正式 Runtime/Trigger 独立回归，不用 HTTP 延迟替代推理 P99，不将合成数据验证标为真实精度通过。
- [ ] 清理本任务进程及临时产物，长期证据保存在文档/交付目录；自动审批拒绝清理时如实记录，不能绕过。

清理状态：本轮目录删除被自动审批拒绝（`blocked by policy`），目录仍保留。资源计量中未实测项目见验证记录。

门禁：以下验收表逐项有证据，任何未通过项不能写“全部完成”。不主动组装/替换生产发行包、不提交 Git，除非后续明确要求。

## 5. 验收证据矩阵

| 编号 | 场景 | 必须断言 |
| --- | --- | --- |
| T01 | Value→Display→Delay | Delay 未结束时页面已有准确值，网络没有完整结果 GET |
| T02 | 真图→图像处理→Display→Delay | 缩略图提前出现，原图按需获取，尺寸与坐标一致 |
| T03 | 全部显示契约 | 值/表/图库/帧窗/debug；0/false/null/空值/长数组不混淆 |
| T04 | Parallel/ForEach/Selection | invocation 身份、节点状态与目标 scope 正确；无无关副作用执行 |
| T05 | 模型单图/批量/SAHI | Preview 输入不写旧 arena；算法实现和参数与正式路径一致 |
| T06 | 断线/慢客户端/半包 | 重连快照正确、终态可恢复、内存有界、执行不被网络拖住 |
| T07 | 取消/timeout/进程退出 | 只在实际终止后终态；保留已完成显示、释放 SHM 和模型借用 |
| T08 | 文档修改/多标签/重复提交 | 旧结果不覆盖新文档，不重复执行保存或协议节点 |
| T09 | 禁止 Preview 写盘 | 上传到显示全链无平台临时文件/文件 mmap；显式保存允许且目标正确 |
| T10 | Runtime/Trigger | 公共契约不变，无 Preview 专有观察/编码/持久化；输出一致 |
| T11 | conda/发行 Python | Windows SHM 生命周期及 spawn 回收；未测平台明确列出 |
| T12 | 真环境三分钟 | 实时显示、最终业务、HTTP 与资源证据同时成立 |

测试文件建议按职责新增 `test_workflow_preview_session.py`、`test_workflow_preview_memory.py`、`test_workflow_preview_stream.py`；前端对应 session/service/reducer/Viewer 测试。真实验证使用 `tests/integration/workflow_preview_session_live.py`，删除旧 `workflow_preview_display_validation.py`，不能继续通过旧文件 manifest 判断成功。

状态/小值 P95≤100 ms、缩略图 P95≤250 ms 仅为本地初始显示目标。跨进程/浏览器时延需要时钟校准或同观察时钟的测试屏障，不直接相减两端未对齐的 performance.now；记录测试方法、样本量和分布。三分钟样本不用于长期性能尾部或工业稳定性结论。模型准确性仅据实际模型和数据报告；历史 SHM P99 +17.46% 失败不由本轮解除。

## 6. 防偏离检查和实施日志

每步结束核对：

1. 是否出现新的磁盘结果文件、轮询、DB Run 写入或双写？出现则本步失败。
2. 是否新增正式 Runtime/Trigger 的事件序列化、锁、编码或后台任务？出现则先缩回 Preview 注入边界。
3. 是否只测终态、只 mock 完成函数、或用合成结果宣称模型精度？出现则补真实链路证据。
4. 是否将不支持的核心节点静默跳过、扩大单节点执行范围或改默认模型参数？出现则撤回该实现方式。
5. 新资源是否有明确 owner、预算、异常释放及终止验证？缺一则不能进入下一步。
6. 原设计与实现是否冲突？先在设计文档记录具体原因和影响，再修改；不得用含糊“兼容旧逻辑”代替决策。

实施日志使用以下固定表，每次只记录实际完成的结果，不提前打勾：

| 步骤 | 起止提交/工作区版本 | 改动文件 | 核对结果 | 验证命令和结果 | 未通过项/下一步条件 |
| --- | --- | --- | --- | --- | --- |
| S00–S09 | `12c3ba27` → 当前工作区 | Preview 会话、Worker、显示、节点观察、前端和旧实现退休 | v1 单实现，正式数据面没有引入流式传输 | 详见验证记录的测试命令和结果 | GPU / POSIX 不在本机实测范围 |
| S10 | 当前工作区 | 真实探针、迁移与浏览器验证 | 57.1 MiB BMP、24 个空槽、90 秒 Delay、17 个显示、断线恢复通过 | 108.407 秒；HTTP 107 次成功 | 显示 P95、GPU、长期 P99 / 稳定性尚未验收；资源计数归零由跨进程测试证明 |

代码迁移、已验证功能及未完成的性能/平台验收应分别报告，不能把本机功能通过写成所有验收项均通过。发布上线、全部模型真实精度及长期工业验收另有范围，不能合并宣布通过。
