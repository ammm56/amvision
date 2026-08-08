import { buildNumericInputAttributes } from '@/shared/ui/numeric-input-step'
import type { NodeParameterUiField } from '../types'

export interface WorkflowNumericParameterInputAttributes {
  min?: number
  max?: number
  step: number
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
  return buildNumericInputAttributes({
    valueKind: schemaType === 'integer' ? 'integer' : 'number',
    minimum: inclusiveMinimum,
    maximum: inclusiveMaximum,
    exclusiveMinimum,
    exclusiveMaximum,
    explicitStep,
  })
}

function readPositiveFiniteNumber(value: unknown): number | undefined {
  const parsedValue = readFiniteNumber(value)
  return parsedValue !== undefined && parsedValue > 0 ? parsedValue : undefined
}

function readFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}
