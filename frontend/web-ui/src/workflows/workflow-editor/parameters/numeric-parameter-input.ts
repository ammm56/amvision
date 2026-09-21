import { buildNumericInputAttributes } from '@/shared/ui/numeric-input-step'
import type { NodeParameterUiField } from '../types'

export interface WorkflowNumericParameterInputAttributes {
  min?: number
  max?: number
  step: number | 'any'
}

/** 仅转换编辑单位，保存值和 JSON Schema 仍使用原单位。 */
export function readWorkflowNumericDisplayDivisor(field: NodeParameterUiField): number {
  return readPositiveFiniteNumber(field.json_schema['x-ui-display-divisor']) ?? 1
}

/** 显示单位转换回原单位；整数参数按最小存储单位取整。 */
export function parseWorkflowNumericDisplayValue(field: NodeParameterUiField, value: string): number | undefined {
  if (!value.trim()) return undefined
  const divisor = readWorkflowNumericDisplayDivisor(field)
  const stored = Number(value) * divisor
  return divisor !== 1 && field.json_schema.type === 'integer' ? Math.round(stored) : stored
}

/**
 * 把节点 JSON Schema 的数值约束转换为原生 number input 属性。
 *
 * `multipleOf` 是精确步长来源。未声明时，integer 固定为 1，number
 * 按有限范围选择稳定的显示步长，避免节点编辑器使用无限制小数精度。
 */
export function readWorkflowNumericParameterInputAttributes(
  field: NodeParameterUiField,
): WorkflowNumericParameterInputAttributes {
  const schema = field.json_schema
  const schemaType = schema.type
  const explicitStep = readPositiveFiniteNumber(schema.multipleOf)
  const inclusiveMinimum = readFiniteNumber(schema.minimum)
  const inclusiveMaximum = readFiniteNumber(schema.maximum)
  const exclusiveMinimum = readFiniteNumber(schema.exclusiveMinimum)
  const exclusiveMaximum = readFiniteNumber(schema.exclusiveMaximum)
  const attributes = buildNumericInputAttributes({
    valueKind: schemaType === 'integer' ? 'integer' : 'number',
    minimum: inclusiveMinimum,
    maximum: inclusiveMaximum,
    exclusiveMinimum,
    exclusiveMaximum,
    explicitStep,
  })
  const divisor = readWorkflowNumericDisplayDivisor(field)
  if (divisor === 1) return attributes
  // 不将历史字节值对齐到 MB 网格；例如非整数 MB 必须无损显示。
  return {
    ...(attributes.min === undefined ? {} : { min: attributes.min / divisor }),
    ...(attributes.max === undefined ? {} : { max: attributes.max / divisor }),
    step: 'any',
  }
}

function readPositiveFiniteNumber(value: unknown): number | undefined {
  const parsedValue = readFiniteNumber(value)
  return parsedValue !== undefined && parsedValue > 0 ? parsedValue : undefined
}

function readFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}
