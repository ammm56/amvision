import type { WorkflowJsonObject } from '../types'
import { displayColor } from '../parameters/display-colors'

export interface DisplayField {
  label: string
  value: unknown
  format: string
  precision: number
  states: Record<string, string>
  labelColor?: string
  valueColor?: string
}

/** 只接受字段正文，不解析或推断生产字段。 */
export function displayFields(payload: WorkflowJsonObject): DisplayField[] {
  if (!Array.isArray(payload.fields)) return []
  return payload.fields.slice(0, 32).flatMap(raw => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
    const precision = Number(raw.precision ?? 2)
    return [{ label: String(raw.label ?? ''), value: raw.value, format: String(raw.format ?? 'text'),
      precision: Number.isInteger(precision) ? Math.max(0, Math.min(6, precision)) : 2,
      states: (raw.states && typeof raw.states === 'object' && !Array.isArray(raw.states) ? raw.states : {}) as Record<string, string>,
      labelColor: displayColor(raw.label_color), valueColor: displayColor(raw.value_color) }]
  })
}

/** 状态匹配只决定文字颜色，不改变字段的原值或格式化。 */
export function fieldValueColor(field: DisplayField): string | undefined {
  return (field.format === 'status' && field.value != null ? displayColor(field.states[String(field.value)]) : undefined) || field.valueColor
}

export const appearanceControls = [
  { key: 'panel_width', label: 'Panel Width', min: 100, max: 1600, default: null },
  { key: 'panel_height', label: 'Panel Height', min: 80, max: 1200, default: null },
  { key: 'font_size', label: 'Font Size', min: 10, max: 72, default: 13 },
  { key: 'status_font_size', label: 'Status Font Size', min: 10, max: 120, default: 20 },
  { key: 'background_opacity', label: 'Background Opacity', min: 0, max: 100, default: 78 },
] as const

/** 对来自旧版本或外部正文的尺寸再次做白名单校验。 */
export function appearanceStyles(value: unknown): Record<string, string> {
  const data = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const style: Record<string, string> = {}
  for (const control of appearanceControls) {
    const raw = data[control.key]
    if (typeof raw !== 'number' || !Number.isInteger(raw) || raw < control.min || raw > control.max) continue
    style[`--display-${control.key.replaceAll('_', '-')}`] = `${raw}${control.key === 'background_opacity' ? '%' : 'px'}`
  }
  const color = displayColor(data.background_color)
  if (color) style['--display-background-color'] = color
  return style
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
