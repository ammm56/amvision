import type { WorkflowJsonObject } from '../types'

/** 只展开唯一非空分支；复合联合类型不能任取首分支作为标量。 */
export function rowScalar(schema: WorkflowJsonObject): WorkflowJsonObject & { nullable: boolean } {
  const union = schema.anyOf ?? schema.oneOf
  if (Array.isArray(union)) {
    const choices = union.filter((value): value is WorkflowJsonObject => value !== null && typeof value === 'object' && !Array.isArray(value))
    const nonNull = choices.filter(choice => choice.type !== 'null')
    const nullable = choices.some(choice => choice.type === 'null')
    if (choices.length !== union.length || nonNull.length !== 1) return { ...schema, type: undefined, nullable }
    const resolved = rowScalar(nonNull[0]!)
    return { ...schema, ...resolved, nullable: nullable || resolved.nullable }
  }
  const types = Array.isArray(schema.type) ? schema.type : [schema.type]
  const nonNull = types.filter(type => type !== 'null')
  return { ...schema, type: nonNull.length === 1 ? nonNull[0] : undefined, nullable: types.includes('null') }
}

export function validRowScalar(value: unknown, schema: WorkflowJsonObject): boolean {
  if (schema['x-ui-widget']) return true
  const spec = rowScalar(schema)
  if (value === undefined) return true // Required properties are checked by the row editor.
  if (value === null) return spec.nullable || spec.type === 'null'
  if (Array.isArray(spec.enum) && !spec.enum.includes(value)) return false
  if (spec.type === 'boolean') return typeof value === 'boolean'
  if (spec.type === 'integer' || spec.type === 'number') {
    return typeof value === 'number' && Number.isFinite(value) &&
      (spec.type !== 'integer' || Number.isInteger(value)) &&
      (spec.minimum === undefined || value >= Number(spec.minimum)) &&
      (spec.maximum === undefined || value <= Number(spec.maximum)) &&
      (spec.exclusiveMinimum === undefined || value > Number(spec.exclusiveMinimum)) &&
      (spec.exclusiveMaximum === undefined || value < Number(spec.exclusiveMaximum))
      && (spec.multipleOf === undefined || Math.abs(value / Number(spec.multipleOf) - Math.round(value / Number(spec.multipleOf))) < 1e-8)
  }
  if (spec.type === 'string') return typeof value === 'string' &&
    (spec.minLength === undefined || value.length >= Number(spec.minLength)) &&
    (spec.maxLength === undefined || value.length <= Number(spec.maxLength)) &&
    (typeof spec.pattern !== 'string' || new RegExp(spec.pattern).test(value))
  return true
}

export function parseRowScalar(input: HTMLInputElement, schema: WorkflowJsonObject): unknown {
  const spec = rowScalar(schema)
  if (spec.type === 'boolean') return input.checked
  if (spec.type === 'number' || spec.type === 'integer') {
    if (input.validity.badInput) return ''
    if (input.value.trim() === '') return spec.nullable ? null : ''
    return Number(input.value)
  }
  return input.value
}
