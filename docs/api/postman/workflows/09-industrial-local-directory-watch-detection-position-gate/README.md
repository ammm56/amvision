# 09 Directory Watch Detection Position Gate 调试说明

## 文档目的

本目录用于说明 `09-industrial-local-directory-watch-detection-position-gate.postman_collection.json` 的实际导入、改值和联调顺序。

这组请求不是单纯的 TriggerSource 片段，而是一条完整的工业目录批次检测闭环：

- 保存 workflow template
- 保存 workflow application
- 先用 preview/runtime 做图级联调
- 再创建并启用 `directory-watch` TriggerSource
- 最后让真实目录事件驱动同一条检测 + 工业规则链

## 导入后先改的变量

- `baseUrl`：FastAPI 服务地址，默认是 `http://127.0.0.1:5600`
- `projectId`：目标项目 ID
- `accessToken`：本地用户 token
- `deploymentInstanceId`：已经可用的 detection deployment 实例 ID

如果 `deploymentInstanceId` 不存在，`Invoke App Runtime`、`Create Workflow Run` 和真实 `directory-watch` 提交都会失败。

## 导入后先改的请求体字段

以下字段通常需要按现场机器改成真实值：

- `trigger-source.create.request.json` 里的 `transport_config.directory_path`
- `trigger-source.create.request.json` 里的 `extensions`、`batch_size`、`min_stable_age_seconds`
- `app-runtime.invoke.request.json` 里的 `request_trigger_payload.directory_path`
- `app-runtime.invoke.request.json` 里的 `files[*].path`
- `app-runtime.invoke.request.json` 里的 `file_paths[*]`

默认回传地址写的是 `http://127.0.0.1:18080/directory-watch/detection-position-batch-result`。当前 template 里 `http-post` 节点使用 `require_success=false`，因此本地没有回调服务时不会把整条 workflow 直接打失败，但现场联调时仍建议改成真实回传地址。

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

这一步不是在监听目录，而是手工构造一份与 `directory-watch` 提交形状一致的 `payload / event`，用来复现同一条业务链。建议把它作为第一次定位问题的主入口，因为最容易看清：

- 输入绑定是不是对
- `deployment_request` 有没有注入成功
- workflow 图里的 `payload-to-value` 桥接是不是正常
- 检测到 `regions.v1` 再到规则链有没有跑通

### 5. 再跑 async workflow run

按下面顺序执行：

- `Create Workflow Run`
- `Get Workflow Run`

这一步仍然不是目录监听，而是验证真实 TriggerSource 最终会走到的 async run 语义。

### 6. 再创建并启用真实 directory-watch

按下面顺序执行：

- `Create TriggerSource`
- `Enable TriggerSource`
- `Get TriggerSource Health`

启用后，把测试图片放进 `transport_config.directory_path` 指向的目录，等待稳定期和批次扫描完成。

### 7. 观察真实目录提交效果

观察面主要有三处：

- `Get TriggerSource Health`：看 health、最近错误、sequence 和记账状态
- `Get Workflow Run`：看异步运行结果
- workflow 结果目录：看 JSON/CSV 归档是否落地

### 8. 调试完成后收尾

按下面顺序执行：

- `Disable TriggerSource`
- `Delete TriggerSource`
- `Stop App Runtime`

## Synthetic Event 和真实 Directory Watch 的区别

- `Invoke App Runtime (Synthetic Event)`：只是在 HTTP 调试入口手工构造 `directory-watch` 形状的请求体，用来验证 workflow 图和 runtime 输入边界。
- `Create TriggerSource + Enable TriggerSource`：才会真的启动目录监听线程、稳定期过滤、批次组装、checkpoint 恢复和去重逻辑。

如果 synthetic event 能跑通，但启用后的真实监听没有出结果，优先排查目录监听配置，而不是先怀疑 workflow 图。

## 现场排查重点

- 空目录不会产生 run；必须真的有新文件进入监听目录。
- 文件还在写入时，`min_stable_age_seconds` 没到，不会进入 ready batch。
- 当前示例默认 `dedupe_by=path` 且 `persist_checkpoint=true`，同一路径文件重复落地后可能被视为已处理。
- `force_polling=true` 更适合“先写临时文件再改名落地”的守护式目录接入；如果现场已经验证原生文件事件稳定，再考虑改成 `false` 或 `null`。
- 这条链依赖已存在的 detection deployment；如果 deployment 不可用，目录监听虽然能收到事件，但 workflow 仍会在推理节点失败。
- 回调地址不可达默认不会让整条链失败，但现场正式上线前仍应改成真实可达地址。

## 推荐使用方式

第一次接这条链时，建议按下面节奏：

1. 先用 `Invoke App Runtime (Synthetic Event)` 把图跑通。
2. 再用 `Create Workflow Run` 确认 async 结果语义。
3. 最后再启 `directory-watch` 做真实目录联调。

这样最容易把“图有问题”和“目录监听有问题”分开看，不会两层问题混在一起。
