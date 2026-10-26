import Decimal from 'decimal.js'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'

type RecordValue = Record<string, unknown>
interface Field { name: string; dtype: string; components: number; count: number; offset: number; byte_length: number }
const widths: Record<string, number> = { float32: 4, float64: 8, uint8: 1, int8: 1, uint16: 2, int16: 2, uint32: 4, int32: 4, uint64: 8, int64: 8 }
const D = Decimal.clone({ precision: 160 })
let cpuBytes = 0
let gpuBytes = 0

export function object(value: unknown): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('cloud_preview_invalid')
  return value as RecordValue
}
function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('cloud_preview_invalid')
  return value
}
function vector(value: unknown): number[] {
  if (!Array.isArray(value) || value.length !== 3 || value.some(v => typeof v !== 'number' || !Number.isFinite(v))) throw new Error('cloud_preview_invalid')
  return value as number[]
}
export function validatePolicy(policy: CloudRendererPolicy): void {
  for (const key of ['max_points', 'max_data_bytes', 'max_cpu_bytes', 'max_gpu_bytes', 'max_canvas_pixels'] as const) {
    if (!count(policy[key])) throw new Error('cloud_renderer_unconfigured')
  }
  if (!Number.isFinite(policy.max_position_error) || policy.max_position_error <= 0) throw new Error('cloud_renderer_unconfigured')
}
export function reserveGpu(bytes: number, policy: CloudRendererPolicy): () => void {
  if (gpuBytes + bytes > policy.max_gpu_bytes) throw new Error('cloud_gpu_capacity')
  gpuBytes += bytes
  let active = true
  return () => { if (active) { active = false; gpuBytes -= bytes } }
}
/** 几何显示附件与原点云显示共用浏览器总预算。 */
export function reserveCpu(bytes: number, policy: CloudRendererPolicy): () => void {
  if (cpuBytes + bytes > policy.max_cpu_bytes) throw new Error('cloud_cpu_capacity')
  cpuBytes += bytes
  let active = true
  return () => { if (active) { active = false; cpuBytes -= bytes } }
}
export function rendererUsage() { return { cpuBytes, gpuBytes } }
function scalar(view: DataView, field: Field, index: number): number | bigint {
  const offset = field.offset + index * widths[field.dtype]!
  switch (field.dtype) {
    case 'float32': return view.getFloat32(offset, true)
    case 'float64': return view.getFloat64(offset, true)
    case 'uint64': return view.getBigUint64(offset, true)
    case 'int64': return view.getBigInt64(offset, true)
    case 'uint32': return view.getUint32(offset, true)
    case 'int32': return view.getInt32(offset, true)
    case 'uint16': return view.getUint16(offset, true)
    case 'int16': return view.getInt16(offset, true)
    case 'uint8': return view.getUint8(offset)
    case 'int8': return view.getInt8(offset)
    default: throw new Error('cloud_preview_invalid')
  }
}
function decimal(value: unknown): Decimal {
  if (typeof value !== 'string' || value.length > 128 || !/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(value)) throw new Error('cloud_preview_invalid')
  const parsed = new D(value)
  if (!parsed.isFinite()) throw new Error('cloud_preview_invalid')
  return parsed
}

export interface CloudDisplayData {
  positions: Float32Array; colors: Float32Array; count: number; origin: number[]
  point(index: number): { sourceIndex: string | null; vertexIndex?: string; xyz: number[]; scalar: string | null }
  dispose(): void
}

