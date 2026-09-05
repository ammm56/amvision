# Runtime 预览监视

## 范围与入口

Runtime 监视显示实际发布图中 Image、Value、Table、Gallery Preview 节点的输出。当前在 **Worker 完成本次执行及资源清理后** 发送显示结果，不提供逐节点实时进度，不创建 Preview Run，不开启 full record，也不改变 HTTP、SDK 或 Trigger 的业务返回。

在 Workflow App 详情的 Runtime 区域选择实例，点击“Runtime 监视”，进入 `/workflows/runtime/{workflow_runtime_id}/monitor`。画布可平移、缩放和打开图片/JSON/表格查看器；节点、参数和公开输入输出只读。说明节点复用安全 Markdown 渲染。打开、刷新或关闭页面不执行 Workflow，不启停 Runtime/Trigger。

页面初始等待下一次实际执行，没有历史回放。停止态只显示所选发布图；重启、切版或断线后点击“刷新”重新取得实际快照并连接。断开连接后保留的已完成画面标记为断开状态，不代表当前生产数据。

轻量 App Mode、输入表单、显示选择及节点执行中更新尚未实现，实施顺序见[实施基线](../development/workflow-runtime-preview-and-app-mode.md)。

## 快照与连接

1. `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/preview-snapshot`，需要现有 `workflows:read` 和 Project 可见范围。
2. 读取返回的 `application`、`template`，它们来自实际 active revision 对应的发布版本，不能替换成编辑草稿。未激活时使用 desired revision，并通过 `active`、`observed_state` 区分。
3. 连接 `/ws/v1/workflows/app-runtimes/preview`，query 参数为快照中的 `workflow_runtime_id`、`workflow_runtime_revision_id`、`runtime_generation`、`worker_instance_id`。

快照格式为 `amvision.workflow-runtime-preview-snapshot.v1`，还包含 `workflow_app_version_id`、`snapshot_fingerprint`、`project_id`、`application_id`、`display_name`。重复获取快照不启动 Runtime。

WebSocket 使用现有鉴权：第三方客户端可传 `Authorization: Bearer <token>`；浏览器沿用已启用的 query token 能力。不得把 token 写入显示内容或文档示例。身份失效或没有权限拒绝连接；worker 身份变化、停止或连接名额用尽拒绝本次订阅，不启动新 worker。

## 显示消息 v1

连接成功时先返回：

```json
{"format_id":"amvision.workflow-runtime-preview.v1","state":"connected"}
```

之后仅推送订阅期间发生的执行完成消息：

```json
{
  "format_id": "amvision.workflow-runtime-preview.v1",
  "workflow_runtime_id": "workflow-runtime-<uuid>",
  "workflow_runtime_revision_id": "workflow-runtime-revision-<uuid>",
  "workflow_app_version_id": "workflow-app-version-<uuid>",
  "runtime_generation": 1,
  "worker_instance_id": "<actual-worker-id>",
  "snapshot_fingerprint": "sha256:<fingerprint>",
  "project_id": "project-1",
  "application_id": "workflow-app-<timestamp>",
  "workflow_run_id": "workflow-run-<uuid>",
  "sequence": 12,
  "state": "succeeded",
  "error_message": null,
  "display_error": null,
  "finished_at": "2026-09-04T12:00:00+00:00",
  "displays": [
    {
      "node_id": "json_preview",
      "node_type_id": "core.io.value-preview",
      "output_port": "body",
      "invocation_id": "json_preview",
      "duration_ms": 0.1,
      "payload": {"type": "value-preview", "value": {"passed": false, "count": 0}}
    }
  ]
}
```

- `state` 是 Worker 本次执行及清理结果，`succeeded` 或 `failed`；不是产品合格判定，也不是控制面的持久化/Trigger ACK 回执。业务结果仍以原调用协议为准。强制终止 worker 时可能只有连接断开，没有终态显示消息，不能补造成功或失败帧。
- `sequence` 在同一 worker 内递增，允许跳号。客户端同时核对 Runtime、revision、版本、generation、worker、指纹和 sequence，不能只按 run 到达顺序更新。
- `displays` 是本次完整显示集合，替换旧画面；未执行或失败前未到达的节点没有条目，不能沿用上次值。失败前已完成的预览仍可显示。
- 按 `node_id + output_port` 关联，不依赖名称、位置或列表顺序。ForEach 的 `invocation_id` 标识实际迭代；同节点同端口只保留本次最后完成的一次预览。完整批次应由 Workflow 聚合后交给 Gallery/Table。
- 仅采集声明 `ui.preview` 的节点端口，支持 `image-preview`、`value-preview`、`table-preview`、`gallery-preview`。不收集任意节点的全部输入输出。自定义节点复用这些类型和能力声明即可。
- `payload` 复用既有预览类型。图片沿用 inline Base64 或实际可读的 ObjectStore 引用；不在 mmap/LocalBuffer lease 释放后再读取原始图片。Preview Run 专属临时路径、失效引用、本地磁盘路径不能冒充可公开读取的 Runtime 资源。
- 图片及图库显示中不提供修改节点参数的 interaction；普通 JSON 中的业务字段不按名称猜测或执行脚本。

## 客户端接收确认与丢帧规则

客户端处理完一个执行消息后发送一条文本消息 `ready`。`connected` 不需要确认。`ready` 仅表示显示接收方可接收下一帧，不是执行命令，也不是业务 ACK。

