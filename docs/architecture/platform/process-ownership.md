# 进程归属与恢复准入

## 分层

业务、启动器和公共控制接口统一，不引用 Windows Job、POSIX signal 或父子进程快照回收代码。平台差异仅位于 `backend/runtime/processes/`。

- `ManagedProcess`：命令启动门、输出与退出码、停止及正常完成后的组回收。
- Python script/module 入口显式使用 `python_entrypoint=True`，登记完成后在同一个 PID 中执行目标，保留 `__main__`、argv、解释器与 multiprocessing spawn 语义，不常驻额外等待进程。任意外部命令仍由同一个受管入口建立归属。
- `managed_spawn_context()`：保留 multiprocessing spawn 的 Queue、Pipe、Event，统一 Process 生命周期。
- `ProcessTreeSupervisor`：保留既有 deadline、取消和有界日志契约，复用受管命令入口。
- `OwnershipScope`：登记组身份与父组关系，封闭停止中的登记，核对旧组清空后才允许释放资源和恢复。
- full 启动的 Python 角色 launcher 在解释器路径完全一致、当前 PID 确为已登记组根且停止封闭未开始时，原位执行业务 module。独立 launcher 或不同解释器仍建立正式受管子组；无效归属不能当作未受管运行降级。
- Windows 适配器复用既有 Job Object，增加命名引用、成员查询和整组退出确认。
- POSIX 使用独立 session/process group 与组内身份守护。根进程退出后，通过守护的 PID、内核出生标识和 PGID 核对身份；owner 控制管道 EOF 时结束全组。Linux 出生标识由 boot ID 与 `/proc/<pid>/stat` 的 starttime 计数组成，不使用随墙钟调整变化的 boot_time 换算。

POSIX 成员查询以 OS 维护的 PGID 为准，不从父 PID 推断后代。新建 session 的嵌套受管组通过启动登记关联。以上机制不是恶意代码沙箱；受信任节点不得自行脱离受管组，新建独立进程必须使用统一入口。

## 顺序

1. 建立启动门，业务 target 尚不运行。
2. 建立平台归属并登记父组、代次与可重开的引用。
3. 确认登记后放行；失败则取消启动。
4. 停止时封闭相关登记，从最内层向外结束各组并实际等待退出。
5. 未清空、身份不明或查询失败时保留记录和资源所有权，拒绝声明成功或恢复替代实例。
6. 确认清空后才清理 IPC、设备 reservation、运行状态及子域登记。

根 PID 退出不表示后代退出。单独停止已验证的 owner 仅用于阻止继续调度，不能代替整组确认。Deployment、Workflow、Preview、Broker、开发 Worker Supervisor 和 full launcher 共用该边界。模型计算、协议 schema、Buffer identity fence 和业务恢复预算保持原模块职责；归属查询不进入每帧推理路径。

## 升级与平台

full 内部状态为 `amvision.full-supervisor-state.v3`，包含 `ownership_scope`、组件 `group_id` 和完整进程 `birth_identity`；桌面启动器同步使用该格式。Broker owner 元数据版本为 3，独立服务归属侧文件为 `amvision.service-ownership.v2`。启动状态为 `amvision.launcher-status.v3`，只读进程检查与停止目标分别为 `amvision.launcher-process.v2`、`amvision.launcher-stop-target.v2`。这些内部契约必须随同一个发行包更新，不接受旧格式降级。

进程组和 scope 内部记录分别使用 `amvision.process-group.v2`、`amvision.process-scope.v2`，统一通过进程适配层读取出生标识。旧 v1 墙钟身份记录拒绝恢复，不加容差或兼容降级；升级前必须完成旧运行停止。此次调整不改变对外显示的进程创建时间及 IPC 数据协议。

旧 PID-only 状态不转换，不保留 taskkill 或 psutil 后代快照降级。升级前必须使用旧版本停止原运行并确认进程退出，再部署新版本；不能覆盖活动发行目录或删除仍使用中的锁、mmap 和状态文件。

开发使用 conda `amvision`，发行使用同目录 Python。依赖为标准库、既有 psutil 及 OS 能力，不增加第三方常驻服务、系统 Python 或 Node 要求。现有 release 组装器的 Windows profile 范围与底层运行时支持是两层边界。

公共启动器按当前平台选择 `python/python.exe` 或 `python/bin/python3` / `python/bin/python`，显式解释器路径保留 venv 符号链接位置，发行目录缺失解释器时直接拒绝启动。当前验收目标为 Windows 和 WSL Ubuntu；不能把进程层测试视为 Ubuntu 完整 GPU 发行验收。

