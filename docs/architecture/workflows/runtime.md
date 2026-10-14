# Workflow Runtime

## 定位

Workflow Runtime 是已发布 Workflow App 的长期运行执行面。它使用稳定的 Runtime id 接受同步调用、异步 Run 和 Trigger 调用，并把每次执行固定到不可变的 App Version、Runtime Revision 与 Worker epoch。

编辑器 Preview 与生产 Runtime 使用同一图执行器、节点目录和图片数据面，但生命周期不同：Preview 由 backend-service 管理内存会话，在独立可复用的 Preview Worker 中执行；生产 Runtime 使用绑定不可变发布版本的独立常驻进程。

## 资源关系

```text
Workflow App draft
  └─ publish -> immutable App Version
       └─ select -> Runtime Revision (generation N)
            └─ start -> Worker instance / epoch
                 └─ invoke -> Workflow Run
                      └─ Trigger Source
```

- **App Version**：不可变发布快照，保存图、模板、节点依赖、公开契约和内容指纹。
- **App Runtime**：稳定调用入口。更新版本时 id 不变。
- **Runtime Revision**：一次版本选择形成的不可变记录；generation 单调递增。
- **Worker instance**：某个 revision 的实际常驻进程实例，使用独立 `worker_instance_id` 防止旧进程状态污染新进程。
- **Workflow Run**：一次调用记录；按记录模式保留必要的结果和追溯字段。
- **Trigger Source**：稳定绑定 Runtime，不直接绑定可变草稿。

版本发布、选择、归档、恢复和回滚语义见 [Workflow App 版本管理](app-versioning.md)。

## Preview 执行

Preview 使用内存会话及 WebSocket 上传输入、提交冻结文档、接收节点进度和结果。每会话最多一条活动执行，并发受 Preview Worker 数量和内存容量约束。核心节点和自定义节点在 Worker 内共享图执行器，不创建逐节点隔离进程。

过程数据保存在内存和操作系统共享内存，不创建 Preview 数据库记录、`events.jsonl` 或磁盘交换结果。显式保存节点仍可写入业务文件。图片以版本化引用进入节点数据面，模型 Deployment 调用继续交给已加载模型的部署进程。

执行期资源在最后一个消费者完成后释放；展示资源在浏览器完整接收并确认后释放，分块 ACK 只用于传输控制。取消先协作终止，必要时终止所属 Preview Worker；确认执行退出后才回收资源及容量。服务重启后旧会话失效，不恢复或自动重跑。

完整协议、页面恢复和资源所有权见 [编辑态 Preview 执行](preview-execution.md) 与 [Workflow Preview Session v1](../../api/workflow-preview-sessions.md)。旧 Preview Run REST/WS 与同步执行路径已删除，不能按旧接口接入。

长期稳定性验收应固定进程和预热基线，观察 Broker 活跃通道、lease、原生句柄及私有内存，并覆盖成功、失败、取消和连接丢失。进程重启后归零或短时成功不代表运行期间没有资源泄漏。

## 生产执行

### Worker 生命周期

Workflow Worker 启动后加载所选 App Version 的不可变快照和节点依赖。只有 startup state、revision id、generation、snapshot fingerprint 与 worker instance id 全部校验成功，进程句柄才会向调用面公开。

start、stop、restart、select-version 和 delete 共享每个 Runtime 的 lifecycle guard；数据库侧仍使用 generation/revision 条件写，覆盖多 API 进程并发。控制动作不引入请求队列、自动重试或轮询。

### 请求固定与 epoch fence

请求开始时固定以下值：

- `workflow_app_version_id`
- `workflow_runtime_revision_id`
- `runtime_generation`
- `snapshot_fingerprint`
- `worker_instance_id`

manager、worker command、worker response、heartbeat 和状态事件均携带这些字段。任何旧 generation、旧 revision 或旧 worker epoch 的响应都会被丢弃，不能回写当前 Runtime。

同步调用继续使用 Runtime 现有的串行 request lock。满载时立即返回明确冲突，不做排队和隐式重试。

### 同步与异步

