# ADR-0005：稳定 Workflow Runtime 指向不可变 App Version

- 状态：已接受并实现

## 背景

Workflow App 草稿会持续编辑，但第三方系统需要稳定的 Runtime id、Trigger id、协议地址和 SDK 配置。删除并重建 Runtime 会把内部发布变更扩散到现场系统，也无法准确追溯历史执行来源。

## 决策

1. Workflow App 保持可变草稿；发布产生不可变 `WorkflowAppVersion`。
2. Version 固定 Application、Template、公开契约、ExecutionPolicy、节点依赖、实现 identity 和内容指纹。
3. `WorkflowAppRuntime` 是稳定生产调用身份，不再增加 Workflow Channel。
4. Runtime 通过不可变 `WorkflowRuntimeRevision` 选择明确的 version，不保存 `latest`，不自动追随草稿或最新版本。
5. Runtime 保存 active revision、desired revision 和单调递增 generation；版本选择使用 `expected_generation` CAS。
6. Trigger Source 只绑定 `workflow_runtime_id`。切版不改变 Runtime/Trigger id、HTTP/ZeroMQ 地址和 SDK Runtime key。
7. 切版采用 stopped-only：停止入口并 drain、停止 Runtime、选择版本、启动验证、恢复 Trigger。
8. `select-version` 只创建新的 staged revision 并修改 desired pointer，不隐式启停 Trigger 或 Worker。
9. Worker 启动校验 version/revision/generation/snapshot fingerprint/worker instance；成功后才更新 active revision。
10. 回滚选择历史 Version，但创建更大的新 generation；历史 revision 和 Run 不修改。
11. Run 在 admission 时固定 version、revision、generation、snapshot fingerprint 和 worker instance id。
12. 正式 invoke 热路径不查询版本列表、不解析 latest、不计算发布 fingerprint，也不比较草稿。
13. Version 可归档和恢复。归档不破坏既有 active/desired revision；新建和选版只接受 published Version。

完整行为见 [Workflow App 版本管理](../architecture/workflows/app-versioning.md)。

## 未采用方案

### 新增 Workflow Channel

未采用。Runtime 已经是稳定身份，再增加 Channel 只会多出一层指针、健康状态和恢复逻辑。

### Runtime 自动追随最新版本

未采用。自动追随会让发布或重启隐式改变生产内容，破坏维护窗口、追溯和回滚。

### Trigger 直接绑定 Version

未采用。这样每次升级都要修改 Trigger，HTTP invoke、Trigger 与 SDK 会形成不同版本选择方式。

### 双 Worker 热切换

当前未采用。双 Worker 会引入资源翻倍、在途请求归属、副作用幂等和流量切分。现场本地部署采用明确的短维护窗口和 stopped-only CAS 切换。

### 复用旧 revision 或回退 generation

未采用。回滚也是新的控制操作，必须产生新的 revision 和更大的 generation，才能保持并发判断和审计顺序。

## 影响

- 第三方调用身份与 App 内容版本解耦；
- 多个 Runtime 可同时选择不同 Version；
- 切版、回滚和失败恢复都保留完整历史；
- 发布与选择增加低频控制面校验，invoke 数据面保持 LocalBuffer/Worker 高性能路径；
- 编辑器明确区分保存草稿、Preview、发布、归档和生产选版。
