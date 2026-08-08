import { describe, expect, it } from 'vitest'

import type { NodeParameterUiField } from '../types'
import { readWorkflowNumericParameterInputAttributes } from './numeric-parameter-input'

function buildField(jsonSchema: NodeParameterUiField['json_schema']): NodeParameterUiField {
  return {
    parameter_name: 'value',
    display_name: '数值',
    description: '',
    group_id: 'basic',
    order: 0,
    required: true,
    hidden: false,
    readonly: false,
    default_value: undefined,
    enum_options: [],
    json_schema: jsonSchema,
  }
}

describe('readWorkflowNumericParameterInputAttributes', () => {
  it('integer 固定使用 1 并继承范围', () => {
    expect(readWorkflowNumericParameterInputAttributes(buildField({
      type: 'integer',
      minimum: 1,
      maximum: 32,
    }))).toEqual({ min: 1, max: 32, step: 1 })
  })

  it('number 优先使用 JSON Schema multipleOf', () => {
    expect(readWorkflowNumericParameterInputAttributes(buildField({
      type: 'number',
      minimum: 0,
      maximum: 1,
      multipleOf: 0.001,
    }))).toEqual({ min: 0, max: 1, step: 0.001 })
  })

  it.each([
    [{ type: 'number', minimum: 0, maximum: 1 }, 0.01],
    [{ type: 'number', minimum: 0, maximum: 180 }, 0.1],
    [{ type: 'number', minimum: 0, maximum: 10_000 }, 1],
    [{ type: 'number' }, 0.01],
  ])('number 未声明 multipleOf 时按范围选择步长', (schema, expectedStep) => {
    expect(readWorkflowNumericParameterInputAttributes(buildField(schema)).step).toBe(expectedStep)
  })

  it('把 inclusive 和 exclusive 边界对齐到同一数值网格', () => {
    expect(readWorkflowNumericParameterInputAttributes(buildField({
      type: 'number',
      exclusiveMinimum: 0,
      exclusiveMaximum: 1,
      multipleOf: 0.1,
    }))).toEqual({ min: 0.1, max: 0.9, step: 0.1 })
  })

  it('浮点边界不会因二进制表示误差跳过有效网格点', () => {
    expect(readWorkflowNumericParameterInputAttributes(buildField({
      type: 'number',
      minimum: 0.30000000000000004,
      maximum: 0.7,
      multipleOf: 0.1,
    }))).toEqual({ min: 0.3, max: 0.7, step: 0.1 })
  })

  it('忽略非法 multipleOf 并使用范围规则', () => {
    expect(readWorkflowNumericParameterInputAttributes(buildField({
      type: 'number',
      minimum: 0,
      maximum: 1,
      multipleOf: 0,
    }))).toEqual({ min: 0, max: 1, step: 0.01 })
  })
})
