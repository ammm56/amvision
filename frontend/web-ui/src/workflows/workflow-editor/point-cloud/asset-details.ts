import { apiRequest } from '@/shared/api/http-client'
import { resourceVersionPath, type MeasurementResourceReference, type CloudRendererPolicy } from '../services/measurement-resource.service'
import { object, count, vector, widths, scalar, decimal, D, reserveCpu, validatePolicy, type CloudDisplayData } from './preview-data'

export interface DetailBounds { min: number[]; max: number[] }
interface DetailField { name: string; dtype: string; components: number; offset: number }
export interface DetailBlock { block_id: number; count: number; bounds: DetailBounds; byte_length: number; sha256: string }
export interface DetailIndex {
  format_id: string; source: MeasurementResourceReference; generation: string
  point_count: number; source_point_count: number; valid_count: number; excluded_count: number
  vertex_kind: 'source' | 'generated'; bounds: DetailBounds; fields: DetailField[]
  logical_dtype: 'uint32' | 'uint64'; identity_dtype: 'uint32' | 'uint64'
  row_bytes: number; logical_offset: number; identity_offset: number; leaf_limit: number; blocks: DetailBlock[]
}

function bounds(value: unknown): DetailBounds {
  const b = object(value), min = vector(b.min), max = vector(b.max)
  if (min.some((v, i) => v > max[i]!)) throw new Error('cloud_preview_invalid')
  return { min, max }
}

export function validateDetailIndex(value: unknown, source: MeasurementResourceReference, generation: string): DetailIndex {
  const r = object(value), reference = object(r.source)
  if (r.format_id !== 'amvision.point-cloud-detail.v1' || r.generation !== generation || !/^[0-9a-f]{32}$/.test(generation)
    || Object.keys(source).some(k => reference[k] !== source[k as keyof MeasurementResourceReference]) || source.kind !== 'point-cloud'
    || !['source', 'generated'].includes(String(r.vertex_kind))) throw new Error('cloud_preview_invalid')
  const n = count(r.point_count), valid = count(r.valid_count), excluded = count(r.excluded_count)
  if (!n || !valid || valid + excluded !== n || !count(r.source_point_count)) throw new Error('cloud_preview_invalid')
  const full = bounds(r.bounds)
  if (!Array.isArray(r.fields) || !Array.isArray(r.blocks) || !r.blocks.length) throw new Error('cloud_preview_invalid')
  let offset = 0, total = 0
  const names = new Set<string>()
  for (const field of r.fields) {
    const f = object(field), width = widths[String(f.dtype)], components = count(f.components)
    if (!width || !components || f.offset !== offset || typeof f.name !== 'string' || names.has(f.name)) throw new Error('cloud_preview_invalid')
    if (f.name === 'positions' && (components !== 3 || !['float32', 'float64'].includes(String(f.dtype)))) throw new Error('cloud_preview_invalid')
    names.add(f.name); offset += width * components
  }
  const logicalType = n <= 2 ** 32 ? 'uint32' : 'uint64'
  const identityCount = r.vertex_kind === 'source' ? count(r.source_point_count) : n
  const identityType = identityCount <= 2 ** 32 ? 'uint32' : 'uint64'
  const logicalWidth = widths[logicalType]!, identityWidth = widths[identityType]!
  const rowBytes = offset + logicalWidth + identityWidth
  if (r.logical_dtype !== logicalType || r.identity_dtype !== identityType || !names.has('positions')
    || r.logical_offset !== offset || r.identity_offset !== offset + logicalWidth || r.row_bytes !== rowBytes) throw new Error('cloud_preview_invalid')
  for (const [id, block] of r.blocks.entries()) {
    const b = object(block), box = bounds(b.bounds), size = count(b.count)
    if (b.block_id !== id || !size || size > count(r.leaf_limit) || b.byte_length !== size * rowBytes || !/^[0-9a-f]{64}$/.test(String(b.sha256))
      || box.min.some((v, i) => v < full.min[i]! || box.max[i]! > full.max[i]!)) throw new Error('cloud_preview_invalid')
    total += size
  }
  if (total !== valid) throw new Error('cloud_preview_invalid')
  return value as DetailIndex
}

export async function readDetailIndex(source: MeasurementResourceReference, signal: AbortSignal) {
  const value = await apiRequest<unknown>(`${resourceVersionPath(source)}/details`, { query: { sha256: source.sha256 }, signal })
  signal.throwIfAborted()
  return validateDetailIndex(value, source, String(object(value).generation))
}

