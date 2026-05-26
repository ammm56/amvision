# Workflow Runtime 第一阶段实现清单

## 文档目的

本文档只收口 workflow runtime 第一阶段真正要落代码的实现边界。

本文档只保留三类内容：状态机、snapshot 规则、worker 消息合同。

第一阶段不展开 AI 控制面、不展开异步 runs、不保留旧 execute 兼容入口。

## 第一阶段范围

- 删除旧的 workflow application execute 路由，不再保留兼容模式。
- 新增 WorkflowPreviewRun、WorkflowAppRuntime、WorkflowRun 三类资源。
- 编辑态试跑采用一请求一子进程。
- 已发布应用运行采用单 runtime 单实例单进程。
- 长期运行只支持 start、stop、health、sync invoke。
- WorkflowRun 在第一阶段只承接 sync invoke，不提供异步 runs 创建接口。

## 状态机表

### WorkflowPreviewRun

| 当前状态 | 允许迁移 | 超时迁移 | 失败迁移 | 取消迁移 |
| --- | --- | --- | --- | --- |
| created | running | 无 | failed | 无 |
| running | succeeded、failed、timed_out | running -> timed_out | running -> failed | 无 |
| succeeded | 无 | 无 | 无 | 无 |
| failed | 无 | 无 | 无 | 无 |
| timed_out | 无 | 无 | 无 | 无 |

状态约束：

- 第一阶段不开放 preview cancel 接口，因此没有外部 cancel 迁移。
- preview child process 退出后，状态必须稳定在 succeeded、failed 或 timed_out 之一。

### WorkflowAppRuntime

| 当前状态 | 允许迁移 | 超时迁移 | 失败迁移 | 取消迁移 |
| --- | --- | --- | --- | --- |
| stopped | starting | 无 | 无 | 无 |
| starting | running、failed、stopped | starting -> failed | starting -> failed | 无 |
| running | stopping、failed | invoke 超时不改变 runtime 状态 | worker 退出或健康检查失败时 running -> failed | 无 |
| stopping | stopped、failed | stopping -> failed | stopping -> failed | 无 |
| failed | starting、stopped | 无 | failed 保持不变 | 无 |

状态约束：

- start 只允许把 stopped 或 failed 拉回 starting。
- stop 只允许把 starting 或 running 切到 stopping，然后落到 stopped。
- 第一阶段单 runtime 只维护一个 instance，不做 scale、restart 或 instances 公开接口。

### WorkflowRun

| 当前状态 | 允许迁移 | 超时迁移 | 失败迁移 | 取消迁移 |
| --- | --- | --- | --- | --- |
| created | dispatching | 无 | failed | 无 |
| dispatching | running、failed | dispatching -> timed_out | dispatching -> failed | 无 |
| running | succeeded、failed、timed_out | running -> timed_out | running -> failed | 无 |
| succeeded | 无 | 无 | 无 | 无 |
| failed | 无 | 无 | 无 | 无 |
| timed_out | 无 | 无 | 无 | 无 |

状态约束：

- 第一阶段只支持 sync invoke，因此 WorkflowRun 仍需要完整记录，但不会进入异步队列对外暴露 queued 状态。
- invoke 请求返回前，WorkflowRun 必须已经落到 succeeded、failed 或 timed_out。

## Snapshot 规则

### 固定原则

- WorkflowPreviewRun 和 WorkflowAppRuntime 都只能执行 snapshot，不直接执行可变 application 保存文件。
- snapshot 一旦创建，后续执行只能引用 snapshot object key，不再回读 application_id 对应的最新保存内容。
- 同一个 WorkflowRun 必须同时固定 application snapshot 和 template snapshot。

### WorkflowPreviewRun snapshot

- 如果请求提供 inline application 或 inline template，backend-service 先把 JSON 写成临时 snapshot 文件，再拉起 preview child process。
- 如果请求提供 application_ref，backend-service 先读取已保存 application，再把 application 与其引用 template 固定为 preview snapshot。
- preview snapshot 使用短期 object key，允许按 retention_until 清理。

建议 object key：

- workflows/runtime/preview-runs/{preview_run_id}/application.snapshot.json
- workflows/runtime/preview-runs/{preview_run_id}/template.snapshot.json

### WorkflowAppRuntime snapshot

