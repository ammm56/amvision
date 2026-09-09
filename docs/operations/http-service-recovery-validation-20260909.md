# Windows HTTP 服务恢复修复验证

日期：2026-09-09。源码基线：`e5f4ee5802461fac3ec53cfe0333cfcfc99e132f`；本次记录对应该基线之后的 HTTP 恢复修复。版本仍为 0.1.6。

结论：已实现针对 WinError 64 的接入保护、持续 HTTP 探测、受控整栈恢复和启动器持续观察，定向回归及部分真实数据验证通过。完整生产验收仍未完成。本记录不能替代性能门禁、真实标注精度评估或 24 小时长稳报告。

## 实现与核对

| 边界 | 实现及验证目的 |
| --- | --- |
| Windows HTTP 接入 | 自定义 Proactor 只重试 WinError 64，失败连接立即关闭；未知错误和取消继续传播。8 次连续错误后从 1 ms 退避，封顶 100 ms。通过 service launcher 的 Uvicorn loop factory 启用。 |
| HTTP liveness | 纯进程内端点，不查询数据库、Broker 或模型。探测每轮新建 TCP 连接，默认总期限 1 秒、轮间间隔 2 秒、响应正文上限 4096 字节。 |
| 故障确认 | 单次失败显示 degraded；连续三次拒绝连接或持续失败达到 30 秒进入恢复；恢复为 running 需要连续两次成功。成功会中断连续失败窗口，启动 ID/PID 变化进入 failed。 |
| HTTP 排空 | ASGI 层统计完整请求生命周期，流式响应最后一段完成前不确认排空；排空阶段拒绝新业务 HTTP 请求，liveness 仍可读取。 |
| Runtime 排空 | 异步 Workflow 登记与停止标记在同一锁内交接；等待已登记工作完成。stop-runtime 回复之后还要确认 worker 正常退出。 |
| 恢复次序 | 更新 Topology 为 stopping，停止接入及 Runtime，等待 worker 退出，然后停止 daemon，最后关闭 service/Broker；验证全部旧身份退出后才创建下一代。 |
| 恢复保护 | 同一 Supervisor 持有原有单实例锁。启动 ID、PID、创建时间和进程树共同校验；10 分钟最多 3 次，退避 2/5/15 秒。排空失败、进程身份不明、异常退出或恢复预算耗尽时保留 failed，等待人工处理。 |
| Worker 恢复期间的监督 | Worker 就绪等待也消费 HTTP 探测结果；HTTP 故障不能在该等待路径中触发 worker 强杀或丢失组件所有权。 |
| 桌面启动器 | 连接成功后每 2 秒继续观察；支持 v1/v2 状态，区分 degraded/recovering/failed；外部服务只观察，不自动接管。不强制重载页面，不重复提交 Workflow。已退出的旧进程身份不无限累积。 |

恢复控制文件按 service 启动 ID 命名，使用 `amvision.http-recovery.v1`；成功一轮后删除该轮控制文件。不是新增的公网控制 API。主监督循环仅取一个最新快照，后台探测和控制线程均不保存无界请求历史。

本次没有改变模型权重、前后处理、共享内存二进制布局、ZeroMQ 协议或 SDK 数据传输实现。HTTP 请求新增两个进程内计数临界区；这只能说明改动边界，不能据此宣称性能零影响。

## 公开接口及状态文件

`GET /api/v1/system/liveness` 响应示例：

```json
{
  "format_id": "amvision.service-liveness.v1",
  "instance_id": "0123456789abcdef0123456789abcdef",
  "pid": 1234,
  "phase": "ready"
}
```

`instance_id` 是每次 service 启动新生成的 32 位小写十六进制 ID；`pid` 为正整数；`phase` 为 `starting/ready/draining/stopped`。只有 `ready` 可作为 HTTP 接入就绪。该端点不认证业务可用性，也不授予业务权限。原 `/health` 保持原语义；未知 `/api`、`/ws` 路径不再回退到 SPA HTML。