每个连接最多一份在途显示；发送或等待 `ready` 期间产生的新帧直接略过，没有“下一帧队列”。首次订阅、断开后重连和刷新均不补发历史。超过 30 秒未完成发送或处理确认则关闭该显示连接，业务继续执行。该超时只约束单个显示连接，不进入 Workflow、HTTP、SDK 或 Trigger 的响应等待。页面不能依赖这一观察通道逐条消费所有生产结果。

## 容量和生命周期

| 边界 | 当前限制 |
| --- | --- |
| 单个 UTF-8 JSON 消息 | 最大 64 MiB，包含 Base64 和消息结构 |
| 捕获 JSON 结构 | 深度最大 32，访问值/键数量最大 100,000 |
| 单 Runtime 订阅连接 | 最多 16 个 |
| Worker 在途副本 | 最多一份正在收集或发送的 Run；忙时不捕获新显示 |
| Worker 到 backend 发送 | 独立 socket，2 秒发送超时；不使用业务响应/节点超时控制通道 |
| 服务端显示持久化 | 无数据库记录、无历史缓存、无重放 |

捕获预算按本次累计复制工作计数；循环多次更新同一端口也计入预算。超出限制会清空本次 `displays` 并给出 `display_error`，不会改变业务执行结果。最终编码后再次核对 64 MiB 长度。容量限制不是进程内存承诺：结构复制、编码/解码、浏览器图片解码和不同客户端的网络在途数据仍有额外峰值。

每个 Runtime 固定增加独立 socket 对、共享观察信号和 backend 接收线程；Worker 发送线程在首次观察执行时创建。无页面时不捕获、不编码和发送新增显示副本，但图中原有 Preview 节点仍按正常逻辑执行。资源在 Runtime 停止或换代时释放，不为每次调用创建线程。显示通道异常只终止观察能力，不改变 Runtime 业务状态。

浏览器只保存当前画面；替换、刷新或离开时释放 Object URL、监听器和在途图片请求，旧异步回调不能恢复已关闭的画面。相同图片源不重复读取。慢页面不会延长核心图片 lease。

逻辑隔离不等于零 CPU、内存或网络成本。大图 JSON 编码、WebSocket 发送仍与服务其他工作共享机器资源。性能门禁必须比较关闭/开启页面的原调用耗时和下一次调用延迟，不能只测页面显示速度。

## 可复现验证入口

开发环境先执行 `conda activate amvision`：

- `tests/test_workflow_runtime_preview.py`：有界捕获、失败前结果、只接下一帧、连接上限、线程/socket 释放。
- `tests/test_workflow_runtime_preview_api.py`：实际 spawn Worker，sync/async、none/minimal/full、临时异步及失败；none 不产生 WorkflowRun 记录。
- `python -m tests.integration.workflow_runtime_preview_validation --runtime-id <专用验证-runtime-id> --cycles 250`：实际图片/JSON 的无页面与有页面交替对照，输出延迟、Private/RSS 和原生句柄。
- `python -m tests.integration.workflow_runtime_preview_validation --runtime-id <专用验证-runtime-id> --soak-seconds 3600 --interval-seconds 3 --subscribers 16 --output .tmp/runtime-preview-soak-1h.json`：一小时、16 个大图客户端、顺序调用的稳定性门禁；调用在上一次完成后等待 3 秒，不追赶或补发。
- 同一工具的 `--validate-triggers`：只允许专用验证 App，创建或复用明确停用的测试 ZeroMQ/本机共享内存 Trigger，核对业务与显示身份，结束后停用测试 Trigger。
- 同一工具的 `--validate-directory-trigger`：在临时目录创建实际 Directory Trigger，核对事件、样本、Runtime 结果与显示身份，结束后停用并删除测试 Trigger，同时删除临时目录。
- `frontend/web-ui/e2e/runtime-preview.spec.ts`：需显式传入验证 App/Runtime ID；实际页面、图片查看器、只读边界、刷新不执行、桌面/窄视口及浏览器短测。

2026-09-05 的一小时实测共顺序调用 1,115 次，16 个客户端收到 17,840/17,840 个 2,628,481-byte 消息，失败、丢帧和客户端错误均为 0；Runtime Worker 原生句柄净增 0。调用耗时 p50 101.143 ms、p95 1,775.461 ms、p99 2,048.877 ms、最大 4,775.529 ms。相同内容和节拍的单客户端 3 分钟对照为 58/58 成功，p50 94.801 ms、p95 230.403 ms、p99 236.021 ms、最大 247.644 ms，资源无增长。这把尾延迟定位到同一 Backend 上的 16 路大图发送竞争，不是单客户端显示或 Runtime Worker 泄漏。资源释放门禁通过，但 16 个大图客户端下的尾延迟门禁未通过，因此当前不据此推进 App Mode 或宣称工业长期认证。

实际生产 Workflow 的 HTTP、ZeroMQ、本机共享内存 .NET SDK 调用均已验证成功，ZeroMQ 与本机共享内存业务结果一致；临时 Directory Trigger 也已验证能触发同一显示链路。另以开发环境 4 个实际 YOLO11 classification Deployment 各执行 20 次有界同步调用，每个 Deployment 同时发起 2 个请求；4 组均由 `instance-0`/`instance-1` 各完成 10 次，错误计数与原生句柄增量均为 0。该项只验证不同实际模型的双实例路由、正确性与请求后资源回落，不把 4 个模型同时承压的 HTTP base64 延迟作为单 Workflow 的生产性能指标，也不代替现场硬件和更长运行周期的独立门禁。
