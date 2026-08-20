# Workflow TriggerSource API

## 用途

WorkflowTriggerSource 把外部协议事件映射为稳定 WorkflowAppRuntime 调用。它只负责接收、规范化、输入绑定、提交和回执，不执行图内图片转换、模型推理或业务规则。

TriggerSource 绑定稳定 `workflow_runtime_id`。Runtime 通过 revision/generation 切换 Workflow App Version 后，TriggerSource id 和外部 endpoint 不变。

## 当前可运行 adapter

| `trigger_kind` | 作用 |
| --- | --- |
| `zeromq-topic` | ZeroMQ multipart/JSON 事件与本机图片高速数据面 |
| `plc-register` | Modbus TCP 寄存器轮询、条件匹配和 Workflow 提交 |
| `directory-poll` | 周期目录扫描、稳定期过滤、checkpoint 和批量提交 |
| `directory-watch` | 本地目录事件监听、稳定期过滤、checkpoint 和受控 polling fallback |

schema 可以识别其他预留 kind，但未注册 adapter 的 TriggerSource 无法 enable，并会返回明确配置错误。未注册类型不能写成已支持。

## 管理接口

```text
POST   /api/v1/workflows/trigger-sources
GET    /api/v1/workflows/trigger-sources?project_id=...&workflow_runtime_id=...&offset=0&limit=100
GET    /api/v1/workflows/trigger-sources/{trigger_source_id}
POST   /api/v1/workflows/trigger-sources/{trigger_source_id}/enable
POST   /api/v1/workflows/trigger-sources/{trigger_source_id}/disable
GET    /api/v1/workflows/trigger-sources/{trigger_source_id}/health
DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}
```

读取需要 `workflows:read`，创建、启停和删除需要 `workflows:write`；所有操作同时校验 Project 可见性。

## 创建请求

```json
{
  "trigger_source_id": "trigger-source-line-1",
  "project_id": "project-1",
  "display_name": "Line 1 image trigger",
  "trigger_kind": "zeromq-topic",
  "workflow_runtime_id": "workflow-runtime-line-1",
  "submit_mode": "sync",
  "enabled": false,
  "transport_config": {
    "bind_endpoint": "tcp://127.0.0.1:5555"
  },
  "match_rule": {},
  "input_binding_mapping": {
    "request_image_ref": {
      "source": "payload.request_image_ref"
    }
  },
  "result_mapping": {
    "source": "workflow_result"
  },
  "default_execution_metadata": {
    "source": "line-1"
  },
  "ack_policy": "ack-after-run-finished",
  "result_mode": "sync-reply",
  "reply_timeout_seconds": 30,
  "debounce_window_ms": 0,
  "metadata": {}
}
```

## 提交与回执组合

| `submit_mode` | `ack_policy` | `result_mode` |
| --- | --- | --- |
| `sync` | `ack-after-run-finished` | `sync-reply` |
| `async` | `ack-after-run-created` | `accepted-then-query` 或 `event-only` |

不支持的组合在创建或 enable 时拒绝。同步调用不排队、不自动重试；Runtime 满载、停止、版本不一致或超时直接返回结构化错误。

## 版本与恢复

- 创建和 enable 时校验 Runtime 当前 revision、version、generation 与公开输入输出契约。
- Trigger 保存验证过的 revision/version/generation/contract fingerprint；Runtime 切版后必须重新校验。
- backend-service 启动先完成 Runtime recovery readiness，再恢复 enabled TriggerSource，避免 adapter 先接流量而 Worker 尚未就绪。
- 旧 generation 或旧 worker epoch 的回调不能污染当前 Runtime。
- disable/delete 在 Supervisor 停止 adapter 后更新持久状态；未完成停止时不假报成功。

## ZeroMQ 图片边界

ZeroMQ adapter 接收 envelope 与图片 bytes，把图片写入 LocalBufferBroker，再向 Workflow 提交 `image-ref.v1`。Workflow 图显式发布 `request_image_ref`，需要兼容 HTTP Base64 时在图内通过 coalesce 节点汇合。

大图热路径不得把图片转成 Base64 JSON。BGR24、mmap、owner/generation/deadline 与槽位回收规则见 [高性能图片数据面](../architecture/high-performance-image-data-plane.md)。

## 诊断

health 至少区分 desired/observed state、adapter 是否注册和运行、绑定 Runtime、验证 generation、endpoint、heartbeat 与最近错误。

Postman 与场景示例见 [Workflow Postman](postman/workflows/README.md)，.NET 调用见 [Workflow SDK](workflow-sdks.md)。
