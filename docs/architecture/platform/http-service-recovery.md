# Windows HTTP 接入与服务恢复方案

状态：接入适配、持续探测、受控恢复、桌面观察和发行接入已实现，2026-09-09。定向测试及真实数据结果见 [修复验证记录](../../operations/http-service-recovery-validation-20260909.md)。第 7 阶段性能与 24 小时验收未完成，不能据此宣布生产放行。

## 1. 目标与边界

正常客户端断连不能关闭整个 HTTP 监听。服务进程存活但无法接入时，Supervisor 必须发现并准确报告；满足进程身份、资源清理和任务恢复条件后，执行有次数限制的恢复。

保持现有 Vue、FastAPI、独立 daemon、worker、Workflow Runtime 与共享内存架构；不增加常驻微服务，不改变模型输出、Trigger 结果或共享内存二进制协议。公开默认凭据保持现状，日志容量问题不纳入本次实现。

恢复保证是“服务可重新接入、状态可信、旧资源不可误用”。对含外部副作用的在途请求，不能承诺透明恢复或 exactly-once；不自动重放请求来掩盖连接断开。

## 2. 修复前已核对事实

1. 发行 Python 3.12.13 的 `IocpProactor.accept()` 将 WinError 64 向上传递；`BaseProactorEventLoop._start_serving()` 捕获 `OSError` 后关闭监听 socket。隔离注入已复现 `listener_closed=true`、`event_loop_closed=false`。
2. 现有 [service launcher](../../../runtimes/launchers/service/start_backend_service.py) 使用 Uvicorn CLI。实装 Uvicorn 的 `get_loop_factory()` 支持 `module:function` 自定义工厂；Windows 非 reload 路径使用 Proactor，reload 路径可能使用不同循环，必须分别验证。
3. [full-stack launcher](../../../runtimes/launchers/full/start_amvision_full.py) 启动时等待 health，但以 HTTP 状态 `<500` 作为就绪条件；运行阶段主要检查 `process.poll()` 和日志捕获线程，未持续验证接入能力。
4. 现有 `/api/v1/system/health` 包含 Broker 健康信息，不适合直接变成高频、纯 HTTP 接入探测。
5. 桌面 [FullStackController](../../../launcher/src/Amvar.Launcher.Infrastructure/Runtime/FullStackController.cs) 有监听检查，丢失监听时返回 `Starting`；[BackendSessionController](../../../launcher/src/Amvar.Launcher.Core/Application/BackendSessionController.cs) 的连接循环在成功后返回，不能依靠该循环保证运行期持续观察。
6. Broker 是 backend-service 管理的 companion process；其 owner、epoch、guard 与其他执行进程存在明确关联。单独杀死 backend 再启动不能被默认认定安全。