- 创建 runtime 时，backend-service 读取已保存 application 与 template，并复制为 runtime 自己的固定 snapshot。
- runtime 后续 start、health、invoke 都只依赖 runtime 记录上的 snapshot object key。
- 后续再次保存同名 application，不影响已创建 runtime。

建议 object key：

- workflows/runtime/app-runtimes/{workflow_runtime_id}/application.snapshot.json
- workflows/runtime/app-runtimes/{workflow_runtime_id}/template.snapshot.json

### fingerprint 规则

- runtime 启动时计算 loaded_snapshot_fingerprint。
- fingerprint 建议由 application snapshot JSON 和 template snapshot JSON 的稳定序列化结果生成。
- health 响应至少返回当前 process 是否加载了 runtime 记录声明的 fingerprint。

## Worker 消息合同

第一阶段只定义单实例同步链路，不定义异步 runs 队列对外合同。

### runtime worker 控制队列

#### start-runtime

```json
{
  "message_type": "start-runtime",
  "message_id": "msg-1",
  "workflow_runtime_id": "runtime-1",
  "application_snapshot_object_key": "workflows/runtime/app-runtimes/runtime-1/application.snapshot.json",
  "template_snapshot_object_key": "workflows/runtime/app-runtimes/runtime-1/template.snapshot.json",
  "request_timeout_seconds": 60,
  "created_at": "2026-05-08T12:00:00Z"
}
```

#### stop-runtime

```json
{
  "message_type": "stop-runtime",
  "message_id": "msg-2",
  "workflow_runtime_id": "runtime-1",
  "reason": "api-stop",
  "created_at": "2026-05-08T12:01:00Z"
}
```

#### health-check

```json
{
  "message_type": "health-check",
  "message_id": "msg-3",
  "workflow_runtime_id": "runtime-1",
  "created_at": "2026-05-08T12:02:00Z"
}
```

### runtime worker 执行队列

#### invoke-run

```json
{
  "message_type": "invoke-run",
  "message_id": "msg-4",
  "workflow_runtime_id": "runtime-1",
  "workflow_run_id": "run-1",
  "requested_timeout_seconds": 60,
  "input_bindings": {
    "request_image": {
      "object_key": "projects/project-1/files/demo/input/sample-1.jpg"
    }
  },
  "execution_metadata": {
    "trigger_source": "sync-api"
  },
  "created_at": "2026-05-08T12:03:00Z"
}
```

### worker 响应合同

#### runtime-state

```json
{
  "message_type": "runtime-state",
  "message_id": "msg-1",
  "workflow_runtime_id": "runtime-1",
  "observed_state": "running",
  "process_id": 12345,
  "heartbeat_at": "2026-05-08T12:00:01Z",
  "loaded_snapshot_fingerprint": "sha256:example"
}
```

#### run-result

```json
{
  "message_type": "run-result",
  "message_id": "msg-4",
  "workflow_runtime_id": "runtime-1",
  "workflow_run_id": "run-1",
  "state": "succeeded",
  "outputs": {},
  "template_outputs": {},
  "node_records": [],
  "error_message": null,
  "finished_at": "2026-05-08T12:03:02Z"
}
```

#### worker-error

```json
{
  "message_type": "worker-error",
  "message_id": "msg-4",
  "workflow_runtime_id": "runtime-1",
  "workflow_run_id": "run-1",
  "state": "failed",
  "error_message": "workflow runtime worker 执行失败",
  "error_details": {
    "error_type": "ServiceConfigurationError"
  },
  "finished_at": "2026-05-08T12:03:02Z"
}
```

## Phase1 Implementation Checklist

1. 删除旧的 workflow application execute 路由和对应公开文档。
2. 新增 WorkflowPreviewRun、WorkflowAppRuntime、WorkflowRun 的 contracts、domain、ORM、repository。
3. 新增共享 SnapshotExecutionService，统一加载 snapshot 并执行图。
4. preview-runs create 路由固定 snapshot 后拉起一次性 child process，并回写 WorkflowPreviewRun。
5. app-runtimes create 路由固定 snapshot 并创建 WorkflowAppRuntime。
6. workflow-runtime-worker 只支持单 runtime 单实例 start、stop、health、sync invoke。
7. invoke 路由先创建 WorkflowRun，再通过 worker IPC 执行，并同步等待结束。
8. 第一阶段不提供 async runs、cancel、events、restart、instances，也不提供 execution policy CRUD。