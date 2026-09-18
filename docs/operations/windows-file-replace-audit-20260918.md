# Windows 文件替换故障修复与验证

## 问题与根因证据

此前百万条日志测试曾在替换汇总 JSON 时发生 `PermissionError: [WinError 5]`。历史记录没有占用句柄或进程追踪，不能认定那一次由哪个进程造成。

本次在当前 Windows / 本地 NTFS 环境可重复验证了代码中的同类缺陷：

1. 用普通 Python `open('rb')` 持有目标文件，再执行原来的 `os.replace`，稳定得到 WinError 5；关闭读者后成功。
2. 仅把读取改成 `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE`，原来的 `os.replace` 在本机仍不能覆盖已打开的目标文件。
3. 共享读取配合 `SetFileInformationByHandle(FileRenameInfoEx)` 的 `REPLACE_IF_EXISTS | POSIX_SEMANTICS`，可在读者持有旧文件时发布新文件。旧句柄仍读取完整旧版本，新打开读取完整新版本。

项目原本允许显示端无写锁读取提交文件、汇总检查点；这种并发模型与原 Windows 读写 API 的语义不匹配。冲突发生在控制文件目录项替换，不是 JSONL 数量超限，也不是计数公式、模型推理或 LocalBuffer 出错。

Windows 语义依据：[CreateFileW 共享模式](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[文件重命名 POSIX 语义](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)。不采用先删除目标再重命名，也不采用存在多步部分失败状态的 ReplaceFileW 来代替单步发布。

## 修复边界与步骤

1. 将共享读取和 Windows 原子替换集中到 `backend/service/infrastructure/filesystem/shared_files.py`；POSIX 平台保留 `os.replace`。
2. JSONL commit/intent、File Summary 检查点及文件输出 journal 使用共享读取；原子写使用同卷完整临时文件、flush/fsync 和单步发布。
3. 对象存储共享快照复用同一读取实现。原来的句柄打开失败一律包装为 FileNotFoundError，现保留真实错误类型与 WinError；本地对象存储 JSON 读取也允许并发替换。
4. 既有基础文件替换 helper 复用新原语；既有对象存储/任务队列的有界错误重试策略不变。JSONL 正常路径与失败路径均不增加自动重试、等待或队列。
5. 原子写记录失败路径和阶段；临时文件清理失败、提交读回失败作为附加诊断，不能覆盖最初异常。
6. `overwrite=False` 使用原子“不覆盖发布”，消除检查目标不存在后被其他创建者插入的覆盖竞争。
7. Append JSONL / Read JSONL / File Summary 在节点边界将系统 IO 异常分类。正常数据与 schema 不变；错误增加可诊断的 code/details，不把失败视作空结果或写入成功。

未改变 Runtime/Trigger 调度、部署推理、模型输出、IPC、mmap、计数规则和记录格式；未增加数据库或后台重试任务。恢复扫描上限仍为 180 秒，并遵守更短的执行 deadline。

## 异常处理

| 场景 | 行为 |
| --- | --- |
| 平台读者同时读取 commit / checkpoint | 允许单步替换，读者保留完整旧版本，无新增等待 |
| 外部程序用不共享删除的句柄占用文件 | 返回 file_busy 或 file_access_denied，包含路径、阶段、errno、winerror |
| 文件只读、权限不足 | 不绕过属性或权限，不删除目标，不伪装成不存在 |
| 磁盘满 / 文件系统只读 / 一般 IO 故障 | 分别报告 disk_full / filesystem_read_only / file_io_failed |
| 系统或文件系统不支持原语 | 保留系统错误；明确的“不支持”错误映射为 file_operation_unsupported，无不安全降级 |
| 日志已写入、提交文件发布失败 | 返回 write_state=unconfirmed，保留 intent；不自动重跑生产调用 |
| 同一个物理追加调用恢复 | 已提交或完整未提交尾部只恢复一次，保留原有协议 |
| 汇总发布失败 | 旧检查点保持有效，后续读取从旧游标补算 |
| 清理临时文件或提交读回也失败 | 保留主错误，并附 cleanup_error / verification_error |

追加失败后的新业务调用不等于同一物理调用重试。操作人员应先核对日志、commit 和 intent，不能凭页面失败就盲目重复生产调用，也不能通过删除有未决意图的 commit 来强行恢复。永久磁盘故障、外部独占和权限问题需要排除环境原因；代码不承诺此类情况下仍能成功写入。

## 验证

测试覆盖普通句柄复现、跨进程持有旧控制文件、旧新版本完整性、外部占用后的同一调用恢复、只读属性、磁盘写入/flush 失败、清理与读回二次失败、无覆盖发布竞争、长路径/中文/非 BMP 字符、NUL 路径拒绝、句柄数量稳定和不支持的文件系统。

真实 Worker / REST / WebSocket 的文件记录显示集成测试通过；开发数据库和现场生产日志未被测试修改。最终集中回归 126 项通过（24.43 秒），修改 Python 文件的 Ruff 检查与 git diff --check 通过。实际测试系统为 Windows 11 专业版 10.0.26200 / NTFS / conda amvision。

回归命令（先执行 `conda activate amvision`）：

```powershell
python -m pytest tests/test_workflow_atomic_files.py tests/test_managed_jsonl.py tests/test_file_summary.py tests/test_file_display_nodes.py tests/test_atomic_file_replace.py tests/test_object_store_snapshots.py tests/test_object_store_port.py tests/test_local_file_queue.py tests/test_workflow_local_file_reading.py tests/test_file_display_workflow.py tests/test_file_display_api.py -q
```

百万条隔离日志复用前一轮样本，初始 1,000,030 条 / 390,011,700 字节；每条字段与现场治具记录一致。每种情况执行 100 次“追加一条 + 增量汇总”，包含实际 fsync 与路径锁。

| 场景 | 中位耗时 | P95 | 最大耗时 |
| --- | ---: | ---: | ---: |
| 顺序执行 | 18.238 ms | 21.530 ms | 23.153 ms |
| 两个进程同时读取控制文件 | 21.876 ms | 24.956 ms | 27.907 ms |

两个读取进程分别完成 869、628 组 commit/summary 读取，未遇到异常。200 次追加和归约均核对累计值，最终 1,000,230 条，总物料 24,005,520，OK 16,003,680，NG 8,001,840。该结果不包括模型推理、图片 IO 和完整页面更新，也不等于长期运行的最大耗时保证。

## 开发与发行要求

实现只使用 Python 标准库 ctypes 和 Windows kernel32，不增加 pip 包、系统 Python 或额外 DLL 要求。conda 开发与同目录 Bundled Python 共用源码；Windows 仅支持项目既定 x64 进程。

Windows 文件发布要求操作系统和文件系统支持 FileRenameInfoEx / POSIX 替换语义；当前验证为 Windows 本地 NTFS。网络共享、其他文件系统及旧系统须单独验证，不能等同于本地 NTFS 的验收。原子临时文件与目标必须同卷；不会跨卷复制降级。

变更需由重新启动的服务/Worker 加载。发行包通过正常 assemble-release 重新组装，不手工修改生成目录。无需数据迁移、节点参数迁移或生产日志重建。
