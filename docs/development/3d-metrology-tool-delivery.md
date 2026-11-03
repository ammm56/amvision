# 点云调用工具发行

## 本轮范围

2026-11-02 按最新要求推进独立交付，不以十秒节拍或接近 1 GB 的显示索引作为前置条件。本轮实现 A11 中已有同机工具和正式工件配方的装配、搬移与调用；A10 携资源 App ZIP 只完成源码边界核对，未实现，A12 完整离线发行未声明通过。没有增加三维算法、运行队列或放宽任何质量条件。

## 实现

- 现有 `assemble-release` 增加固定文件清单，复制 Python 同机点云客户端、工件生成器、两份配方和使用说明到 `app/`；保留源码相对布局。不复制 `tests/`、输入点云、开发审计产物或缓存。
- 新入口 `launchers/client/invoke_point_cloud.py` 仅分发 `invoke` / `recipe`，复用 `resolve_app_root`、`run_python_module`、ManagedProcess 和既有整组停止。没有新 Supervisor、常驻服务或独立 IPC 实现。
- 发行 manifest 增加 `point_cloud_tools` 文件清单、长度与 SHA256；`validate-layout` 在原有运行时检查中拒绝缺文件、错摘要和未知清单。缺少这项清单的开发发行目录须从源码重新装配，不手工补发布目录代码。
- 生成器仍输出原 `amvision.workflow-app-document.v1`。文件/数组与完整显示/仅数值四种组合复用同一配方，50 项规则、算法参数和测量证据不改。默认拒绝覆盖，显式 `--overwrite` 才替换。
- 客户端仍使用目标安装的共享内存和 Broker 配置。当前 route generation、source_id、超时由调用方显式提供，成功/拒绝/异常沿原 ACK/取消协议收尾，不自动重试。

使用方式见[同机工具](../../runtimes/clients/point_cloud/README.md#发行目录调用)和[工件配方](../examples/workflows/lithium-workpiece.md)。这是随平台 Python 的调用工具，不是另一个独立 SDK；Windows .NET SDK 边界不变。

## 验证口径

测试使用开发解释器或隔离 venv 显式执行搬移后的工具，清除开发 `PYTHONPATH`、用户 site 和业务 `AMVISION_` 环境覆盖，运行目录与源码隔离。装配后改为带空格目录，核对导入来源确实位于新包。Ubuntu 测试输出位于原生文件系统。

覆盖四种生成配方逐字段一致、默认禁止覆盖、显式覆盖、缺发行解释器拒绝、缺源文件拒绝、清单缺失/重复/未知路径/损坏，以及 `validate-layout` 接线。Windows 另通过搬移后的 CLI 调用正式发布 Runtime/Trigger，核对正常响应、过期 generation、错误长度和调用后资源归零。测试不代替最终离线包原生依赖及完整工件验收。

本轮未修改前端，不重复页面、完整云数值、P99 或长稳测试。前序完整工件和 1 GB 输入验证仍作为各自历史记录，不计入本轮新通过数。

### 结果

- Windows 装配、运行时、配方及工具回归 43 项通过，追加的 validate-layout 接线 1 项通过；真实发布与客户端组合 2 项通过，共 46 项。定向 Ruff 与 `git diff --check` 通过。
- WSL Ubuntu 原生目录工具回归 9 项通过，包含实际进程启动、四种配方生成、拒绝覆盖、搬移导入和失败路径。首次临时环境缺少项目既有 jsonschema 依赖导致 2 项失败；仅补齐隔离 venv 依赖后通过，没有删断言、添加兼容代码或修改系统 Python。
- Ubuntu 本轮未重跑真实 Runtime/完整样本，Windows 的真实调用使用三点协议样本用于客户端/资源生命周期验证，不能描述为本轮完整工件测量或离线发行已验收。

主要命令：

```text
python -m pytest tests/test_point_cloud_delivery.py tests/test_metrology_workpiece_delivery.py tests/test_release_assembly.py tests/test_release_runtime_validation.py -q
python -m pytest tests/integration/metrology3d/test_delivery_client.py tests/integration/metrology3d/test_python_client.py -q
python -m pytest tests/test_point_cloud_delivery.py::test_runtime_validation_includes_tool_inventory -q
```

Windows 分别使用 `.tmp/delivery-unit`、`.tmp/delivery-published`、`.tmp/delivery-layout`；WSL 使用原生目录临时 venv 和 `--basetemp`。收尾已确认测试进程退出，删除上述测试产物、缓存和临时 venv，仓库 `.tmp/` 为空；Ubuntu 恢复原先停止状态，其他发行版不动。不保留测试包作为正式发行物。没有启动 Vite 或监听 5620/5621，没有操作业务 5600/5601 或现有发布目录。

## 后续固定范围

1. **A10 携资源配方。** 复用 `collect_measurement_references`、现有点云 ZIP、资源校验和 App/Template bundle journal。仍需实现父资产闭包、完整身份与摘要映射、流式包限额、空目标导入、回滚/崩溃恢复及编辑器入口。现有单资产 ZIP 只含父引用，不能当作完整携资源包。动态输入工件配方不含资产，不应自动附带原云。
2. **A12 离线包。** Windows 工具清单接通不代表 bundled Python/Open3D/受控 wheel/前端/服务完整包已验收；Ubuntu CPU profile、装配及运行时检查仍须沿现有发行器补齐。Ubuntu NVIDIA 未实现前仍保留预留状态。
3. **A13 冻结验收。** 同一候选验证实际交付图、容量故障、显示、搬运、离线运行和停止回收。十秒和近 1 GB 显示索引保持待验收，不阻塞前两项，不新增并行调度或缩减测量输入来冒充通过。

A10 的资源事务不能简单在 API 中循环导入后保存 App：中途失败会留下资源，重启还可能丢失清理信息。现有 bundle journal 已支持四份 App/Template 权威文档的持久原像与恢复，应在该事务内纳入新资产；资源服务已有项目写锁，保存资源和模板都可能取锁，接入时必须避免重复获取跨进程文件锁。这里记录真实复用边界，不提前声称这条链路已实现。
