# 11 Directory Poll YOLOX Position Gate 调试说明

## 文档目的

本目录用于说明 `11-industrial-local-directory-poll-yolox-position-gate.postman_collection.json` 的实际导入、改值和联调顺序。

这组请求不是单纯的 TriggerSource 片段，而是一条完整的工业目录轮询检测闭环：

- 保存 workflow template
- 保存 workflow application
- 先用 preview/runtime 做图级联调
- 再创建并启用 `directory-poll` TriggerSource
- 最后让真实目录轮询驱动同一条 YOLOX + 工业规则链

## 导入后先改的变量

- `baseUrl`：FastAPI 服务地址，默认是 `http://127.0.0.1:8000`
- `projectId`：目标项目 ID
- `accessToken`：本地用户 token
- `deploymentInstanceId`：已经可用的 YOLOX deployment 实例 ID

如果 `deploymentInstanceId` 不存在，`Invoke App Runtime`、`Create Workflow Run` 和真实 `directory-poll` 提交都会失败。

## 导入后先改的请求体字段

以下字段通常需要按现场机器改成真实值：

- `trigger-source.create.request.json` 里的 `transport_config.directory_path`
- `trigger-source.create.request.json` 里的 `extensions`、`batch_size`、`scan_interval_seconds`、`min_stable_age_seconds`
- `app-runtime.invoke.request.json` 里的 `request_trigger_payload.directory_path`
- `app-runtime.invoke.request.json` 里的 `files[*].path`
- `app-runtime.invoke.request.json` 里的 `file_paths[*]`

默认回传地址写的是 `http://127.0.0.1:18080/directory-poll/yolox-position-batch-result`。当前 template 里 `http-post` 节点使用 `require_success=false`，因此本地没有回调服务时不会把整条 workflow 直接打失败，但现场联调时仍建议改成真实回传地址。

## 推荐联调顺序

### 1. 先保存图和应用

按下面顺序执行：

- `Save Template`
- `Save Application`

这一步只验证保存路径、template/application 规则和图绑定关系。

### 2. 先做图级干跑

按下面顺序执行：

- `Create Preview Run`
- `Get Preview Run`

这一步是可选的，但建议保留。它最适合先确认：

- `request_trigger_payload`
- `request_trigger_event`
- `deployment_request`

这三个输入 binding 形状没有写错。

### 3. 启动正式 runtime

按下面顺序执行：

- `Create App Runtime`
- `Start App Runtime`
- `Get App Runtime Health`

只有这一步通过，后面的 direct invoke、async run 和真实 TriggerSource 才有共同宿主。

### 4. 先跑 synthetic event 版 direct invoke

执行：

- `Invoke App Runtime (Synthetic Event)`

这一步不是在轮询目录，而是手工构造一份与 `directory-poll` 提交形状一致的 `payload / event`，用来复现同一条业务链。建议把它作为第一次定位问题的主入口，因为最容易看清：

- 输入绑定是不是对
- `deployment_request` 有没有注入成功
- workflow 图里的 `payload-to-value` 桥接是不是正常
- YOLOX 检测到 `regions.v1` 再到规则链有没有跑通

### 5. 再跑 async workflow run

按下面顺序执行：

- `Create Workflow Run`
- `Get Workflow Run`

这一步仍然不是实际目录轮询，而是验证真实 TriggerSource 最终会走到的 async run 语义。

### 6. 再创建并启用真实 directory-poll

按下面顺序执行：

- `Create TriggerSource`
- `Enable TriggerSource`
- `Get TriggerSource Health`

启用后，adapter 会按 `scan_interval_seconds` 周期扫描 `transport_config.directory_path` 指向的目录，并按稳定期过滤、checkpoint 去重和 batch 规则持续提交。

### 7. 观察真实目录轮询效果

观察面主要有三处：

- `Get TriggerSource Health`：看 health、最近错误、`sequence_id`、`checkpoint_path` 和 `known_identity_count`
- `Get Workflow Run`：看异步运行结果
- workflow 结果目录：看 JSON/CSV 归档是否落地

### 8. 调试完成后收尾

按下面顺序执行：

- `Disable TriggerSource`
- `Delete TriggerSource`
- `Stop App Runtime`

## Synthetic Event 和真实 Directory Poll 的区别

- `Invoke App Runtime (Synthetic Event)` 只是本地复现标准化后的 `payload / event` 输入形状，不会真的扫描目录，也不会推进 checkpoint
- 真正的 `directory-poll` 行为以启用后的 TriggerSource 常驻线程为准：由 adapter 负责扫描周期、稳定期过滤、identity 去重、checkpoint 恢复和批次提交
- 如果 synthetic event 能跑通但真实轮询没有提交，优先检查 `directory_path`、`extensions`、`scan_interval_seconds`、`min_stable_age_seconds` 和 health 里的 checkpoint / 最近错误字段
