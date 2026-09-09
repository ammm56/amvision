# 0.1.6 生产就绪审计（2026-09-09）

结论：**当前不满足生产放行条件。** 本轮发现了实际服务不可用但进程仍存活的问题，以及 API 错误回退。源码回归通过不能替代真实业务精度、尾延迟、故障恢复和长期运行验收。

2026-09-09 后续范围决定：默认账号与公开 token 属于明确保留的产品行为，不实施认证复杂化；日志容量边界暂缓处理。下文保留原始观察，分别标记为接受现状和暂缓，不再把它们列入本次核心功能修复任务。

本记录是指定版本的一次有界审计，不是所有代码无缺陷的证明，也不代表任何工业标准认证。本轮仅增加审计记录，不修改业务源码、生产配置、凭据或运行中的资源，不重启发行服务。

## 1. 基线与范围

- 源码：`e5f4ee5802461fac3ec53cfe0333cfcfc99e132f`；审计开始时工作区干净。
- 产品版本：前端、后端、启动器 `0.1.6`。
- 实际检查的发行包：`release/full-windows-x64-cpu/`。
- 发行 manifest：`product_version=0.1.6`、`source_revision=e5f4ee5802461fac3ec53cfe0333cfcfc99e132f`、`source_dirty=false`、`assembled_at_utc=2026-09-09T11:41:35.105501Z`。
- 目标暂按 Windows x64 本地 CPU 部署；NVIDIA 目标尚未确认。当前 NVIDIA 目录仅有 Python，不能将它计作完整发行包。
- 真实业务资产范围仅按已知 YOLO11 分类模型及相关图片处理；其他模型的合成张量、轻量计算图和 mock 测试不计为真实精度验收。
- 覆盖源码边界：数据集导入/导出、训练与转换任务、发布包完整性、推理网关、共享内存消息、Workflow Runtime/Trigger、.NET SDK、前端、启动器、数据库迁移与任务持久化。
- 使用只读 HTTP、进程/端口/日志检查以及隔离临时目录中的自动化测试。未对用户运行中的服务注入断网、杀进程、满盘或长时间压力。

## 2. 已确认问题

### P1-01：HTTP 监听已消失，但服务进程存活、启动器状态文件仍为 running

**现场证据**：审计前段 HTTP 接口可以响应；后续在约 19:53–19:56 复查时，`127.0.0.1:5600` 新连接被拒绝，`Get-NetTCPConnection` 与 `netstat` 均未发现 5600 LISTEN。后端 PID `38736`、服务包装进程 PID `8128`、full-stack PID `42524` 仍存在。`logs/full-stack/launcher-status.json` 仍为 `running`。本轮没有执行停止这些进程的命令。

发行服务日志记录：

```text
Task exception was never retrieved
IocpProactor.accept.<locals>.accept_coro()
OSError: [WinError 64] 指定的网络名不再可用。
Accept failed on a socket
laddr=('0.0.0.0', 5600)
```

日志随后还有已有连接上的请求记录；这与“旧连接尚能活动，新连接无法接入”相符。日志没有逐条时间戳，因此不将文件最后写入时间当作异常精确发生时间。

**已定位的处理路径**：发行 Python 3.12.13 的 `Lib/asyncio/proactor_events.py` 中 `_start_serving` 在 accept future 抛出 `OSError` 后调用异常处理器并 `sock.close()`，没有恢复 accept。对应 `windows_events.py` 的 accept 完成回调把 `ov.getresult()` 错误向上传递。当前服务使用该 Windows 事件循环路径。

[full-stack Supervisor](../../runtimes/launchers/full/start_amvision_full.py) 在启动阶段检查 HTTP health，但持续运行阶段主要检查日志线程和 `process.poll()`。只要进程未退出便继续循环，不能识别本次监听已经消失的状态。这是项目可用性监控的明确缺口。

**归因边界**：监听丢失后的处理与未被 Supervisor 识别已有源码和现场证据；最初的 WinError 64 是客户端连接中断、系统网络栈、其他软件还是其他原因触发，尚未确定。不能归因于某次模型、共享内存或前端修复。没有证据据此判断内存泄漏。

**修复与验证设计**：

