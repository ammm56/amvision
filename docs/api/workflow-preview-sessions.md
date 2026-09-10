# Workflow Preview Session v1

编辑器预览使用常驻独立进程执行冻结的应用与模板快照，通过 WebSocket 逐节点显示。输入、执行文档、事件、图片和完整 JSON 值使用内存及操作系统共享内存；不生成 Preview 数据库记录、事件文件或临时交换文件。模型与已有文件可以读取，节点明确配置的保存行为仍会写入目标位置。

正式 WorkflowAppRuntime、WorkflowRun 和 Trigger 的协议不变。

## 连接与控制

所有控制操作需要 `workflows:write`，WebSocket 需要 `workflows:read`。会话绑定认证主体、项目、应用和编辑器身份；其他主体、项目或已过期会话不能读取其数据。

| 操作 | 路径 | 成功 |
| --- | --- | --- |
| 创建会话 | `POST /api/v1/workflows/preview-sessions` | 201 |
| 订阅 | `/ws/v1/workflows/preview-sessions/{session_id}` | `session.snapshot` |
| 提交 | `POST /api/v1/workflows/preview-sessions/{session_id}/runs` | 202 |
| 请求取消 | `POST /api/v1/workflows/preview-sessions/{session_id}/runs/{run_id}/cancel` | 202 |
| 释放会话 | `DELETE /api/v1/workflows/preview-sessions/{session_id}` | 204 |

创建请求：

```json
{"project_id":"project-1","application_id":"app-1","editor_session_id":"editor-unique-id"}
```

创建响应包括 `format_id=amvision.workflow-preview-session.v1`、`session_id`、服务启动代次 `epoch` 和 `memory_limit_bytes`。必须收到 WebSocket 快照后再提交。提交体包含：

- `request_id`：UUID。同一会话、同一内容的重试返回原 run；内容变化返回 409。不会自动重放业务。
- `document_revision`：编辑器生成的本次文档身份。
- `application`、`template`：完整 v1 文档，直接在内存校验和执行；不接受磁盘快照路径。
- `input_bindings`：小型 JSON 输入；`input_ids`：绑定名称到已完成上传 ID 数组的映射。
- `execution_scope`：`{"kind":"application"}` 或 `{"kind":"node","target_node_id":"node-1"}`。
- `timeout_seconds`：可选业务期限。省略沿用 `preview_default_timeout_seconds`，默认 1800 秒。连接心跳和业务期限独立。

每会话一条活动执行，全局并发受 `preview_worker_count` 限制；忙返回 409，容量不足返回 429/413。取消受理不代表执行已经停止；协作取消失效时仅终止本次 Preview Worker，确认进程退出后释放借用。

## 实时状态

事件公共字段为 `format_id, session_id, epoch, run_id, document_revision, seq, type, payload`。`seq` 由服务器分配。节点身份包括 `node_id, invocation_id, scope_path`，能够区分并行和循环。

| 消息 | 内容 |
| --- | --- |
| `session.snapshot` | 当前 run、nodes、displays、values 和 watermark |
| `run.accepted` / `run.started` | 已受理 / 已进入 Worker |
| `node.started` / `node.progress` / `node.finished` | 节点状态、节点实际报告的进度、耗时和错误 |
| `display.updated` / `display.unavailable` | 单节点输出端口的显示内容或明确失败 |
| `value.updated` | 完整值描述：inline、json 或 unavailable |
| `run.finished` | succeeded、failed、cancelled 或 timed_out |
| `run.outputs` | 业务结束后的最终输出、显示交付状态及分段耗时 |

节点显示不等待整图结束。页面缩略图和全尺寸预览均使用 JPEG，编码质量 90；可直接复用的 JPEG 源字节不重复编码。画布缩略图最大边长 1920，交互坐标始终使用源图尺寸，业务图片和模型输入不压缩。大 JSON 完整传输到浏览器，检查器在本地分页。自定义 response body 内的嵌套显示使用端口 JSON Pointer 路径区分。

`run.finished` 表示业务执行结束，`delivery_state=pending` 表示仍有显示编码；`run.outputs` 将交付置为 `ready` 或 `unavailable`。编码完成也不等于浏览器接收、解码完成。`timings` 中 `prepare_ms`、`graph_ms`、`worker_total_ms`、`display_drain_ms` 为 Worker 本地持续时间；页面另记录从点击开始的 `client_business_ms`、`client_total_ms`，不混用不同进程的计时起点。

页面分段计时包含文件读取、SHA256、传输、上传合计（`client_file_read_ms`、`client_file_hash_ms`、`client_file_transfer_ms`、`client_upload_ms`），以及提交前、提交请求、执行开始及首节点事件到达（`client_before_submit_ms`、`client_submit_ms`、`client_run_started_ms`、`client_first_node_ms`）。多文件读取/摘要/传输按本轮累计；各字段有重叠，不能直接相加。事件到达时间包含传输及浏览器调度，不等于 Worker 内部起点。