`launcher-status.json` writer 升为 `amvision.launcher-status.v2`，保留 `root_process/state/error`，新增 `generation`；恢复沿用同一 root 并递增 generation。reader 兼容 v1，未知版本或 root 身份不匹配明确失败。数据库结构没有变化，不需要 migration。

## 已完成验证

| 测试 | 结果与适用范围 |
| --- | --- |
| 原始 Windows 故障固定 | 注入 WinError 64 后，原始监听关闭但循环存活。用于说明本次修复所覆盖的机制，不能倒推出现场具体客户端。 |
| accept 回归 | 同目录 Python 3.12.13 的 6 项测试通过，包括 Uvicorn 100 次真实 HTTP 新连接、一条持续 WebSocket、10 次 accept 错误交错；未知错误和取消释放连接。 |
| 监督、排空、资源所有权 | 最终补充批次 61 项通过，含 Broker 未退出不得强杀、Runtime ACK 后仍存活不得清理、Worker 就绪被 HTTP 故障打断时保留所有权；旧 epoch 拒绝、有 reader guard 的 extent 保持 revoking 而不复用。 |
| 最后定向复核 | 46 项通过、2 项真实控制台 reload 用例跳过。跳过项的独立尝试与失败结论见下文。Ruff 与 git diff 空白检查通过。 |
| 生命周期、API、发行契约 | 分阶段执行：64 项初始回归通过；18 项发行运行时、生命周期、API 契约通过；37 项 HTTP 排空及 Runtime 回归通过。批次有重叠，不相加为独立用例数。 |
| 启动器 Core | 9 项通过，含运行中失联、再次连接以及 NavigationId 不变、退出后没有残余探测。 |
| 启动器 Infrastructure | 26 项通过，4 项依赖实际进程/发行环境的测试默认跳过；单独进程集成脚本执行其中 3 项，通过。固定 5600 的发行冷启动用例未执行，以免占用开发服务。 |
| 隔离 CPU 发行，无模型 | 关闭实际 HTTP 监听，保留循环存活；Supervisor 根身份不变，17 个旧子进程退出，换代恢复 89.625 秒。 |
| 隔离 CPU 发行，真实模型 | 真实 YOLO11/OpenVINO CPU 分类模型完成导入、sync 启动/预热/推理/停止、async 启动/预热/任务推理/停止和重新导出。运行模型时关闭监听，18 个旧子进程全部退出，93.141 秒恢复，模型 desired running 自动恢复。 |
| 最终源码完整发行 | 使用 `release/http-recovery-validation/verified/full-windows-x64-cpu`，包含本次桌面构建；核对 accept、monitor、recovery、full launcher 与源码一致。再次真实模型恢复通过，18 个旧进程正常退出，耗时 87.625 秒，恢复后概率与基准一致。 |
| 真实 .NET Framework x64 SDK | 使用实际 59,885,622 字节 BMP 和 3570 Runtime，HTTP、ZeroMQ、LocalSharedMemory 返回同一个分类摘要：24 个空槽、0 个异常、passed=true。临时创建的共享内存 TriggerSource 已删除，用户原有 TriggerSource 未改动。 |
| 浏览器 | 独立标签页检查实际 Runtime。当前 3570 发布版本未配置 app-mode，页面明确显示此状态；不能视作完整结果展示通过。原有未保存 Workflow 编辑页保留。 |

模型回归输入来自已有真实部署导出包，SHA-256：`b655cecdf49bf60df26b203ad5fef80bbf276ab14b48df7632129894cc2e95d0`。模型为 YOLO11 `pcbtrayslotsmall4570`，OpenVINO FP32 CPU，输入 224×224。样本图片 1080×722；恢复前后类别概率分别为 `0.509155 / 0.449694 / 0.041151`，与原始结果逐项比较，容差 `1e-5`。这是回归一致性证据，不是标注集准确率。

