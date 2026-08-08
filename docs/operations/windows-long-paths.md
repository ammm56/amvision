# Windows 长路径支持

## 适用范围

Windows 默认的传统 `MAX_PATH` 限制会使深层数据集、模型产物、任务日志和原子临时文件在约 260 字符处失败。Ubuntu 和 macOS 不需要设置系统策略。

项目采用两层处理：

- 本地 ObjectStore 的文件操作使用 Windows extended-length path；
- 本地队列和 ObjectStore 的原子替换统一对 WinError 5、32、33 短暂占用做有界退避重试，持续占用仍明确失败；
- Windows 发行包首次启动检查系统 `LongPathsEnabled`，未开启时请求 UAC 管理员权限并执行独立启用脚本。

## 独立执行

开发目录：

```powershell
conda activate amvision
python runtimes/launchers/enable_windows_long_paths.py
```

发行目录：

```powershell
.\python\python.exe launchers/enable_windows_long_paths.py
```

脚本已经具有管理员权限时直接修改注册表；没有管理员权限时显示标准 Windows UAC 确认框，启动同一脚本的管理员进程并等待结果。

只检查、不修改：

```powershell
python runtimes/launchers/enable_windows_long_paths.py --check
```

输出为 JSON，`enabled=true` 表示策略已开启。注册表位置为：

```text
HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem
LongPathsEnabled = 1 (REG_DWORD)
```

## 首次启动行为

Windows 发行包的 full、service、worker 和 inference daemon launcher 在启动业务进程前执行检查：

1. 已开启时直接继续；
2. 未开启时执行独立启用脚本并显示 UAC；
3. 设置成功后当前 launcher 以退出码 78 结束，并提示重新启动；
4. 第二次启动复核通过后再启动服务和常驻进程。

要求重新启动 launcher 是为了避免 Windows 进程已经缓存旧注册表值。系统重启通常不需要，但企业组策略覆盖本机设置时需要由管理员处理策略来源。

## 验证

```powershell
python runtimes/launchers/enable_windows_long_paths.py --check
```

还应验证项目存储根下超过 260 字符的 JSON 和二进制文件可以完成创建、原子替换、读取和清理，并验证 Windows 短暂 sharing violation 不会使事件或队列终态丢失。相关自动化测试位于 `tests/test_dataset_storage_zip_limits.py`、`tests/test_atomic_file_replace.py` 和 `tests/test_local_file_queue.py`。