## 二进制上传和读取

1. 发送 `input.begin`，包含 UUID `transfer_id`、`byte_length`、`media_type`、SHA-256 `sha256` 和可选 `file_name`。
2. 收到 `input.ready` 后发送 AMVP 二进制块，每块不超过 256 KiB；逐块确认 `input.ack`，浏览器最多预发 8 块。
3. 发送 `input.commit`；全部块顺序、长度和 SHA-256 正确后返回 `input.committed` 与 `input_id`。

AMVP 使用网络字节序，32 字节头：`magic(4), version(1), kind(1), reserved(2), UUID(16), chunk_index(4), payload_length(4)`；version=1，kind=1 上传，kind=2 下载。

`display.get` 包含 `blob_id`，返回 `display.begin`、二进制块和 `display.end`；浏览器逐块发送 `display.ack`。不返回共享内存名称或任意文件读取接口。

图片和大 JSON 共用 `display.get`。完整传输后 `display.end` 携带不透明 `receipt`。浏览器按序校验完整长度、建立独立 Blob 后发送 `{"type":"resource.received","blob_id":"...","receipt":"..."}`。凭证绑定当前已鉴权的会话与 Blob；任意节点 ID、共享内存名称和未完成传输不能释放资源。分块 ACK 只用于流控。

所有当前订阅者接管后，后端撤销该 Blob 的持有；现有 borrow pin 归零后才销毁映射。已断开的订阅者不永久阻止其他接收者释放。快照描述符的 `server_available=false` 表示服务端不再提供该内容，同页重连使用已有浏览器缓存；没有本地副本时明确不可用。浏览器完整 JSON 默认按 50 项本地分页，已删除服务端 `value.get/value.page` 旧读路径。

## 边界与恢复

- 默认每会话受管内存 512 MiB，全局 1 GiB；上传单文件 64 MiB，JSON 值 16 MiB，快照请求 8 MiB；容量不足明确失败，不落盘。
- 控制队列最多 1024 项 / 4 MiB，慢订阅者溢出后重连快照；不反向阻塞模型等待浏览器。
- 15 秒连接心跳；所有订阅者离线 60 秒后回收会话。未使用上传也会过期。节点没有进度事件不代表服务故障。
- 每会话保留最多 256 个受理请求摘要，达到上限需创建新会话；不会淘汰去重记录后重新执行旧请求。
- 重连恢复当前内存状态。API 重启后 epoch 改变，旧会话明确失效；不会从磁盘恢复或重新执行。
- 受管预算不等于进程 RSS 或 GPU 显存上限，模型和第三方算法工作区另计。
- 显示排队最多 128 张图、256 MiB 矩阵；每次执行最多 4096 个编码描述符，超限返回显示容量错误。业务完成后的编码排空限 60 秒，超时只报告交付失败。

Preview 模型节点通过既有 PublishedInferenceGatewayClient、平台网关和 LocalBuffer 调用部署进程。Preview 不创建部署模型运行时池；显式 checkpoint/model-session 节点仍保留自身原有作用域。

项目服务启动器默认 `--ws-per-message-deflate false`，减少本地大图上传及 JPEG 二次压缩开销。手工 Uvicorn 启动需使用同一参数并重启生效；站点可显式覆盖。此设置影响 HTTP 服务 WebSocket 扩展协商，不改变 REST、模型字节和 Runtime/Trigger IPC。

## 开发阶段替换与数据库升级

旧 Preview Run REST/WS、数据库实体和磁盘结果实现已删除，无 v2、双写或兼容读取层。前后端应一起更新。Alembic `a8d6c4e2b019` 删除旧临时运行表，将已有 preview-default 策略转换为 runtime-default 并保留参数及正式运行引用。升级使用项目 `migrate-database` 维护入口及其备份流程；降级仅恢复空表结构，旧临时数据需从备份恢复。

开发使用 `conda activate amvision` 后运行项目 Python；发行使用同目录 Python 和随包前端，不依赖外网 CDN、Redis 或系统 Node。当前部署入口为单 API 进程，Preview Worker 数量独立配置。

## 执行期图片引用与节点删除

ROI 等完整 JSON 中的 `image_handle` 是 execution registry 的不透明 ID，不是 OS SHM 名称或可下载 Blob。值描述以 `reference_scope: execution` 标明这一作用域；完整 ROI 数值仍保留，浏览器取图只接受会话授权的 `blob_id`。

`run.accepted` 的 `node_ids` 固定本次文档节点集合，客户端据此释放已删除节点的旧显示；仍存在节点的上次结果标为 stale，直到新显示完整接收再替换。标准 Uvicorn `--workers` / `WEB_CONCURRENCY` 必须为 1；其他多进程 ASGI 宿主暂不支持。
