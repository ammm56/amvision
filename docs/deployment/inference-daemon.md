# 独立 inference daemon

## 进程边界

正式发布配置使用 `inference_daemon.runtime_owner=daemon`。此时 backend-service 只保留 REST、WebSocket 和持久化控制客户端，不创建模型 deployment 子进程。`backend.inference_daemon.main` 是独立入口，持有以下资源：

- detection、classification、segmentation、pose、OBB 的 sync / async deployment supervisor
- async inference gateway dispatcher
- deployment 期望状态恢复协调器
- 本地持久化控制队列 dispatcher

开发和单元测试可使用 `runtime_owner=embedded`，但该模式不是正式发布默认拓扑。

## 启动与探测

发行目录根启动器在数据库迁移成功后启动 inference daemon，并同时校验 ready 日志和真实控制队列往返，再启动 backend-service 和 worker。开发环境的唯一命令入口见 [development-environment.md](development-environment.md)，本文不重复维护启动命令。

`--probe` 通过实际控制队列往返判断 daemon 是否可达。`GET /api/v1/system/diagnostics` 的 `services.inference_daemon` 使用 1 秒短探测返回 `ok` 或 `unavailable`，不会仅根据客户端对象存在就误报健康。

## 恢复语义

每个 DeploymentInstance 的 `sync`、`async` 通道分别持久化：

- `desired_state`：API 请求的目标状态
- `observed_state`：controller 最近确认的状态
- `generation`：启停命令 fencing token
- controller lease、PID、heartbeat、重启与连续失败计数
- 下一次重试时间和最近错误

daemon 启动后扫描 `desired_state=running` 的记录并恢复进程。进程崩溃和启动失败使用指数退避；generation 防止较早的 start 结果覆盖较新的 stop 请求；数据库 lease 防止同一 deployment 被两个 daemon 同时恢复。新 daemon 接管旧 owner 时，最坏需要等待 `controller_lease_seconds` 到期，正式默认值为 15 秒。

backend-service 不可达不会改变 daemon 中已运行模型进程的期望状态。daemon 不可达时，deployment status/health 返回结构化降级状态，仍允许把持久化期望状态改成 `stopped`，避免恢复后意外拉起。

## 大输入和队列清理

控制请求不会把图片 base64 长期写入队列。backend-service 先把 bytes、BufferRef 或 FrameRef 物化到共享对象存储的 `runtime/inputs/inference-control/`，daemon 读取后清理成功请求。超时残留由 runtime storage retention 清理。

每个控制请求使用独立响应队列。daemon 定期按 `queue.response_queue_retention_seconds` 清理客户端超时后遗留的 `inference-control-response-*` 目录。请求队列使用 lease 恢复，瞬时文件系统错误只记录日志并继续消费，不会终止 dispatcher。

## 运维边界

- SQLite 正式同机多进程模式启用 foreign keys、busy timeout 和 WAL；迁移到 MySQL/PostgreSQL 时继续通过 Repository 和 Unit of Work，不在应用层增加方言 SQL。
- 根启动器仍是整套发行进程的前台生命周期管理器。需要进程自动拉起时，应由 Windows Service、systemd 或现场进程管理器监督根启动器；daemon 自身负责恢复其内部 deployment，而不是替代操作系统服务管理器。
- 独立升级前先保持数据库 schema 向前兼容，再替换 daemon 代码并重启。daemon 会按持久化期望状态恢复 deployment。