Linux mmap byte-range guard 使用绑定独立打开句柄的 OFD 锁，不使用进程级 `lockf`。同进程不同线程/句柄也必须互斥，关闭无关句柄不能释放正在使用的锁。Windows 保留既有 byte-range 机制；该数据面适配器当前不声明 macOS 已验收。依据：[Linux fcntl locking](https://man7.org/linux/man-pages/man2/F_OFD_SETLK.2const.html)。

Workflow Trigger poller 停止超时必须保留线程、mailbox 和 executor，并拒绝重新启动；确认线程退出并完成 stop 后才允许恢复。图片请求的 Runtime 准入、输入 handoff 与执行共用既有有界 executor 槽位，poller 不同步等待准入；取消先到也不能在该槽位退出之前释放在用输入。

Outbox、DeploymentRuntimeReconciler 和 Deployment supervisor 的停止同样必须确认执行线程退出。停止超时保留线程及其依赖；线程自行退出后仍须显式完成 stop，不能直接 start。Outbox 完成已经领取的批次，不再领取下一批；协调器和 supervisor 停止后不得启动下一代模型。此边界没有新增业务等待队列。

Workflow manager 采用相同的确认边界：先关闭准入并唤醒 monitor，再确认 monitor、recovery、异步完成回调及全部 Runtime 进程组退出，最后关闭 cleanup client。首轮恢复与停止并发时，启动不得继续发布 monitor；有界等待未完成则保留停止标记。组停止或 client close 的错误必须传给上层并保留可重试引用，不能继续释放 Broker、数据库或恢复接入。停止失败后，即使旧线程稍后自行退出，也须再次成功完成 stop。

API 与 inference daemon 资源容器采用统一生命周期阶段，启动失败或进入停止后禁止再次复用。停止可重试；生产者停止失败时不得关闭下游模型进程、Broker 或数据库。已经成功 drain 的资源不重复 drain。backend 必须枚举五类任务的全部 sync/async supervisor 和 gateway，不能根据不统一的属性命名猜测成员。

API 状态采集也属于依赖使用者：正常退出与 HTTP recovery 排空均须先确认采集线程退出。Training Telemetry 接收线程退出之前不得关闭 reader 或业务 broker；Worker heartbeat 必须等在途写入结束后才能发布 stopped。停止失败保留线程及资源引用，禁止直接 start；确认清理完成后才解除组件的停止状态。

Inference Mailbox 先发布 closed fence，使 client 立即取消；dispatcher 和在途 handler 都退出后才释放 mapping、executor 和 owner。状态发布线程停止超时也必须向上传递。daemon 启动回滚与正常停止共用同一依赖顺序，不能简单倒序启动列表：Mailbox owner 在最早准备，但其请求线程在后续启动，必须在模型消费者之前停止。

独立服务接替、Broker 接管和 full launcher 都使用同一内核出生标识；公开 create_time 仅用于展示。进程适配器将 Linux 非子进程的 zombie 视为执行已结束，不等待其父进程回收 PID；后续仍必须确认登记组为空。权限或身份读取失败不得被解释为进程已退出。

PREPARE 的 Broker 分配也复用该执行器，容量不足立即拒绝；没有新增执行队列或线程池。分配 Future 完成且槽位归还后，poller 才发布 WRITING；取消或停止期间迟到的 allocation 仍按原 receipt 回收。整组停止与恢复准入不依赖这些性能优化。

## 验证

`tests/test_managed_process.py` 与 `tests/test_process_tree_supervisor.py` 覆盖中间进程先退出、根进程退出、重开归属停止、owner 崩溃、嵌套组、兄弟组隔离、登记失败、停止封闭、退出码和输出。

2026-10-14 的 Windows 对照复现中，HEAD taskkill 与未提交快照 helper 都返回成功但留下孙进程；既有 Job 实现正确回收。修复的是未统一的生命周期入口，不是否定已有跨平台架构或重做模型执行器。证据为 `data/acceptance/process-ownership-20261014/baseline.json`。

本轮 Windows 与 Ubuntu WSL 有真实进程证据，macOS 尚无实机证据。2026-10-15 后台生命周期与身份补充修复后的组合回归为 Windows 751 passed、13 skipped，WSL Ubuntu 335 passed、16 skipped，包含真实孙进程回收、恢复准入、Linux OFD 锁、本地队列、mmap 生命周期、Workflow mailbox、状态采集和训练遥测。Windows 缺少符号链接权限的越界测试由 WSL 实际执行；Windows extended-length 前缀用例不在 Ubuntu 假执行。平台专用跳过项不计为通过。Linux 墙钟变化的证明覆盖本轮相关内核身份调用链，不代表所有公开时间字段都经过时钟跳变认证。不能扩大为 Linux GPU 推理或完整发行已验收。性能、资源和长期稳定结论以独立验收报告为准。

平台依据：[Python subprocess](https://docs.python.org/3.12/library/subprocess.html)、[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