1. 在服务控制层增加有超时、低频、连续失败判定的就绪监测，区分进程存活、HTTP 可接入和业务就绪；失败状态同步给启动器。
2. 对确认丢失监听的实例采取明确的失败/恢复策略，核对 PID 与进程创建时间。恢复需要遵循现有 Broker、daemon、worker 生命周期，不盲目另起一套服务，不对业务调用进行无条件重放。
3. 在隔离 Windows 发行实例中验证 accept 错误、监听关闭但进程存活、慢 health、短暂网络故障、正常关闭与连续失败后的退避。核对未完成请求、租约回收与客户端重连。
4. 事件循环或 Python 版本调整必须独立验证 WebSocket、子进程、连接规模和尾延迟；不直接改发行 Python 标准库，也不未经验证全局替换事件循环。

### 原 P1-02（明确保留）：可访问的前端配置公开了有效的默认管理员凭据

**现场证据**：服务可访问阶段，无认证读取 `/runtime-config.json` 返回 200，包含启用自动登录的默认 user token。用该配置中公开的 token 只读请求 `/api/v1/system/me` 返回 200，权限 `scopes=["*"]`，项目范围无限制。后端启动参数绑定 `0.0.0.0:5600`。本报告不记录凭据明文。

来源：[默认账号 seeder](../../backend/service/application/auth/default_local_auth_seeder.py)、[认证默认设置](../../backend/service/settings.py)、[前端配置模板](../../frontend/web-ui/public/runtime-config.template.json)及前端运行配置 fallback。空库默认创建已知账号、已知密码及长期全权限 token。

**影响**：任何能够访问该 HTTP 服务的客户端都可能取得管理员权限。当前机器防火墙和外部网络可达性未验证，不能把绑定所有地址等同于已暴露公网；但现有配置不能作为共享网络生产环境的访问控制边界。

**修复设计**：区分开发便利配置与生产首次初始化；生产使用唯一初始凭据并显式完成账号配置；撤销已有默认长期 token，处理默认密码；SDK 使用最小权限及项目范围 token。仅删除前端 token 或关闭自动登录不会撤销服务端已存在的凭据。实现应放在初始化、配置和认证边界，不向每帧推理增加额外查询。

**复验**：匿名配置中无有效管理凭据，旧默认凭据被拒绝，新管理员登录正常，两个账号/项目之间权限隔离，SDK 合法调用及凭据撤销均符合公开契约。

### P2-01：未知 API 路径返回 200 HTML

**现场证据**：`GET /api/v1/audit-nonexistent-route` 返回 `200 text/html`，内容为前端入口页面，而不是 API 404。该请求仅作只读路径探测。

来源：[FrontendStaticFiles.get_response](../../backend/service/api/app.py) 对没有扩展名的 404 路径直接回退 `index.html`，未排除 API 命名空间。已有 SPA fallback 测试未覆盖该边界。

**影响**：SDK 可能收到 JSON 解析错误，路径拼写或版本错误被掩盖，只看 HTTP 状态的探测可能误判成功。正确的已注册接口不因该问题自动变成无认证接口。

**修复设计**：保留前端深层路由回退，明确排除服务端 API/协议命名空间；增加未知 API、前端深链、缺失静态文件、认证失败和方法不支持的边界验证。

### 原 P2-02（暂缓）：full-stack 日志没有磁盘总量与保留期边界

来源：[DailyAppendLogCapture](../../runtimes/launchers/common.py) 按日期追加磁盘日志，只有内存日志尾部受到容量限制；未见按文件大小、总字节数或保留天数清理的实现。独立的 `bounded_log_sink.py` 不能替代此路径的容量控制。

日志写入失败被记录为捕获线程错误，Supervisor 的 `assert_healthy()` 会使 full-stack 进入失败清理路径。因此持续日志增长可能最终影响整个服务的可用性。

**证据边界**：本项是源码确认的容量缺口和故障路径；现场没有执行满盘实验，也没有发生已确认的磁盘耗尽。本次发现的 HTTP 监听故障不能归因于此项。

**修复设计**：规定每文件/总容量、保留期、清理周期与磁盘预警；只清理明确归属的历史日志；在独立日志工作线程实施有界策略并持续排空 stdout，避免把磁盘扫描放入每帧链路。满盘时保留明确错误状态，不能吞掉重要业务写入失败。

**复验**：模拟写失败/配额、跨日轮转、大量输出、清理失败和停止过程；核对磁盘容量有界、pipe 不堵塞、状态可信及所选故障策略。

## 3. 本轮实测结果