Windows 上无监听端口可能表现为连接超时，因此实际演练走了持续 30 秒失败确认窗口。恢复耗时包含故障确认、排空、daemon/Broker 关闭、六类 worker 启动和模型恢复；不能把这些数字解释为单请求推理时延。

真实 reload 补测没有通过：同一自动化宿主下，原始 `IocpProactor` 与项目 `HttpProactor` 均检测到文件变化，但 25 秒内未完成子进程换代。最初共享控制台还导致验证命令被 Ctrl+C 信号中断；后续已改为独立隐藏控制台。该失败属于仍需核对的 Uvicorn/Windows 控制台信号路径，不能归因为本次 accept 改动，也不能宣称 reload 验收通过。[Microsoft 控制台文档](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent) 说明 CTRL_C_EVENT 不能按非零进程组限定交付。对应测试需在独立 Windows 控制台设置 `AMVISION_TEST_CONSOLE_RELOAD=1` 后显式运行，默认跳过这两个环境相关用例；跳过不是通过。

重复演练曾因上一轮保留 desired running 而不满足导入验收脚本的初始 stopped 条件。测试准备已补充隔离实例的状态复位及 Supervisor 根 PID 核对，没有修改业务恢复结果来绕过断言。

## 发布边界

开发环境使用 `conda activate amvision`；目标发行使用同目录 Python。已测试组合为 Windows x64、Python 3.12.13、Uvicorn 0.48.0；Windows loop factory 拒绝其他 Python minor，发行验证要求 Uvicorn 0.48.0。其他 Python patch、reload 真实重载、IPv6 多监听及 NVIDIA profile 仍需按部署目标补测。

直接执行 `python -m uvicorn ...` 不会自动选择项目 factory。开发入口应使用 `runtimes/launchers/service/start_backend_service.py`，或显式传入 `--loop backend.service.infrastructure.http.windows_event_loop:create_loop`。本轮没有重启用户正在运行的开发服务，因此不能声称其既有进程已启用新 accept 适配。

启动器已按 `launcher/publish-win-x64.ps1` 构建，使用自包含 .NET 和 Fixed Version WebView2。Python 源码、launchers、前端与桌面组件应通过 `assemble-release` 同批生成。已有数据的发行目录不能强制重建；本轮验证使用独立输出目录。原用户发行目录未修改。

## 尚未通过的放行项

- 最终目标机至少 5 轮修复前后交错性能对照，HTTP/ZeroMQ/共享内存 P95/P99、吞吐及进程资源趋势。历史共享内存 P99 失败结论保留。
- 24 小时混合真实业务、客户端断连和受控故障运行；短测试不替代长稳。
- 使用具有 app-mode 布局的实际发布版本，完成 SDK 调用到前端结果更新，以及恢复前后展示验证。
- .NET SDK 持有真实 mmap view 时整栈恢复、各请求阶段的故障注入、训练/转换长任务、外部副作用节点去重与终态核对。
- NVIDIA 最终发行及本机桌面窗口交互验收。本会话原生桌面控制不可用，未把 C# 测试或浏览器测试冒充桌面 GUI 验收。

发生故障时不会自动重放业务请求；含外部副作用的操作不能承诺透明恢复或 exactly-once。无法确认旧资源安全释放时，自动恢复停止在 failed 是保护行为，不能绕过检查后重新启动 owner。

## 测试资源清理

本轮测试进程已退出，临时共享内存 TriggerSource 删除后查询返回 404，临时浏览器标签页已关闭；开发服务 liveness 返回 200 ready。原有未保存的图编辑页和业务 TriggerSource 保留。

本轮 `.tmp/http-*` 测试目录及输出文件的清理已执行到工具审批阶段，但被自动审批策略拒绝，返回 `blocked by policy`，没有更详细原因。临时产物仍保留，未通过其他方式绕过删除限制；这些路径不是长期交付物，也不纳入版本控制。长期验证结论以本记录为准。