/** 原始行记录保留完整字段；仅渲染坐标转为相对原点的 float32。 */
export async function decodeDetailBlock(raw: ArrayBuffer, index: DetailIndex, block: DetailBlock, origin: number[], color: Record<string, unknown>, policy: CloudRendererPolicy, signal: AbortSignal): Promise<CloudDisplayData> {
  validatePolicy(policy)
  if (raw.byteLength !== block.byte_length || raw.byteLength > policy.max_data_bytes || block.count > policy.max_points) throw new Error('cloud_preview_capacity')
  const release = reserveCpu(raw.byteLength + block.count * 24, policy)
  let disposed = false
  try {
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', raw)), x => x.toString(16).padStart(2, '0')).join('')
    signal.throwIfAborted()
    if (digest !== block.sha256) throw new Error('cloud_preview_checksum')
    const view = new DataView(raw), position = index.fields.find(f => f.name === 'positions')!
    const rowId = (row: number, offset: number, dtype: 'uint32' | 'uint64') => dtype === 'uint32'
      ? BigInt(view.getUint32(row * index.row_bytes + offset, true))
      : view.getBigUint64(row * index.row_bytes + offset, true)
    const colorField = index.fields.find(f => f.name === (color.mode === 'rgb' ? 'colors' : color.field))
    const component = color.mode === 'scalar' ? count(color.component ?? 0) : 0
    if (!['solid', 'rgb', 'scalar'].includes(String(color.mode)) || color.mode !== 'solid' && (!colorField || component >= colorField.components)
      || color.mode === 'rgb' && (colorField!.dtype !== 'uint8' || colorField!.components !== 3)) throw new Error('cloud_preview_invalid')
    const range = color.mode === 'scalar' && color.min != null && color.max != null ? [decimal(color.min), decimal(color.max)] : null
    if (range && range[0]!.gt(range[1]!)) throw new Error('cloud_preview_invalid')
    const positions = new Float32Array(block.count * 3), colors = new Float32Array(block.count * 3)
    const read = (f: DetailField, row: number, c = 0) => scalar(view, { dtype: f.dtype, offset: row * index.row_bytes + f.offset }, c)
    const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity]
    for (let i = 0; i < block.count; i++) {
      if (i % 4096 === 0) { await new Promise(resolve => setTimeout(resolve, 0)); signal.throwIfAborted() }
      const identity = rowId(i, index.identity_offset, index.identity_dtype)
      const logical = rowId(i, index.logical_offset, index.logical_dtype)
      if (logical >= BigInt(index.point_count) || identity >= BigInt(index.vertex_kind === 'source' ? index.source_point_count : index.point_count)
        || index.vertex_kind === 'generated' && identity !== logical) throw new Error('cloud_preview_invalid')
      for (let c = 0; c < 3; c++) {
        const value = Number(read(position, i, c)), relative = value - origin[c]!
        positions[i * 3 + c] = relative
        if (!Number.isFinite(value) || !Number.isFinite(positions[i * 3 + c]) || Math.abs(relative - positions[i * 3 + c]!) > policy.max_position_error) throw new Error('cloud_position_precision')
        low[c] = Math.min(low[c]!, value); high[c] = Math.max(high[c]!, value)
        colors[i * 3 + c] = color.mode === 'rgb' ? Number(read(colorField!, i, c)) / 255 : [.08, .65, .61][c]!
      }
      if (color.mode === 'scalar') {
        const value = read(colorField!, i, component), finite = typeof value === 'bigint' || Number.isFinite(value)
        const t = finite && range ? range[0]!.eq(range[1]!) ? .5 : new D(value.toString()).minus(range[0]!).div(range[1]!.minus(range[0]!)).clamp(0, 1).toNumber() : null
        colors.set(t === null ? [.45, .45, .45] : [t, .2 + .6 * (1 - Math.abs(2 * t - 1)), 1 - t], i * 3)
      }
    }
    if (low.some((v, i) => v !== block.bounds.min[i] || high[i] !== block.bounds.max[i])) throw new Error('cloud_preview_invalid')
    return { positions, colors, count: block.count, origin, point(i) {
      if (disposed || !Number.isInteger(i) || i < 0 || i >= block.count) throw new Error('cloud_point_unavailable')
      const identity = rowId(i, index.identity_offset, index.identity_dtype).toString()
      return { sourceIndex: index.vertex_kind === 'source' ? identity : null, ...(index.vertex_kind === 'generated' ? { vertexIndex: identity } : {}),
        xyz: [0, 1, 2].map(c => Number(read(position, i, c))), scalar: color.mode === 'scalar' ? read(colorField!, i, component).toString() : null }
    }, dispose() { if (!disposed) { disposed = true; release() } } }
  } catch (error) { release(); throw error }
}

export async function loadDetailBlock(index: DetailIndex, block: DetailBlock, origin: number[], color: Record<string, unknown>, policy: CloudRendererPolicy, signal: AbortSignal) {
  if (block.byte_length > policy.max_data_bytes) throw new Error('cloud_preview_capacity')
  const release = reserveCpu(block.byte_length * 2, policy)
  try {
    const blob = await apiRequest<Blob>(`${resourceVersionPath(index.source)}/details/${block.block_id}`, {
      query: { sha256: index.source.sha256, generation: index.generation }, responseType: 'blob', signal,
    })
    signal.throwIfAborted()
    if (blob.size !== block.byte_length) throw new Error('cloud_preview_invalid')
    return await decodeDetailBlock(await blob.arrayBuffer(), index, block, origin, color, policy, signal)
  } finally { release() }
}