| 检查 | 结果 | 适用边界 |
| --- | --- | --- |
| 后端 API、认证、发行、包校验、IPC、Trigger、推理、worker 第一组 | 162 passed，156.36 秒 | 源码定向回归 |
| 数据集、训练/转换、模型计算图、遥测、队列原子性、迁移、日志第二组 | 237 passed，161.27 秒 | 源码定向回归，含轻量真实 ONNX/OpenVINO 执行；非真实业务全模型验收 |
| 后端合计 | **399 passed** | 35 个指定测试文件，并非后端全仓库全量测试 |
| 前端默认并发全量 | **531 passed，1 failed** | TrainingTaskDetailPage 一项超过 10 秒，首轮失败保留 |
| 前端上述文件单独复测 | 4 passed | 原文件包含 4 项；不能重复计入总覆盖数 |
| 前端全量降低并发 `--maxWorkers=2` | **129 files / 532 passed**，86.46 秒 | 未修改测试超时；与执行资源竞争相符，但未严格证明首轮超时根因 |
| 启动器 `dotnet test` | **63 passed，4 skipped** | 4 项真实进程/发行启动退出测试未执行，不能计为通过 |
| .NET SDK .NET Framework 4.7.2 x64 Release | 构建退出 0，契约程序退出 0 | 消息/结果/映射缓存/JSON 契约；未运行现场 Console 触发配置 |
| CPU 发行 `validate-layout` | valid/runtime valid/requirements valid，issues 空 | bundled Python、launcher、目录及运行依赖检查通过 |
| CPU bundled Python `pip check` | No broken requirements found，退出 0 | 依赖声明一致性，不等于所有硬件运行验证 |

模型组产生 56 条 ONNX 导出弃用、trace 和索引相关 warning。测试执行通过；不能把警告直接计为模型错误，也不能由固定输入图测试宣称动态形状和全部权重均已验证。

CPU 发行环境为 Python 3.12.13 x64、PyTorch 2.12.1+cpu；未配置 CUDA/TensorRT 符合本次 CPU profile。开发 conda 环境结果与发行解释器检查分别记录，不能互相替代。

### 现场业务状态

服务可访问阶段观察到 Broker、独立推理 daemon 和 6 个同 epoch worker 就绪。Broker 的 2 GiB arena 空闲、无活跃租约及隔离项，消息通道页/描述符容量正常。这是时点状态，不证明长时间无泄漏。

部署实例已有导入成功记录，读取到 4 条完成的导入回执，至少 3 个 YOLO11 分类 OpenVINO CPU 部署配置。当前包完整性检查成功不能替代实际分类精度测试，也不能证明历史 ZIP 位错误的底层原因已经消失。

在可访问阶段，`GET /api/v1/workflows/app-runtimes` 与 `GET /api/v1/workflows/trigger-sources` 返回空数组。生产 Runtime/Trigger 的真实业务闭环尚未建立；后续 HTTP 监听失败又阻止了最终在线复查。不能用之前开发环境的 App/Runtime/Trigger 记录代替当前发行环境验收。

## 4. 原有修复及未闭合门禁

- [模型修复记录](../development/model-matrix-repair-plan.md)中的 YOLO26 TopK 校验、Pose 评估策略、RF-DETR 输出访问问题已具备修复及定向测试。本轮不把历史失败误报为当前仍存在的相同代码错误。真实权重、全部设备/精度组合仍需独立验收。
- [共享内存实施记录](../development/local-message-channel-implementation.md)明确保留真实目标发行环境 **24 小时混合 soak** 门禁，当前未完成。短测和合成测试不能替代。
- [Runtime 显示记录](../architecture/workflows/runtime-display.md)保留一小时 16 个大图客户端的 **P95/P99 失败**，正确性与资源稳定通过不意味着尾延迟通过。此前共享内存第二轮 P99 相比 ZeroMQ 高约 17.46% 的用户反馈，本轮没有新的受控证据将其关闭或重新归因。
- 导出包每次重建及完整性验证的回归通过，现场有成功导入回执；历史 CRC 破坏的最初来源没有在本轮确定。
- 真实启动、停止、立即退出、端口被无关进程占用的 4 项启动器测试仍需在隔离发行目录运行。不能占用当前 5600 或把测试绕过条件记作通过。
- 尚未执行真实备份恢复与版本回滚演练；数据库迁移单测不等于生产恢复能力已验收。
- 本轮没有执行 NVIDIA/TensorRT 发行验证、全量模型训练、真实跨数据库迁移、外网暴露测试或依赖漏洞全量扫描。