- **同步调用**：请求等待执行结果；`none`、`minimal`、`full` 控制 Run 持久化开销。
- **异步调用**：先持久化 queued Run，再登记到当前 worker；查询接口读取最终状态和输出。
- **Trigger 调用**：Trigger Source 解析稳定 Runtime，在当前 revision/epoch 上创建 Run。

异步 admission 和需要持久化的同步 dispatch 在 lifecycle guard 内完成，执行阶段不持 guard。`minimal`/`none` 同步调用使用进程内轻量 reservation 阻止运行中删除，不增加数据库写入、队列或重试。

Runtime 存在 queued、dispatching 或 running Run 时，delete/select 等破坏性控制动作返回冲突。同步或异步执行异常会把已持久化 Run 收敛到 failed/cancelled 终态，不遗留永久 dispatching 记录。

## 图片数据面

Workflow 节点统一消费 `image-ref.v1`：

- `memory`：单次执行内的图片句柄；
- `storage`：ObjectStore 相对路径；
- `local-path`：当前主机可读的磁盘绝对路径；
- `buffer`：LocalBufferBroker `BufferRef`；
- `frame`：LocalBufferBroker `FrameRef`。

生产 Runtime、Trigger 和 Preview 都优先通过 LocalBuffer 传递大图片。ObjectStore 用于需要持久化、跨执行复用或对外返回的对象；Base64 只适合小型兼容输入，不是高性能主链路。详见 [高性能图片数据面](../platform/image-data-plane.md) 和 [数据与文件](../platform/data-and-files.md)。

## 健康与恢复

- health 是当前 DB snapshot 与 manager live state 的只读合并，不在同步调用热路径执行整行数据库更新。
- heartbeat 和 observed state 由后台 monitor 通过 revision/generation/worker instance 条件写持久化。
- startup recovery 先恢复 desired Runtime 并等待可用，再恢复 enabled Trigger Source。
- worker 崩溃、超时取消和旧异步回调都使用 epoch fence；旧进程不能停止或标坏新进程。
- 日志按 `YYYYMMDD` 写入当日日志文件，长期运行不会让单个文件无限增长。

## Run 追溯

已持久化 Run 记录固定保存 version、revision、generation、snapshot fingerprint 和 worker instance id。后续切版、回滚或重启不会修改历史 Run 的来源。

`none` 模式不创建完整 Run 记录；`minimal` 只保留控制和状态所需字段；`full` 可保留输入、输出、节点记录和 trace。生产默认应按审计需求选择最低足够级别。

## 实现入口

- Runtime 应用服务：`backend/service/application/workflows/runtime_service.py`
- Worker manager：`backend/service/application/workflows/worker/manager.py`
- Worker process：`backend/service/application/workflows/worker/process.py`
- Runtime 持久化：`backend/service/infrastructure/persistence/workflow_runtime_repository.py`
- Preview 应用服务：`backend/service/application/workflows/preview/session.py`、`preview/pool.py`；独立的编辑态内存会话，不使用正式 Runtime 的持久化
- Trigger 应用服务：`backend/service/application/workflows/trigger_sources/trigger_source_service.py`
- API： [Workflow App Runtime](../../api/workflow-app-runtimes.md)、[Workflow Run](../../api/workflow-runs.md)、[Trigger Source](../../api/workflow-trigger-sources.md)

## 明确边界

- Runtime 不替代训练、转换、验证、部署和模型推理 worker。
- 模型 Batch 节点仍通过已发布 DeploymentInstance 执行；Workflow Runtime 只执行显式 Parallel 图，不把 Batch 改造成跨请求调度、等待队列或自动重试。详细边界见[视觉并行与模型批量节点设计](vision-parallel-and-model-batch.md)。
- Runtime 不做跨主机调度、通用资源编排或自动扩缩容。
- 核心平台不直接内置 PLC、相机或传感器驱动；相关能力由自定义节点提供。
- 不使用逐节点安全沙箱。节点包由使用者显式安装和启用，执行链路以本地工业视觉性能为优先。
- 不把未公开的 Persona、ToolPolicy 或通用 Agent 循环纳入当前 Runtime 契约。