/** 仅解码有界显示副本；完整点云与算法输出不经过浏览器。 */
export async function decodeCloudPreview(value: unknown, policy: CloudRendererPolicy, signal: AbortSignal): Promise<CloudDisplayData> {
  validatePolicy(policy)
  const body = object(value), data = object(body.data), color = object(body.color)
  if (body.type !== 'point-cloud-preview' || body.format_id !== 'amvision.point-cloud-preview.v1' || body.state !== 'ready') throw new Error('cloud_preview_invalid')
  const n = count(body.display_point_count), originalCount = count(body.source_point_count), pointCount = count(body.point_count), size = count(data.content_length)
  if (!['source', 'generated'].includes(String(body.vertex_kind))) throw new Error('cloud_preview_invalid')
  const generated = body.vertex_kind === 'generated'
  if (!n || n > pointCount || n > policy.max_points || size > policy.max_data_bytes) throw new Error('cloud_preview_capacity')
  const content = data.content
  if (typeof content !== 'string' || content.length !== 4 * Math.ceil(size / 3) || data.encoding !== 'base64' || data.checksum_algorithm !== 'sha256') throw new Error('cloud_preview_invalid')
  const cost = size * 3 + content.length * 2 + n * 24
  if (cpuBytes + cost > policy.max_cpu_bytes) throw new Error('cloud_cpu_capacity')
  cpuBytes += cost
  let released = false
  const release = () => { if (!released) { released = true; cpuBytes -= cost } }
  try {
    signal.throwIfAborted()
    // 不重复捕获四字符组，避免大显示载荷在正则引擎中耗尽调用栈。
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(content)) throw new Error('cloud_preview_invalid')
    const raw = Uint8Array.from(atob(content), c => c.charCodeAt(0))
    if (raw.length !== size) throw new Error('cloud_preview_invalid')
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', raw)), b => b.toString(16).padStart(2, '0')).join('')
    signal.throwIfAborted()
    if (hash !== data.checksum) throw new Error('cloud_preview_checksum')
    const indexField = generated ? 'vertex_indices' : 'source_indices'
    const expected = color.mode === 'solid' ? ['positions', indexField] : color.mode === 'rgb' ? ['positions', indexField, 'colors'] : color.mode === 'scalar' ? ['positions', indexField, 'scalar'] : []
    if (!Array.isArray(data.fields) || !expected.length || data.fields.length !== expected.length) throw new Error('cloud_preview_invalid')
    let end = 0
    const fields = data.fields.map((item, index): Field => {
      const f = object(item)
      const width = widths[String(f.dtype)]
      const components = index === 0 || f.name === 'colors' ? 3 : 1
      const offset = width ? Math.ceil(end / width) * width : -1
      if (!width || f.name !== expected[index] || f.count !== n || f.components !== components || f.offset !== offset || f.byte_length !== n * components * width) throw new Error('cloud_preview_invalid')
      if (index === 0 && !['float32', 'float64'].includes(String(f.dtype)) || index === 1 && f.dtype !== 'uint64' || f.name === 'colors' && f.dtype !== 'uint8') throw new Error('cloud_preview_invalid')
      for (let i = end; i < offset; i++) if (raw[i] !== 0) throw new Error('cloud_preview_invalid')
      end = offset + n * components * width
      if (end > size) throw new Error('cloud_preview_invalid')
      return f as unknown as Field
    })
    if (end !== size) throw new Error('cloud_preview_invalid')
    const origin = vector(body.render_origin), bounds = object(body.bounds), low = vector(bounds.min), high = vector(bounds.max)
    if (low.some((v, i) => v > high[i]! || origin[i]! < v || origin[i]! > high[i]!)) throw new Error('cloud_preview_invalid')
    const view = new DataView(raw.buffer), positions = new Float32Array(n * 3), colors = new Float32Array(n * 3)
    const range = color.mode === 'scalar' && color.min !== null && color.max !== null ? [decimal(color.min), decimal(color.max)] as const : null
    if (range && range[0].gt(range[1])) throw new Error('cloud_preview_invalid')
    let previous = -1n, invalid = 0
    const actualLow = [Infinity, Infinity, Infinity], actualHigh = [-Infinity, -Infinity, -Infinity]
    for (let i = 0; i < n; i++) {
      if (i % 4096 === 0) { await new Promise(resolve => setTimeout(resolve, 0)); signal.throwIfAborted() }
      const sourceIndex = scalar(view, fields[1]!, i) as bigint
      if (sourceIndex >= BigInt(generated ? pointCount : originalCount) || generated && sourceIndex <= previous) throw new Error('cloud_preview_invalid')
      previous = sourceIndex
      for (let c = 0; c < 3; c++) {
        const position = scalar(view, fields[0]!, i * 3 + c) as number
        const local = position - origin[c]!
        positions[i * 3 + c] = local
        if (!Number.isFinite(position) || !Number.isFinite(positions[i * 3 + c]) || Math.abs(local - positions[i * 3 + c]!) > policy.max_position_error) throw new Error('cloud_position_precision')
        actualLow[c] = Math.min(actualLow[c]!, position); actualHigh[c] = Math.max(actualHigh[c]!, position)
        colors[i * 3 + c] = color.mode === 'rgb' ? Number(scalar(view, fields[2]!, i * 3 + c)) / 255 : [.08, .65, .61][c]!
      }
      if (color.mode === 'scalar') {
        const v = scalar(view, fields[2]!, i)
        const finite = typeof v === 'bigint' || Number.isFinite(v)
        if (!finite) invalid++
        const t = finite && range ? range[0].eq(range[1]) ? .5 : new D(v.toString()).minus(range[0]).div(range[1].minus(range[0])).clamp(0, 1).toNumber() : null
        colors.set(t === null ? [.45, .45, .45] : [t, .2 + .6 * (1 - Math.abs(2 * t - 1)), 1 - t], i * 3)
      }
    }
    if (actualLow.some((v, i) => v !== low[i] || actualHigh[i] !== high[i]) || color.mode === 'scalar' && (count(color.invalid_count) !== invalid || (range === null) !== (invalid === n))) throw new Error('cloud_preview_invalid')
    return { positions, colors, count: n, origin, point(index) {
      if (released || !Number.isInteger(index) || index < 0 || index >= n) throw new Error('cloud_point_unavailable')
      const identity = scalar(view, fields[1]!, index).toString()
      return { sourceIndex: generated ? null : identity, ...(generated ? { vertexIndex: identity } : {}), xyz: [0, 1, 2].map(c => scalar(view, fields[0]!, index * 3 + c) as number), scalar: color.mode === 'scalar' ? scalar(view, fields[2]!, index).toString() : null }
    }, dispose: release }
  } catch (error) { release(); throw error }
}
