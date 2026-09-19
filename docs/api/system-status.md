# 视觉服务运行状态

`GET /api/v1/system/status` 用于第三方查询视觉服务是否完成启动并正常运行。每次查询立即返回当前内存快照，不等待业务完成、不等待空闲实例、不自动重试。

## 状态含义

- HTTP `200`、`ready: true`：当前要求运行的资源及其可确定的依赖全部就绪。
- HTTP `503`、`ready: false`：启动未完成、运行故障、状态不可用或正在停止。503 正文仍是正式状态响应。
- HTTP 尚未监听时会连接失败；这与取得一个有效的未就绪响应不同。
- 正在推理、并发满载、长工作流、历史业务失败、NG 检测结果不改变就绪状态。
- 就绪不代表当前有空闲实例，也不保证任意输入的下一次调用必定成功。

```json
{
  "ready": true,
  "state": "ready",
  "instance_id": "当前HTTP进程启动标识",
  "checked_at": "2026-09-18T00:00:00+00:00",
  "summary": {
    "deployments": { "expected": 2, "ready": 2 },
    "runtimes": { "expected": 3, "ready": 3 },
    "triggers": { "expected": 2, "ready": 2 }
  },
  "blockers": []
}
```

示例数量不代表任何现场配置。`deployments` 按部署 id 与 sync/async 模式计数；不是模型实例的空闲数。`summary: null` 表示未取得可信资源清单，不能视作零个资源。`checked_at: null` 表示没有可用的当前观测时间。

`state` 为 `starting`、`ready`、`degraded`、`unavailable`、`stopping`。首次成功前未就绪是 starting；成功后出现组件故障是 degraded；采集失败或过期是 unavailable。`instance_id` 在 HTTP 服务重启后变化。

常用 `blockers[].code`：`initializing`、`status_stale`、`status_collection_failed`、`local_buffer_unavailable`、`inference_unavailable`、`deployment_not_running`、`runtime_not_running`、`model_dependency_unavailable`、`trigger_not_running`、`runtime_dependency_unavailable`、`service_stopping`。原因码描述当前状态，不复制历史业务错误。

## 资源范围与权限

- 模型部署和 Runtime 使用现有 `desired_state=running` 集合；Trigger 使用现有启用集合。不会启动停止的资源，也不要求 App 草稿或 Preview 会话启动。
- 模型必须完成配置要求的全部实例预热，并具有存活的进程和响应线程。
- Runtime 校验当前 active/desired revision、generation、快照指纹、进程及独立心跳。静态部署依赖根据启用节点声明的 `runtime_requirements.deployment_process` 和 `deployment_instance_id` 检查。
- Trigger 必须已启动且绑定 Runtime 可用。动态请求输入、自定义节点内部才确定的外部依赖、图片内容与业务结果不通过状态探测执行或推断。
- 默认摘要与现有 liveness 一样可直接读取，不包含资源 id、名称、路径或业务参数，且不进行每请求数据库鉴权。
- 管理员可以请求 `?details=true`，额外取得 `resources` 列表，包括资源 id、模式和状态。明细沿用现有鉴权；未认证返回 401、非管理员返回 403。高频检查使用默认摘要，避免重复鉴权数据库访问。
- 响应设置 `Cache-Control: no-store`。`/liveness` 和 `/health` 保留原有语义，不能把它们等同于本接口。

## 性能和生命周期

HTTP 路由只读取已序列化的内存 bytes，不获取模型或 Runtime 执行锁，不查询数据库、访问文件、发送 IPC 请求或执行推理。请求数量不改变后台采集频率。

后台约每秒采集一次控制面期望状态和当前观测；不是零延迟的原子跨进程事务。HTTP 快照超过 5 秒无更新时撤销 ready。Runtime 心跳使用该 Runtime 现有超时配置，独立于业务执行时长。

独立 inference daemon 每秒通过已有 LocalMessage EventRing 发布完整状态，后台读取最新一份。状态通道固定保留两份快照，正文容量每份 256 KiB，总计约 512 KiB；不占用推理 Mailbox admission、业务队列或图片 LocalBuffer。其 mmap 文件属于运行时通信文件，不是追加日志。owner、epoch、关闭标记和 5 秒时效校验阻止使用已退出或旧进程的状态；超容量明确返回未就绪，不截断为成功。

这是一条独立状态观察链路，未修改推理、Runtime、Trigger 的 admission、推理算法、生产数据写入或忙碌立即拒绝规则。变化在下一次采集反映；组件启动状态与监控超时共同决定实际故障发现时延。不能将状态接口当作每次业务调用前必须执行的探测。

## .NET SDK

```csharp
// client 复用现有 AMVisionClient 配置；Timeout 是一次 HTTP 请求的超时。
ServiceStatusResponse status = client.GetServiceStatus();
if (status.Ready)
{
    // 按既有方式调用 Runtime、Trigger 或模型。
}

// 异步入口同样只查询一次。
var current = await client.GetServiceStatusAsync(cancellationToken);
```

`AMVisionOperationRunner` 同样提供上述两个方法。同步方法不创建业务队列、轮询器或后台等待任务。503 正式状态返回对象；连接失败、超时、401/403、无效 JSON 和不一致的状态响应分别按现有 SDK 传输/API/JSON 异常处理。不提供 `WaitForServiceReady`。

## 开发和发布

无需数据库迁移、第三方依赖、新端口或 .NET 数据面协议变更。Vue 前端无需改动；离线和 bundled Python 发布方式不变。

更新后必须重启独立 inference daemon；开发 HTTP `--reload` 只会更新 HTTP 进程，不能更新已运行的 daemon。仍使用开发/发布文档原有启动命令。生产通过 `assemble-release` 重建发行包，不能直接手工修改 release 源码。旧 daemon 没有状态通道时接口明确返回未就绪，不能假定正常。

## 当前验证记录（2026-09-18）

- 后端状态、独立通道、daemon 生命周期、部署协调器和 Runtime watchdog 共 53 项回归通过；覆盖过期/关闭、旧 revision、部分实例初始化失败、满载及长任务不误判、公开摘要与管理员明细。
- .NET Framework 4.7.2 x64 编译及契约程序通过；覆盖同步/异步单次请求、有效 503 返回、认证失败、无效或矛盾的状态响应。
- 开发环境旧 daemon 尚未重启时，SDK 连续 1000 次查询全部正常返回未就绪。端到端中位数 0.9633 ms、P99 2.3944 ms，最大 258.3698 ms（包含首请求开销）；该结果仅衡量此次机器环境的状态查询，不代表推理或满载下的性能承诺。
- 新 daemon 的全就绪及真实业务并行验收需在更新后的 daemon 启动后完成；以上结果不替代该项验收。

2026-09-19 补充：更新后的 daemon 已在开发环境验证全就绪，.NET 1000 次查询及真实 Runtime、Trigger、Preview 并行调用通过。审计同时发现并修复采集器提前缓存未初始化节点目录的启动顺序回归，保留状态查询响应长尾及运行版本差异，详见[一周功能验证](../operations/weekly-verification-20260919.md)。
