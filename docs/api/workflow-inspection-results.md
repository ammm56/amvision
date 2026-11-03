# Workflow 判定结果契约

2026-10-31。开发中的量值判定与结果记录统一 v1，不接受旧二态记录或保留执行别名。三维测量契约仍为 v1；实际投产节点的变更保护见下文。

## 三种独立状态

| 层级 | 字段 | 含义 |
| --- | --- | --- |
| 执行 | WorkflowRun.state | succeeded/failed/cancelled 等，描述图是否执行完成 |
| 测量 | NumericItem.valid/value/reason | 是否存在可用物理量；缺测 value=null，不补 0 |
| 产品判定 | summary/record.state | ok/ng/invalid，分别为合格、超差、无法判定 |

执行 succeeded 可以得到 invalid 产品判定。几何 valid 不表示产品合格，也不表示实体精度已获计量验收。传输或设备写入失败不能改写已经计算的产品状态。

## Check Limits

节点 `core.rule.check-limits` 继续接收 `numeric-table.v1` 和配方 rules。输出 result 为放行布尔，summary 是完整 `amvision.limit-check.v1`；不经过布尔往返后重建三态。

- 必检无效、缺项或单位不符优先得到 invalid，保留其他已超差项；没有必检项也为 invalid。
- 所有必检有效时，任一超限得到 ng，否则为 ok。可选项保留自己的结果但不改变必检结论。
- 只有 ok 可令 passed=true。false 同时包含 ng 与 invalid，不得用 not passed 生成“NG 数”。
- 区间包含端点由 include_lower/include_upper 决定；错误配置仍是配置错误，不自动交换上下界。

summary 字段：format_id、observation_id、state、passed、reason、items、required_count、required_ok_count、required_ng_count、required_invalid_count、optional_count。reason 为 null、no_required_checks、required_invalid 或 required_out_of_limits。items 每项完整保存 item_id、required、state、passed、valid、value、unit、actual_unit、lower、upper、include_lower、include_upper、reason。计数、状态及值与规则必须一致；消费者拒绝篡改摘要。

## Result Record

节点 `core.output.result-record` 的 decision 输入必须是上述完整 summary，conditions 自动保留该摘要。输出固定 `format_id=amvision.result-record.v1`，state 与 passed 必填；可选 reason、metrics、conditions、metadata、alarm、image、video。invalid 必须带非空原因，完整 conditions 与记录状态冲突会拒绝。没有 ok_ng/ok 兼容字段。

Process Decision 继续用于明确布尔条件的 all/any，不把任意 false 当作缺测。其纯布尔 decision/summary 输出及 OK/NG Decision 保持原义；生成的标准结果记录使用当前 state/passed。三态量值不要先接这两个布尔节点。

Batch Result Summary 将 ok/ng/invalid/unknown 分开计数；invalid 不计为 ng，良率分母保留全部记录。预计算汇总同样校验计数和比例，不能注入不一致的高良率摘要。

## 真实调用示例

保存并发布 [inspection_limits](../examples/workflows/inspection_limits.application.json) 及其 [template](../examples/workflows/inspection_limits.template.json)，创建 Runtime 后，通过现有 invoke/runs 或 App Mode 提交：

```json
{
  "input_bindings": {
    "measurements": {
      "observation_id": "sample-001",
      "items": [{"item_id": "d", "unit": "mm", "value": null, "valid": false, "reason": "missing_surface"}]
    }
  }
}
```

示例闭区间 0.95–1.05 mm 仅用于规则演示，不是当前工件公差。输入 1.000000001 得到 ok，1.25 得到 ng，上述缺测得到 invalid/required_invalid；原始 missing_surface 保留在 conditions.items。输出 inspection 为记录，display 为同次判定表。App Mode 显示合格/超差/无法判定；普通 bool 表格显示不改变。显示舍入不改变保存量值。

## 文件、数据库、HTTP 与 PLC

JSON/CSV/SQL/HTTP 复用现有节点与权限；来源字段改为 state/passed，null 原样保留。外部列名和业务 JSON 目标名不自动迁移，必须审核映射。SDK 保留完整 JSON，不把未知状态视作放行。CSV 的空字段并非数值 0，接收方应连同 valid/state/reason 解释。

PLC result signals 的 result.state 整数映射必须显式配置三个不同且可编码的 state_values，例如 `{"ok":7,"ng":8,"invalid":9}`。代码只是演示，不是现场地址/协议默认。字符串目标可直接映射 state；不能用布尔真值映射状态，也不能通过本次请求覆盖状态字段。配置字段及写类型以节点 Catalog 为准。

所有启用映射在连接前完成来源解析和编码校验。null、越界、不可编码导致整次拒绝，不先写部分字段；continue_on_error 不绕过这一检查。实际连接后发生的设备故障仍采用原继续/停止策略，顺序写多寄存器不是原子事务。需要设备事务/握手时由显式配方及设备协议负责，软件测试不代替现场 PLC 联调。

## 升级与恢复

Check Limits、Result Record、Process Decision、Batch Record、Batch Result Summary、PLC result signals 标记 requires_execution_review。现有 AppVersion 冻结依赖参与选版、启动、worker READY 前校验；定义/版本/包身份不匹配返回 HTTP 409，details.requires_republish=true 及受影响 node_type_ids。旧发布仍可查看，审核草稿后创建新发布；不删除历史、不猜测旧 NG 的原因、不保留旧执行分支。

只读核对的摆盘机发布模板未引用上述改义节点，但引用 Value Preview，因此该显示节点增加新格式时实现版本明确为 2.0.0。普通值/布尔行为不变，无关发布不强制停用；格式版本仍为 v1。节点定义/manifest 身份不等于所有 Python 源文件内容锁定，后续实现变化必须维护版本，离线发行另行验收。

软件验收与限制见[三态验收记录](../development/3d-metrology-decisions.md)。
