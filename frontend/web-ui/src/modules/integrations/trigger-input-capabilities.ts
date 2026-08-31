/** 高性能 Trigger 固定支持的公开输入 payload 类型。 */
export const HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS = Object.freeze([
  'image-ref.v1',
  'value.v1',
  'text.v1',
] as const)

const HIGH_PERFORMANCE_TRIGGER_KINDS = new Set([
  'zeromq-topic',
  'local-shared-memory',
])
const HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPES = new Set<string>(
  HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS,
)

/** 判断协议 Trigger 是否允许映射指定 App Entry 输入类型。 */
export function supportsTriggerInputPayloadType(
  triggerKind: string,
  payloadTypeId: string,
): boolean {
  return !HIGH_PERFORMANCE_TRIGGER_KINDS.has(triggerKind)
    || HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPES.has(payloadTypeId)
}