## 5. 修复和放行顺序

1. **先修核心可用性与接口边界**：监听丢失识别/恢复、API 404 边界。默认凭据保持现状，日志容量暂缓。修改源目录并定向验证，再重新组装目标发行包；不手改 `release/<profile>/app`。
2. **冻结验收对象**：确认 CPU/NVIDIA、目标机器、模型与转换产物摘要、App 发布版本、Runtime/Trigger 配置、实际图片集、并发数、响应大小以及前端预览客户端数量。设定业务精度、吞吐、P95/P99、超时率和恢复时间要求。
3. **隔离发行集成验收**：验证安装/启动/停止、账号隔离、导出→下载→导入、已知图片与标注的分类结果；经 Deployment→独立 daemon→Workflow Runtime→HTTP/ZeroMQ/共享内存 Trigger→.NET SDK→app-mode 展示，核对同次调用身份、类别映射、结果一致性与资源释放。sync/async 分别覆盖。涉及外部输出的自定义节点使用受控接收端。
4. **性能复验**：固定模型、输入、预热、设备和负载，多轮交错对比 ZeroMQ/共享内存；分离纯 IPC、模型执行和大图广播开销，记录 P50/P95/P99、吞吐、CPU、private bytes、working set、page fault、句柄及租约/页容量趋势。沿用当前文档门禁，不以平均值、最好轮次或放宽门槛覆盖失败。
5. **故障与恢复**：监听失效、短暂断连、客户端异常退出、worker/daemon 异常、队列满、重复/迟到请求、日志配额、数据库忙、坏包与恢复重连。故障注入在隔离环境执行；核对调用不会串包、旧 owner 不复用、资源守恒、失败不伪装成功、无无限重试。
6. **真实 24 小时混合运行**：使用最终发行解释器、真实 YOLO11 分类图片、已预热部署、实际 Runtime/Trigger 和预览负载。结果中保留所有失败，检查资源斜率与恢复后基线，而不是只看开始/结束两张快照。
7. **生产恢复演练**：备份数据库、对象文件、配置及版本清单，在独立目录恢复并核对资源引用与产物摘要；验证版本回滚和已验证的退出清理。归档验收摘要后再决定放行。

上述修复主要处于启动器、配置、认证、路由及日志边界，不应向推理/共享内存热路径增加每帧数据库操作、全量拷贝、磁盘扫描或无界缓存。正式放行只覆盖实际通过验收的模型、设备、协议及负载范围。

## 6. 可复跑命令

Python 测试先执行 `conda activate amvision`。使用仓库 `.tmp/` 内的独立目录，运行结束后清理本次临时产物。

```powershell
python -m pytest tests/test_api_dependency_chain.py tests/test_local_auth_api.py tests/test_release_assembly.py tests/test_release_runtime_validation.py tests/test_launcher_release.py tests/test_model_deployment_package_archive.py tests/test_model_deployment_export_reuse.py tests/test_local_message_channel_engine.py tests/test_workflow_trigger_mailbox.py tests/test_workflow_trigger_local_shared_runtime.py tests/test_workflow_runtime_worker_watchdog.py tests/test_workflow_runtime_event_lock_lifetime.py tests/test_workflow_trigger_source_version_recovery.py tests/test_published_inference_gateway.py tests/test_backend_worker_health.py --basetemp=.tmp/production-audit-20260909 -o cache_dir=.tmp/production-audit-20260909-cache -q --tb=short

python -m pytest tests/test_dataset_import_format_validation.py tests/test_dataset_export_format_support.py tests/test_dataset_export_delivery.py tests/test_yolo_training_queue_worker.py tests/test_yolox_conversion_worker.py tests/test_yolov8_conversion_worker.py tests/test_rfdetr_conversion_worker.py tests/test_yolo26_topk_validation.py tests/test_pose_evaluation_policy.py tests/test_model_artifact_runtime_smoke.py tests/test_rfdetr_runtime_lifecycle.py tests/test_training_telemetry.py tests/test_training_telemetry_mmap.py tests/test_task_submission_outbox_atomicity.py tests/test_task_queue_outbox_atomicity.py tests/test_task_attempt_claiming_queue.py tests/test_local_file_queue.py tests/test_resource_deletion_faults.py tests/test_database_migrations.py tests/test_runtime_daily_logs.py --basetemp=.tmp/production-audit-models-20260909 -o cache_dir=.tmp/production-audit-models-20260909-cache -q --tb=short

node frontend/web-ui/node_modules/vitest/vitest.mjs run --config frontend/web-ui/vite.config.ts
node frontend/web-ui/node_modules/vitest/vitest.mjs run --config frontend/web-ui/vite.config.ts --maxWorkers=2
dotnet test launcher/Amvar.Launcher.slnx --no-restore --verbosity minimal
```

