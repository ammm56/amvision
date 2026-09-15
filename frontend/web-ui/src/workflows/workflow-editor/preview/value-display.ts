import type { WorkflowJsonObject } from '../types'

export interface DisplayField {
  label: string
  value: unknown
  format: string
  precision: number
  states: Record<string, string>
}

/** 只接受字段正文，不解析或推断生产字段。 */
export function displayFields(payload: WorkflowJsonObject): DisplayField[] {
  if (!Array.isArray(payload.fields)) return []
  return payload.fields.slice(0, 32).flatMap(raw => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
    const precision = Number(raw.precision ?? 2)
    return [{ label: String(raw.label ?? ''), value: raw.value, format: String(raw.format ?? 'text'),
      precision: Number.isInteger(precision) ? Math.max(0, Math.min(6, precision)) : 2,
      states: (raw.states && typeof raw.states === 'object' && !Array.isArray(raw.states) ? raw.states : {}) as Record<string, string> }]
  })
}

/** 百分比只格式化一次，空值和不安全数字不伪装成有效数据。 */
export function formatDisplayField(field: DisplayField): string {
  const value = field.value
  if (value === null || value === undefined) return '—'
  if (['integer', 'number', 'percent'].includes(field.format)) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
    if (field.format === 'integer') return Number.isSafeInteger(value) ? String(value) : '—'
    if (field.format === 'percent') return Number.isFinite(value * 100) ? `${(value * 100).toFixed(field.precision)}%` : '—'
    return value.toFixed(field.precision)
  }
  return String(value).slice(0, 1024)
}

/** 来源和汇总版本必须一致，缺失上下文不能猜测配对。 */
export function samePresentationContext(left: unknown, right: unknown): boolean {
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>
  return ['generation', 'sequence', 'snapshot_revision'].every(key => a[key] !== undefined && a[key] !== null && a[key] === b[key])
}
