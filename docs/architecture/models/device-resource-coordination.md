# GPU 设备资源协调

## 适用范围

设备资源协调只处理 NVIDIA CUDA GPU 和 MIG 实例。CPU 不获取设备锁；OpenVINO GPU 可能是 Intel GPU，也不进入本协调器。协调目标是防止 Training、TensorRT Conversion 与常驻 CUDA Deployment 在不同 Python 进程中无意争用同一资源，同时不增加 inference 请求热路径开销。

## 稳定资源键

同一物理 GPU 或 MIG 实例必须在 backend-service、backend-worker 和 conversion 子进程中使用同一个资源键：

- 完整 `GPU-...` UUID；
- 完整 `MIG-...` UUID。

`cuda:0` 只是当前进程的可见索引，不能作为跨进程资源身份。解析顺序为显式 `cuda_device_uuid_overrides`、PyTorch 设备属性、`CUDA_VISIBLE_DEVICES` 中的 UUID、`nvidia-smi`。当 `CUDA_VISIBLE_DEVICES` 使用数字重排时，先换算物理索引再读取 UUID。无法得到稳定 UUID 时明确报配置错误，不生成 hash、`gpu:` 前缀或伪造的 index 资源键。

锁文件名使用 UUID 的 SHA-256 摘要，避免文件名字符差异；摘要只用于本地锁文件名，不会写入 `CUDA_VISIBLE_DEVICES` 或任务公开诊断。TensorRT Conversion 子进程的 `CUDA_VISIBLE_DEVICES` 使用已经解析出的原始 GPU/MIG UUID，子进程内部继续使用 `cuda:0`。

## Lease 模式和生命周期

| 链路 | 模式 | 获取边界 | 释放边界 |
| --- | --- | --- | --- |
| Training | `exclusive` | worker 开始执行训练任务、进入模型 runner 之前 | runner 成功、失败或异常退出后的上下文清理 |
| CUDA Conversion | `exclusive` | conversion attempt 受监督子进程启动之前 | attempt、staging 校验和原子发布完成或失败 |
| 纯 CPU Conversion | 无 | 来源 runtime 和目标构建都不使用 CUDA 时不获取锁 | 不适用 |
| CUDA Deployment | `shared` | deployment 子进程启动之前 | 显式停止、启动确认失败、放弃自动恢复或 service 关闭 |
| inference 请求 | 无新增锁 | 直接使用 deployment 已持有的 reservation | 不适用 |

多个 CUDA Deployment 可以同时持有 `shared` reservation。任意 `shared` holder 存在时，Training 或 CUDA Conversion 的 `exclusive` lease 会被拒绝；反过来，`exclusive` holder 存在时新 CUDA Deployment 也会被拒绝。CPU Deployment、CPU Training 和纯 CPU Conversion 不参与这组锁。

Deployment 子进程异常退出且允许自动恢复时，父进程继续持有原 shared reservation，避免恢复间隙被独占任务抢占。显式停止或不再恢复时才释放。该 reservation 不限制 Deployment 数量、显存份额、CUDA stream 数量或 inference 并发；这些容量仍通过目标机器 benchmark 和 soak 决定。

## 跨进程实现与崩溃恢复

- Windows 使用 `LockFileEx` 的 shared/exclusive 非阻塞文件锁。
- POSIX 使用 `flock` 的 `LOCK_SH`/`LOCK_EX` 非阻塞文件锁。
- lease 由打开的 OS 文件句柄持有，不依赖进程内 `Condition`、PID 文件或定时续约。
- 进程崩溃或被强制终止后，操作系统关闭句柄并自动释放 lease。
- 锁目录中的 `.lease` 文件可以长期存在；是否占用由 OS handle lock 决定，不能通过文件是否存在判断 busy。

该实现不在每次 inference 请求上打开文件、获取锁或轮询。Deployment 只在启动/停止边界操作一次 lease。

## Busy 和 timeout 策略

默认策略是立即拒绝，不建立额外资源等待队列：

```json
{
  "root_dir": "./data/runtime/device-leases",
  "exclusive_acquire_timeout_seconds": 0.0,
  "shared_acquire_timeout_seconds": 0.0,
  "poll_interval_seconds": 0.05,
  "cuda_device_uuid_overrides": {},
  "conversion_cuda_device": "cuda:0"
}
```

- `exclusive_acquire_timeout_seconds` 用于 Training 和 CUDA Conversion。
- `shared_acquire_timeout_seconds` 用于 CUDA Deployment 启动。
- `0.0` 表示首次冲突立即返回 `device_lease_unavailable`。
- 大于零时只在调用边界做有界轮询，超过时间返回相同稳定错误码，不无限等待、不自动重试、不切换设备以外的执行链路。
- `auto` Training 会在同一个总 timeout 内尝试所有可见 GPU/MIG；显式 `cuda:n` 只尝试指定资源。

backend-worker 在 `config/backend-worker.json` 的顶层 `device_leases` 读取配置；backend-service 在 `deployment_process_supervisor.device_leases` 读取配置。两个进程组必须使用同一个 `root_dir` 和一致的 UUID 映射。

## 状态与诊断

一次成功 lease 记录：requested/resolved device、原始 UUID/MIG UUID、模式、用途、owner id、PID、线程 id、获得时间和等待时间。Training 把该信息写入任务 metadata；Conversion 写入转换结果 metadata；Deployment health 返回当前 lease 和本 service 进程的 provider snapshot。

冲突错误包含 requested/resolved device、资源键、请求模式、用途、owner、timeout、已等待时间和锁路径。provider snapshot 只表示当前进程持有的 lease；其他进程的 holder 由 OS 锁裁决，不能根据本进程 snapshot 推断全局空闲。

## 验收边界

实现必须持续通过以下门禁：

- 同进程和跨进程 shared reservation 并存；
- shared/exclusive 双向冲突；
- busy timeout 有界；
- 持锁进程崩溃后 OS 自动释放；
- CPU 路径不创建或持有 GPU 锁；
- Training、CUDA Conversion 和 Deployment 生命周期集成测试；
- Deployment inference 请求路径没有新增 lease 获取；
- 无 GPU 的测试环境使用固定测试 UUID 验证协调协议；真实 GPU/MIG UUID 枚举、驱动行为和持续负载仍需在目标 NVIDIA 机器执行硬件 smoke 与 soak。