CPython [issue #93821](https://github.com/python/cpython/issues/93821) 和 [PR #124779](https://github.com/python/cpython/pull/124779) 提供同类接入异常的背景；查询时 PR 未合并。现场具体断连源仍未知，不把客户端断连场景推断当作现场抓包结论。

## 3. 总体决策

采用三个互相独立的保护层：

| 层 | 职责 | 不承担的职责 |
| --- | --- | --- |
| Windows 接入适配 | 丢弃失败的单次 accept，继续接收合法新连接 | 不重放业务请求，不管理模型和进程 |
| Python Supervisor | 持续探测、状态发布、串行受控恢复 | 不参与每帧调用，不读写图片和消息页 |
| 桌面启动器 | 持续展示真实状态、提供人工重试与退出 | 不与 Supervisor 同时重启一套服务，不接管外部进程 |

常见 WinError 64 应在第一层消化，不触发模型重载或整栈重启。后两层处理第一层无法恢复、事件循环卡住、进程退出及依赖失效等异常。

## 4. Windows 接入适配

### 4.1 实现位置与接入

接入适配位于 `backend/service/infrastructure/http/windows_event_loop.py`。通过 Uvicorn 自定义 loop factory 在 Windows backend-service 进程中选择；不修改 Python 安装目录，不全局 monkey patch asyncio，不改变训练、转换、daemon 或其他进程的循环策略。

首选实现是局部 Proactor/accept 适配：在单次 accept 内部处理已确认的连接中断，外层服务 accept future 只有拿到有效连接才成功完成。不能仅在 `_start_serving` 外面捕获异常，因为标准库内部可能已经关闭监听；也不能只给 exception handler 增加日志。

这部分涉及 CPython 私有接口，必须隔离、保留必要来源说明，建立已验证的 Python/Uvicorn 版本矩阵。第一步技术验证若无法证明 overlapped I/O、取消和连接关闭正确，就停止该实现分支，不直接复制上游未合并 PR 或扩大补丁范围。生产兼容性检查应拒绝未验证组合进入发行；开发诊断可以明确选择原生循环，但不能静默回退后宣称修复生效。

Linux 保持现有循环；Windows reload 与非 reload 分别记录实际循环类型。不能把 reload 模式测试通过当作生产 Proactor 修复通过。

### 4.2 accept 处理规则

- 第一版只处理已复现的 WinError 64；其他错误进入已有异常/故障路径。新增错误码必须附带独立证据与测试。
- 失败的新连接 socket 必须关闭；监听 socket 保持有效；关闭 socket 与未完成 overlapped 操作的先后关系遵守当前 CPython/Windows 完成回调契约。
- 不能把无效的 `(connection, address)` 当作成功返回，也不能调用失败后的 `getpeername()` 掩盖原错误。
- 正常 stop/cancel 是终止信号，不视为需要重新 accept 的网络错误。关闭期间不创建新连接、不重新挂接 accept。
- 同一个监听最多一个待处理 accept 和一个必要的重试定时器；没有递归重试、无界 Task 或线程队列。
- 正常成功路径不加入 sleep、逐请求磁盘写入或进程检查。错误重试先让出事件循环；连续错误采用有上限的退避，避免异常风暴占满 CPU。
- 所有 future 异常必须被消费；失败 socket、overlapped、定时器和 future 在成功、错误、取消、loop.close 四条路径均有明确归属。
- 仅保留有界计数与最后错误分类；错误日志限频，不记录请求内容和凭据。

第一版建议的错误退避为连续错误 8 次后从 1 ms 递增，上限 100 ms；成功 accept 清零。该值属于待验证的内部策略，不是生产性能承诺。持续错误由外部接入探测触发不可用判定，不能仅因错误总次数多而杀掉仍能正常服务的实例。

### 4.3 备选方案的处理

| 方案 | 决定 |
| --- | --- |
| 直接升级 Python | 只有包含已验证修复的版本才可采用；不能根据版本号猜测已修复 |
| 全局切换 SelectorEventLoop | 不作为默认方案，连接规模及子进程能力需另行验证 |
| 引入第三方事件循环 | 后续备选，需要 Windows x64 wheel、离线分发、依赖和性能验证，不与本次最小修复同时引入 |
| 吞掉所有 OSError | 禁止，可能返回无效连接或隐藏资源故障 |
| 发现错误就重启整个服务 | 仅作为持续不可用的最后恢复手段，不作为正常断连处理 |

## 5. 持续接入探测

### 5.1 轻量端点

新增版本化端点 `GET /api/v1/system/liveness`，用独立异步 handler 返回小型固定 JSON：协议标识、服务实例启动 ID、PID、当前启动/排空阶段。数据来自进程内状态，不查询数据库、Broker、模型、队列或磁盘，不申请线程池 worker。

启动 ID 每次真实 service 子进程启动重新生成，不能等同于 PID；Supervisor 将响应身份与其持有的进程树、创建时间和应用根核对。该 ID 用于防止误认实例，不是认证凭据。端点放在 API router 内，必须先于 SPA fallback。

纯 liveness 只证明新连接可被 HTTP 事件循环处理，不表示全部业务依赖就绪。启动完成继续检查既有必要组件；将原来的 `<500` 判断改为严格的状态码、JSON 格式与对应阶段验证，拒绝 HTML、重定向、401/403 和错误实例。

### 5.2 探测方式与初始参数

探测在 Supervisor 的单个后台任务中执行，主监督循环只读取有界最新结果，不被网络等待阻塞。使用 loopback、禁用系统代理、不跟随重定向、限制响应大小；**每轮新建 TCP 连接并关闭，禁止连接池/Keep-Alive 复用**。否则监听丢失后旧连接仍可响应，监测会误判。

建议默认值如下，均须经过真实负载校准：

| 参数 | 初始值 | 含义 |
| --- | --- | --- |
| 探测间隔 | 2 秒 | 单次探测未结束时不发下一次 |
| 单次总超时 | 1 秒 | 连接与读取合计受限，不是分别累加 |
| 最大响应 | 4 KiB | 超出即判协议异常，不能整页读入 |
| 连续失败阈值 | 3 次 | 首次失败只标记 degraded |
| 恢复成功阈值 | 2 次 | 同一实例连续成功后清除短暂故障 |
| 超时型故障确认 | 至少持续 30 秒 | 区分短时忙与持续无响应，期间继续探测 |
| 自动恢复预算 | 10 分钟内最多 3 次 | 超出后停止自动尝试并明确失败 |

启动沿用现有 profile 的启动超时和组件就绪顺序，启动期不使用运行期失败阈值。正常停止立即取消探测与恢复，不因停止导致的端口消失拉起服务。

低频探测请求如需要避免 access log 噪声，仅对这个精确路径实施日志过滤，保留失败记录和其他请求日志。

## 6. 判定与恢复状态机

运行状态：`starting → running → degraded → recovering → running`；不可恢复或预算耗尽进入 `failed`；任意阶段的人工停止优先进入 `stopping → stopped`。

| 观察 | 动作 |
| --- | --- |
| 单次超时/异常响应 | degraded，继续探测，不重启 |
| 连续失败且确认监听已消失，进程身份仍属本次栈 | 标记接入失败，进入恢复协调 |
| 监听存在但持续超时 | 保留 degraded 至确认窗口；记录依赖/负载状态，按显式策略决定恢复，不按一次慢响应强杀 |
| 端口由其他进程占用 | failed；禁止杀占用者、接管或反复尝试绑定 |
| 本次 service 子进程退出 | 按明确异常分类进入同一恢复协调；配置、迁移、文件完整性错误直接 failed |
| 子进程身份、owner 或锁状态无法确认 | failed，保留诊断，不执行猜测性清理 |
| 达到恢复预算 | failed，停止自动重试，允许显式人工重试 |

恢复只能有一个 owner 和一个进行中的 generation，worker 原有单 Profile 恢复在整栈恢复期间暂停。计时使用 monotonic clock，状态写入采用现有原子替换与锁；不在每帧流程中记录监测状态。

### 6.1 第一版的恢复单元

第一版以 Supervisor 已拥有的完整依赖栈为恢复单元，不能只更换 backend 而默认保留旧 Broker/daemon/Workflow consumer。这样会产生可见的业务中断和模型预热时间，不能描述为无损切换。

自动恢复必须以如下恢复流程和任务分类验收通过为前提；在未通过前，监听永久丢失的兜底行为是明确 failed 和受控停止，不开启未经验证的自动重启。普通 WinError 64 由接入适配处理，通常不会进入此流程。

### 6.2 恢复步骤

1. 原子登记故障原因、当前 generation、受管进程身份和恢复次数；停止本 Supervisor 的其他恢复动作。
2. 停止 Runtime/Trigger 和任务执行器接收新工作；使用既有控制接口，必要时补充进程级排空接口。共享内存/ZeroMQ 入口同样需要停止接收，不能只关闭 HTTP。
3. 在限定时间内等待已接收工作结束，持续响应人工停止。事件循环已卡住时不能无限等待服务端排空确认；期限到达按任务分类处理。
4. 按现有依赖的反向顺序关闭 consumer、worker、daemon，最后关闭 service/Broker。每一步重验 PID、创建时间、路径与祖先链。当前 `_stop_component` 的强制进程树终止只作为到期兜底，不能把它称为优雅排空。
5. 验证本次拥有的子孙进程已退出，owner/guard 已按既有协议释放。存在 `close_blocked`、外部 SDK 仍持有 view 或身份不明时，不删除 mmap/guard、不伪造释放、不继续创建第二个 owner。
6. 取得既有单实例锁并按正常启动顺序创建下一代：service/Broker、daemon、同一 active topology 的 worker。每一步复用原就绪门禁；不跳过初始化或每次重新迁移数据库。
7. 只恢复持久化 desired state 为运行的部署、Runtime 和 Trigger。完成依赖加载/必要预热与身份核对后开放新请求；手工停止的资源不自动启动。
8. 新连接 probe 连续成功、依赖就绪且旧 generation 不再活动后，发布 running。失败进入有界退避；清理未完成前不能开始下一次恢复。

建议恢复退避为 2、5、15 秒，计数按固定时间窗口保留，短暂成功不能清零导致无限重启。人工停止优先级高于退避和重启。

## 7. 在途业务与共享内存语义

| 工作类型 | 处理原则 |
| --- | --- |
| 尚未接收的 HTTP/Trigger 请求 | 明确不可用或连接失败，不隐式排队 |
| 已接收的同步推理/Workflow | 尽力完成；无法确认结果时客户端看到连接中断/既有超时，不伪造成功，不自动重放 |
| 已持久化但未 claim 的任务 | 保留队列/outbox，下一代按原协议 claim |
| 已 claim 的异步任务 | 用既有 attempt/lease 恢复规则判定；仅原契约允许的幂等工作可重试，旧 attempt 不得覆盖新 attempt 终态 |
| 训练/转换中的长任务 | 先排空；中断需记录失败或明确可恢复 checkpoint。不能保证从原执行位置无缝继续 |
| 有外部副作用的自定义节点 | 保留结果不确定事实，禁止自动重放；业务侧按既有幂等键/查询契约处理 |
| 已交付、SDK 尚持有的共享内存结果 | 遵守 reader guard/view 与 owner 关闭顺序；不能为追求重启速度回收仍被引用的内存 |

Broker epoch、descriptor generation、local-message owner 是不同身份，按各自现有协议更新，不合并成一个自造 epoch。旧引用在新 owner 下必须被拒绝；SDK 在下一次合法调用重新发现服务及 locator，不能长期复用旧 mmap 身份。

不新增像素复制、不修改 zero-copy 交付、ACK 顺序、allocator、mailbox layout、Training Telemetry 布局或训练指标上报频率。恢复路径若暴露现有协议缺口，单独修复并验证，不能在 HTTP 健康检查中增加补偿写入。

## 8. 桌面启动器和状态契约

- 成功连接后保留低频、可取消的观察任务；退出时先取消并等待观察结束，防止退出期间自动重连。
- Python Supervisor 是恢复唯一执行者，桌面只观察状态、展示故障和发送显式重试/停止意图。
- `Starting` 仅表示首次启动；已运行过的实例失去监听，应显示不可用/恢复中，不能无限显示启动中。
- 观察外部服务时保持 observe-only，不因探测失败启动另一套或停止外部进程。
- 恢复后只恢复页面连接；保留本地启动页设置，不调用 Workflow 执行接口，不自动提交预览表单。页面有未保存修改时不能通过强制导航丢弃。

若新增 `degraded/recovering` 及 generation 等状态，显式升级本地启动器状态文档版本，并同步 Python writer、.NET reader、测试与发行资源。0.1.6 旧状态文档保留只读诊断兼容；未知版本明确报错。状态文件是临时运行事实，不做数据库 migration，不把旧 running 文件当作活进程证据。

新增 liveness 是 `/api/v1` 下的独立接口，补充响应模型与接口说明；不修改既有 health 字段含义。现有 API 404/SPA 边界问题应作为小而独立的修复提交，不让它干扰 probe 的响应判定。

## 9. 实现顺序与文件范围

| 阶段 | 实现内容 | 主要位置 | 完成条件 |
| --- | --- | --- | --- |
| 1 | 固化故障回归与版本基线 | `tests/`；发行验证 | 原始运行时稳定复现监听丢失，记录实际 loop/Python/Uvicorn |
| 2 | Windows accept 局部适配及 loop factory | `backend/service/infrastructure/http/`；service launcher | WinError 64 后同一监听接受正常请求；取消/关闭无泄漏 |
| 3 | 轻量 liveness、严格就绪校验、后台 probe | system routes；full launcher；独立 monitor 模块 | 新连接检测、身份核对、无假阳性，不阻塞主监督循环 |
| 4 | 恢复状态机、任务分类与资源排空 | full launcher；现有 runtime 控制边界 | 有限恢复、单 owner、无重复执行；未知状态停止恢复 |
| 5 | 桌面持续观察及状态版本 | Launcher Core/Infrastructure/Desktop | 不停留虚假 starting/running，退出/人工重试竞态通过 |
| 6 | CPU/NVIDIA 发行验证及真实业务回归 | release assembly/validation；SDK；验收记录 | 最终目标 bundled 环境通过，真实模型/触发结果一致 |
| 7 | 受控性能和 24 小时运行 | 隔离目标发行实例 | 既有尾延迟门禁、资源稳定、故障恢复通过 |

测试先于对应修复建立；每阶段只运行相关验证，随后进入下一阶段。代码提交按接入、监督、恢复、桌面、发行验收拆分，保持可审阅和回滚。新增模块不得把全部逻辑继续堆入 full launcher 单文件。

## 10. 验证矩阵

### 接入层

- WinError 64 在异步完成和可触发的同步启动错误路径；下一条健康请求仍能成功。
- 同一监听反复失败/成功交错；新失败 socket 全部关闭，监听句柄不变。
- 未知错误不吞掉；取消中的 accept、不完成的 overlapped、loop.close 和 listener.close 无重启 accept、未消费异常或句柄泄漏。
- 多监听、IPv4/实际使用的 IPv6、WebSocket，以及实际 profile 使用的连接配置。
- 正常 HTTP keep-alive 与频繁短连接并发；既有 WebSocket/Trigger 会话不因无关客户端断开而断开。

### Supervisor 与启动器

- 监听消失但进程存活；保留旧 Keep-Alive 可响应，必须仍判新连接失败。
- 端口存在但应用循环阻塞；短暂超时后恢复，不能误杀；持续阻塞按窗口处理。
- 200 HTML、重定向、超大响应、错误启动 ID、PID 复用、其他进程占端口均不能认作就绪。
- 启动中模型加载、worker 自身重启、整栈恢复、人工停止、恢复中退出、恢复预算耗尽。
- 桌面 observe-only、连接成功后失联、恢复成功后再次失联；只有一套恢复任务，退出后没有迟到的导航或重启。

### 数据面与业务

- 真实 YOLO11 分类图片 → Deployment → daemon → Workflow Runtime → HTTP/ZeroMQ/共享内存 → .NET SDK → app-mode，同步/异步分别覆盖。
- 故障发生在接收前、接收后、执行中、结果发布前、响应交付后/ACK 前；核对关联 ID、终态与资源归属。
- SDK 持有共享内存 view、过期引用、旧 epoch、异常退出、重连；页/descriptor/lease 守恒，不能靠删除 guard 恢复。
- 任务 outbox/claim/attempt、训练 checkpoint、外部副作用节点使用受控接收端，验证重复执行计数为零或符合既有明确重试契约。

### 性能与长稳

先固定 target profile、模型、图像、预热、并发和 UI 预览客户端数；修复前后交错至少 5 轮稳态对照。单独记录正常接入开销、HTTP P95/P99、ZeroMQ/共享内存 P95/P99、吞吐、CPU、private bytes、句柄、页和租约趋势。测试资源不可与全量前端编译等负载混跑。

保持 [本机消息通道门禁](../../development/local-message-channel-implementation.md) 的原有阈值；历史 P99 失败不能因本次接入修复而自动关闭。低频 probe 与异常路径原则上不接触每帧热路径，但“没有性能影响”仍必须由测量支持。

真实最终发行环境运行至少 24 小时，混合正常业务、客户端断连和受控故障。单次 accept 断连应零整栈重启；持续不可用应在配置检测窗口内被识别；总恢复时长包含排空、停止、重新加载和预热，按目标机器实际测量，不承诺固定数秒。

## 11. 发布、回滚与放行

开发验证使用 `conda activate amvision`；发行使用同目录 Python 和已验证 Uvicorn，两个环境独立记录。不要手工修改发行目录源码或标准库；由源目录重新 `assemble-release --profile-id <目标 profile>`。

新增代码和状态 schema 作为同一发行单元交付；旧 launcher 与新 Supervisor 不混装。回滚前停止并确认清理本次栈，恢复上一个完整发行单元，不复制旧 runtime-state、PID 或 owner 信息。当前设计不改数据库结构和模型文件。

放行需要：接入异常回归通过、监督与受控恢复通过、真实业务正确性通过、性能门禁通过、长稳通过、退出/回滚演练通过。未验证的版本/设备组合不随已通过 CPU profile 自动放行。暂未完成完整自动恢复时，可保留明确失败与人工恢复，但不能宣称完整方案已实现。
