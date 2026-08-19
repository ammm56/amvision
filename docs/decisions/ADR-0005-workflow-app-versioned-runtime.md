# ADR-0005：以稳定 WorkflowAppRuntime 指向不可变 Workflow App 版本

## 背景

当前 WorkflowAppRuntime 在创建时固定 FlowApplication、WorkflowGraphTemplate 和可选 WorkflowExecutionPolicy snapshot。后续继续编辑 Workflow App 不会改变已有 Runtime，这个隔离行为是正确的。

当前缺少生产版本切换能力。修改 Workflow App 后，如果需要让生产调用使用新内容，只能删除或另建 Runtime 和 Trigger，导致 `workflow_runtime_id`、TriggerSource id、协议地址和第三方 SDK 配置发生变化。现场系统需要稳定调用地址，同时还要保留旧实现、准确回滚和多个 Runtime 使用不同版本的能力。

需要决定：

- 稳定调用身份放在 Runtime 还是新增 Workflow Channel
- Workflow App 发布物是否允许修改
- Runtime 是否自动追随最新版本
- 第一阶段采用停机切换还是双 worker 热切换
- 回滚是否恢复旧 generation

## 决策

1. Workflow App 保持可变草稿，发布产生不可变 `WorkflowAppVersion`。
2. `WorkflowAppVersion` 同时固定 Application、Template、公开契约、ExecutionPolicy 和节点/节点包依赖，不能只使用 `template_version` 代替。
3. 不新增 Workflow Channel。`WorkflowAppRuntime` 本身就是 TriggerSource、SDK 和第三方系统绑定的稳定生产调用身份。
4. Runtime 通过不可变 `WorkflowRuntimeRevision` 选择准确的 `workflow_app_version_id`，不保存 `latest` 或自动追随最新版本。
5. Runtime 维护 active revision、desired revision 和单调递增 generation。选择版本使用 `expected_generation` 做 CAS。
6. TriggerSource 始终绑定 `workflow_runtime_id`，不绑定版本或 revision。版本切换不改变 Runtime/Trigger id、HTTP/ZeroMQ 地址和 SDK Runtime key。
7. 第一阶段只实现 stopped-only 切换。操作顺序固定为停用 Trigger、停止并 drain Runtime、选择版本、启动验证、恢复 Trigger。
8. `select-version` 只写入新 staged revision 和 desired pointer，不隐式启停 Trigger，也不隐式启动 worker。
9. 启动验证成功后才更新 active revision；失败保留最后成功 active revision。
10. 回滚选择历史 WorkflowAppVersion，但创建新的、更大 generation revision，不修改历史，不回退 generation。
11. WorkflowRun 在请求接收时固定 revision、version、generation 和 snapshot fingerprint。
12. 生产请求热路径不查询版本列表、不解析 latest、不计算发布 fingerprint 和不比较契约。

完整字段、流程、API 版本边界、迁移和验收门禁见 [Workflow App 版本管理与 Runtime 稳定切换设计](../architecture/workflow-app-versioning.md)。

## 备选方案

### 新增 Workflow Channel

未采用。现有调用已经通过 WorkflowAppRuntime，新增 Channel 会形成 `Trigger -> Channel -> Runtime -> Version`。这会增加一套指针、健康状态和恢复逻辑，但没有增加稳定地址或多版本能力。

模型 Deployment Channel 与 Workflow 不同。模型调用需要在多个不可变模型 deployment/revision 之间提供稳定模型名；Workflow 已有长期 Runtime 资源承担这个职责。

### Runtime 自动追随最新版本

未采用。自动追随会让保存或发布操作隐式改变生产执行内容，无法准确控制维护窗口，也会让重启后的实际版本依赖当时的最新指针。

### TriggerSource 直接绑定 WorkflowAppVersion

未采用。这样每次升级都要修改 Trigger，并使 HTTP invoke、Trigger 调用和 SDK 配置使用不同的版本选择方式。Trigger 只负责创建 run，版本选择属于 Runtime。

### 第一阶段直接实现双 worker 热切换

未采用。双 worker 会增加资源翻倍、在途请求归属、Trigger 流量切分、副作用节点幂等和失败回滚状态。当前本地工业视觉场景先采用短维护窗口和显式停机切换。

### 回滚时重新激活旧 revision 或回退 generation

未采用。历史记录复用会破坏操作顺序和并发判断。回滚仍然是一次新的版本选择，必须产生新的 revision 和 generation。

### 继续通过删除并重建 Runtime 更新

未采用。Runtime/Trigger id 和 SDK 配置变化会把内部发布操作扩散到第三方现场系统，增加生产变更风险。

## 影响

- 需要新增 WorkflowAppVersion 和 WorkflowRuntimeRevision 持久化资源。
- WorkflowAppRuntime 需要 active/desired revision 和 generation 字段。
- WorkflowRun 需要记录完整版本来源。
- 编辑器需要区分保存草稿、Preview 和发布版本。
- Runtime 页面需要提供 stopped-only 版本选择和契约差异展示。
- 公开创建接口从 `application_id` 转向必填 `workflow_app_version_id` 是破坏性变化，必须通过新 API 大版本或明确兼容期落地。
- 现有 Runtime 必须从自己的 snapshot 迁移，不能用迁移时最新草稿覆盖；迁移保留 Runtime/Trigger id 和协议地址。
- 版本发布和 Runtime 启动增加控制面校验，但正式 run 热路径保持当前高性能数据链路。

## 后续动作

1. 实现不可变 WorkflowAppVersion 发布和读取。
2. 实现 Runtime revision、generation CAS 和版本来源记录。
3. 实现 stopped-only 选择、启动 fingerprint 校验、失败恢复和回滚。
4. 实现公开契约与 Trigger mapping 兼容性检查。
5. 实现保留 Runtime/Trigger id 的幂等迁移。
6. 完成 E2E、故障注入、重启恢复和持续负载验收。