SDK 使用已安装 MSBuild 构建 `sdks/dotnet/tests/Amvar.Vision.ContractTests/Amvar.Vision.ContractTests.vs2019.net472.csproj`，参数 `/t:Build /p:Configuration=Release /p:Platform=x64`，然后无参数执行其 `bin/Release/net472/Amvar.Vision.ContractTests.exe`。

在 CPU 发行根目录执行：

```powershell
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output json
.\python\python.exe -m pip check
```

## 7. HTTP 监听故障的后续定位

完整修复设计与实施顺序见 [Windows HTTP 接入与服务恢复方案](../architecture/platform/http-service-recovery.md)，状态为待实现。

2026-09-09 20:16 使用同一 CPU 发行 Python 3.12.13 做独立进程诊断：创建 loopback 临时端口，在该诊断进程的 Proactor accept future 注入 WinError 64，然后执行标准库原有 `_start_serving` 路径。结果：

```json
{"python":"3.12.13","listener_closed":true,"event_loop_closed":false,"errors":["Accept failed on a socket"]}
```

这是对异常处理路径的确定性复现，不是对现场网络中断来源的复现。没有访问业务端口、修改标准库文件或停止运行服务。证明接收一个连接的错误可以关闭整个监听 socket，而事件循环仍存活。

CPython 上游 [issue #93821](https://github.com/python/cpython/issues/93821) 记录了相同堆栈与监听丢失行为；[PR #124779](https://github.com/python/cpython/pull/124779) 讨论客户端在 accept 完成前断开时的处理。查询时 PR 仍为 Open，不能宣称简单升级 Python 就能修复。现场仍缺少故障瞬间的网络追踪，不能认定具体客户端或某一次断开就是触发源。

需要修正上一轮结论的范围：[FullStackController.ObserveAsync](../../launcher/src/Amvar.Launcher.Infrastructure/Runtime/FullStackController.cs) 已检查监听，缺失监听时返回 `Starting`；[HttpServiceProbe](../../launcher/src/Amvar.Launcher.Infrastructure/Http/HttpServiceProbe.cs) 也有 HTTP 检查。因此不能根据 `launcher-status.json` 的 `running` 推断桌面界面当时必然显示运行中。已确认缺口在 Python full-stack 持续监督及状态文件更新；桌面端还需验证运行后丢失监听是否被准确表现为故障，而不是长期停留在启动中。

后续实现应优先保证接入层正确关闭失败连接、保持或受控恢复监听，并补充监督层的运行就绪状态；仅吞掉异常、仅改状态文案、对业务触发无限重试都不能修复本问题。重启策略必须处理在途调用和 Broker/daemon/worker 所有权，避免重复执行。

后续 UI 检查时 5600 已由 conda 开发服务（`--reload`）监听，该进程不是原 CPU 发行实例；不能把开发服务恢复可用计作原发行实例自动恢复成功。

## 8. Hough Circles 调试图显示修复

真实页面 `workflows/graph/apps/workflow-app-20260831130620` 中，4 个 Hough Circles 调试图均出现图片底部越过节点的情况。浏览器测量发现：图片框固定为 112 CSS px，而节点内预览容器仅获分配约 96.33 CSS px（包含 padding/border）；部分长参数名称使参数行从预计的 34 px 增长为 46 px，挤压预览空间。图片框未随可用空间收缩，导致溢出。

修复只作用于 `.workflow-graph-node` 内具有图片框的预览：Grid 子项允许收缩，图片框宽高随实际区域、最大高度 112 px，保持 `object-fit: contain`；图片与 SVG 使用同一矩形。未改变模型、参数、保存的图结构、app-mode 显示槽或数据面代码。未操作页面已有的未保存修改，也未重新执行业务流程。

修复后同一真实页面 4 个图片框与图片边界一致，底部均在预览容器和节点内；完整图片等比显示。前端 geometry 与 app-mode display grid 两个现有测试文件的 2 项测试通过。浏览器布局实测是本次 CSS 回归的主要验证，单元测试不被用来证明实际布局。
