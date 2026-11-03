import { decodePreviewBytes, object, reserveCpu } from './preview-data'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'

type Value = Record<string, unknown>
export interface DebugArray {
  count: number
  components: number
  get: (index: number, component?: number) => number
}
export interface DebugEvidence {
  id: string
  featureId: string
  nodeId: string
  runId: string
  state: string
  reason: string | null
  failureField?: string | null
  requiredBytes?: number | null
  stage: string
  complete: boolean
  measurementReason: string | null
  targetIds: string[]
  evaluation: { origin: number[]; rotation: number[][] }
  grid: null | {
    origin: number[]
    step: number
    shape: number[]
    seedMin: number[]
    seedMax: number[]
    selection: string
    component: number | null
  }
  arrays: Record<string, DebugArray>
  dispose: () => void
}
export interface DebugSelection {
  kind: 'cell' | 'candidate' | 'profile' | 'metric'
  index: number
}
export interface DebugLayers {
  grid: boolean
  profiles: boolean
  candidates: boolean
  partition: boolean
}
const invalid = () => new Error('cloud_debug_invalid')
const integer = (v: unknown) => {
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < 0)
    throw invalid()
  return v
}
const vector = (v: unknown, n: number) => {
  if (
    !Array.isArray(v) ||
    v.length !== n ||
    v.some((x) => typeof x !== 'number' || !Number.isFinite(x))
  )
    throw invalid()
  return v as number[]
}
const specs: Record<string, [string, number]> = {
  input_source_indices: ['uint64', 1],
  counts: ['uint64', 1],
  heights: ['float64', 1],
  spread: ['float64', 1],
  usable: ['uint8', 1],
  foreground: ['uint8', 1],
  grouped: ['uint8', 1],
  selected: ['uint8', 1],
  components: ['int64', 1],
  bin_rows: ['int64', 1],
  metric_uv: ['float64', 2],
  metric_rows: ['uint64', 1],
  metric_labels: ['int64', 1],
  metric_seed: ['uint8', 1],
  candidate_positions: ['float', 3],
  local_source_rows: ['uint64', 1],
  source_edges: ['uint64', 2],
  source_weights: ['float64', 2],
  surface_faces: ['uint64', 3],
  surface_face_ids: ['uint64', 1],
  section_edges: ['uint64', 2],
  section_face_offsets: ['uint64', 1],
  section_faces: ['uint64', 1],
  candidate_indices: ['uint64', 1],
  candidate_offsets: ['uint64', 1],
  candidate_closed: ['uint8', 1],
  selection_events: ['uint64', 4],
  profile_positions: ['float64', 3],
  profile_offsets: ['uint64', 1],
  profile_breaks: ['uint8', 1],
  profile_kinds: ['uint8', 1],
  profile_cells: ['uint64', 2],
  profile_weights: ['float64', 2],
}
const widths: Record<string, number> = {
  float32: 4,
  float64: 8,
  uint64: 8,
  int64: 8,
  uint8: 1,
}

/** 同观测的冻结调试正文；不从显示 LOD 重新生成算法数据。 */
export async function decodeBoundaryDebug(
  payload: Value,
  policy: CloudRendererPolicy,
  signal: AbortSignal,
): Promise<DebugEvidence[]> {
  if (payload.boundary_debug === undefined) return []
  if (
    !Array.isArray(payload.boundary_debug) ||
    payload.boundary_debug.length > 8192
  )
    throw invalid()
  const results: DebugEvidence[] = [],
    ids = new Set<string>(),
    spatial = object(payload.spatial)
  const encodedOwners: (() => void)[] = []
  let points = integer(payload.display_point_count ?? 0),
    bytes = integer(object(payload.data).content_length)
  try {
    for (const entry of payload.boundary_debug) {
      const raw = object(entry)
      if (raw.state === 'ready') {
        const data = object(raw.data)
        if (typeof data.content !== 'string') throw invalid()
        encodedOwners.push(reserveCpu(data.content.length * 2, policy))
      } else encodedOwners.push(() => {})
    }
    for (const entry of payload.boundary_debug) {
      const raw = object(entry),
        identity = object(raw.identity),
        id = String(identity.capture_id)
      for (const key of [
        'capture_id',
        'run_id',
        'node_id',
        'invocation_id',
        'observation_id',
        'feature_id',
      ])
        if (
          typeof identity[key] !== 'string' ||
          !(identity[key] as string).length
        )
          throw invalid()
      if (
        typeof identity.parameters_sha256 !== 'string' ||
        !/^[a-f0-9]{64}$/.test(identity.parameters_sha256)
      )
        throw invalid()
      if (results.length && identity.run_id !== results[0]!.runId)
        throw invalid()
      if (
        raw.format_id !== 'amvision.boundary-debug.v1' ||
        identity.format_id !== 'amvision.boundary-debug-ref.v1' ||
        !id ||
        ids.has(id) ||
        identity.observation_id !== payload.observation_id ||
        !['ready', 'unavailable', 'not-executed'].includes(String(raw.state)) ||
        typeof raw.selection_complete !== 'boolean' ||
        !['input', 'grid', 'candidates', 'selection', 'complete'].includes(
          String(raw.stage),
        )
      )
        throw invalid()
      ids.add(id)
      const curves = object(payload.geometry).curves
      const curve = Array.isArray(curves)
        ? curves
            .map(object)
            .find(
              (c) =>
                c.kind === 'boundary' && c.feature_id === identity.feature_id,
            )
        : undefined
      if (
        !curve ||
        object(curve.method).parameters_sha256 !== identity.parameters_sha256 ||
        curve.reason !== raw.measurement_reason
      )
        throw invalid()
      const e = raw.evaluation === null ? null : object(raw.evaluation)
      if (
        e &&
        (e.frame_id !== spatial.frame_id ||
          e.length_unit !== spatial.length_unit)
      )
        throw invalid()
      const evaluation = e
        ? { origin: vector(e.origin, 3), rotation: vectorRows(e.rotation) }
        : { origin: [], rotation: [] }
      if (
        e &&
        JSON.stringify(e) !==
          JSON.stringify(object(object(curve.method).resolution).evaluation)
      ) {
        const actual = object(
          object(object(curve.method).resolution).evaluation,
        )
        if (
          JSON.stringify(e.origin) !== JSON.stringify(actual.origin) ||
          JSON.stringify(e.rotation) !== JSON.stringify(actual.rotation)
        )
          throw invalid()
      }
      if (
        !Array.isArray(raw.target_ids) ||
        raw.target_ids.some((x) => typeof x !== 'string') ||
        new Set(raw.target_ids).size !== raw.target_ids.length
      )
        throw invalid()
      const g = raw.grid === null ? null : object(raw.grid)
      const grid = g
        ? {
            origin: vector(g.origin, 2),
            step: Number(g.step),
            shape: vector(g.shape, 2).map(integer),
            seedMin: vector(g.seed_min, 2),
            seedMax: vector(g.seed_max, 2),
            selection: String(g.selection),
            component:
              g.selected_component === null
                ? null
                : integer(g.selected_component),
          }
        : null
      if (
        grid &&
        (!Number.isFinite(grid.step) ||
          grid.step <= 0 ||
          grid.shape.some((n) => !n) ||
          !['grid-connected', 'distance-connected'].includes(grid.selection) ||
          grid.seedMin.some((n, i) => n > grid.seedMax[i]!))
      )
        throw invalid()
      const record: DebugEvidence = {
        id,
        featureId: String(identity.feature_id),
        nodeId: String(identity.node_id),
        runId: String(identity.run_id),
        state: String(raw.state),
        reason: raw.reason === null ? null : String(raw.reason),
        stage: String(raw.stage),
        complete: raw.selection_complete,
        measurementReason:
          raw.measurement_reason === null
            ? null
            : String(raw.measurement_reason),
        targetIds: raw.target_ids as string[],
        evaluation,
        grid,
        arrays: {},
        dispose: () => {},
      }
      record.failureField =
        raw.failure_field == null ? null : String(raw.failure_field)
      record.requiredBytes =
        raw.required_bytes == null ? null : integer(raw.required_bytes)
      results.push(record)
      const releaseEncoded = encodedOwners[results.length - 1]!
      record.dispose = releaseEncoded
      if (record.state !== 'ready') {
        if (raw.data !== null || !record.reason) throw invalid()
        continue
      }
      if (!e || record.reason !== null || record.stage === 'input')
        throw invalid()
      const data = object(raw.data),
        length = integer(data.content_length)
      if (bytes + length > policy.max_data_bytes)
        throw new Error('cloud_preview_capacity')
      // 持有正文字符串与解码数组；atob/摘要的短时副本只在解码阶段计费。
      const release = reserveCpu(length + 8192, policy)
      record.dispose = () => {
        release()
        releaseEncoded()
      }
      const transient = reserveCpu(length * 3, policy)
      let binary: Uint8Array<ArrayBuffer>
      try {
        binary = await decodePreviewBytes(data, signal)
      } finally {
        transient()
      }
      const view = new DataView(binary.buffer)
      if (!Array.isArray(data.fields) || data.fields.length > 48)
        throw invalid()
      let end = 0
      for (const value of data.fields) {
        const f = object(value),
          name = String(f.name),
          dtype = String(f.dtype),
          spec = specs[name],
          width = widths[dtype]
        if (
          !spec ||
          record.arrays[name] ||
          !width ||
          (spec[0] === 'float'
            ? !['float32', 'float64'].includes(dtype)
            : dtype !== spec[0]) ||
          f.components !== spec[1]
        )
          throw invalid()
        const count = integer(f.count),
          offset = Math.ceil(end / width) * width,
          size = count * spec[1] * width
        if (
          !Number.isSafeInteger(size) ||
          f.offset !== offset ||
          f.byte_length !== size ||
          offset + size > length
        )
          throw invalid()
        for (let i = end; i < offset; i++) if (binary[i] !== 0) throw invalid()
        record.arrays[name] = {
          count,
          components: spec[1],
          get(index, component = 0) {
            if (
              !Number.isInteger(index) ||
              index < 0 ||
              index >= count ||
              component < 0 ||
              component >= spec[1]
            )
              throw invalid()
            const at = offset + (index * spec[1] + component) * width
            const n =
              dtype === 'float32'
                ? view.getFloat32(at, true)
                : dtype === 'float64'
                  ? view.getFloat64(at, true)
                  : dtype === 'uint8'
                    ? view.getUint8(at)
                    : Number(
                        dtype === 'uint64'
                          ? view.getBigUint64(at, true)
                          : view.getBigInt64(at, true),
                      )
            if (
              !Number.isFinite(n) ||
              (dtype.includes('int') && !Number.isSafeInteger(n))
            )
              throw invalid()
            return n
          },
        }
        end = offset + size
      }
      if (end !== length) throw invalid()
      points += await validateArrays(
        record,
        integer(payload.source_point_count),
        signal,
      )
      if (points > policy.max_points) throw new Error('cloud_preview_capacity')
      bytes += length
      signal.throwIfAborted()
    }
    return results
  } catch (error) {
    for (const record of results) record.dispose()
    for (const release of encodedOwners) release()
    throw error
  }
}
function vectorRows(value: unknown) {
  if (!Array.isArray(value) || value.length !== 3) throw invalid()
  const rows = value.map((r) => vector(r, 3))
  for (let a = 0; a < 3; a++)
    for (let b = 0; b < 3; b++) {
      const dot = rows.reduce((s, r) => s + r[a]! * r[b]!, 0)
      if (Math.abs(dot - (a === b ? 1 : 0)) > 1e-8) throw invalid()
    }
  return rows
}

async function validateArrays(
  d: DebugEvidence,
  sourceCount: number,
  signal: AbortSignal,
) {
  const a = d.arrays,
    require = (name: string, count?: number) => {
      const f = a[name]
      if (!f || (count !== undefined && f.count !== count)) throw invalid()
      return f
    }
  const sources = require('input_source_indices')
  for (let i = 0; i < sources.count; i++)
    if (sources.get(i) < 0 || sources.get(i) >= sourceCount) throw invalid()
  let total = 0
  const bounded = (name: string, upper: number) => {
    const f = a[name]
    if (f)
      for (let i = 0; i < f.count; i++)
        for (let j = 0; j < f.components; j++)
          if (f.get(i, j) < 0 || f.get(i, j) >= upper) throw invalid()
  }
  if (d.grid) {
    const n = d.grid.shape[0]! * d.grid.shape[1]!
    if (!Number.isSafeInteger(n)) throw invalid()
    total += n
    for (const name of [
      'counts',
      'heights',
      'spread',
      'usable',
      'foreground',
      'selected',
    ])
      require(name, n)
    if (d.grid.selection === 'grid-connected') {
      require('grouped', n)
      require('components', n)
    }
    for (let i = 0; i < n; i++) {
      const count = a.counts!.get(i),
        height = a.heights!.get(i),
        spread = a.spread!.get(i)
      if (
        count > sources.count ||
        count < 0 ||
        spread < 0 ||
        (!count && (height !== 0 || spread !== 0))
      )
        throw invalid()
      for (const name of ['usable', 'foreground', 'selected', 'grouped'])
        if (a[name] && ![0, 1].includes(a[name]!.get(i))) throw invalid()
      if (
        a.selected!.get(i) > a.foreground!.get(i) ||
        a.foreground!.get(i) > a.usable!.get(i) ||
        (!count && a.usable!.get(i))
      )
        throw invalid()
    }
    const bins = require('bin_rows', sources.count)
    for (let i = 0; i < bins.count; i++)
      if (bins.get(i) < -1 || bins.get(i) >= n) throw invalid()
    if (a.metric_rows) {
      const m = a.metric_rows.count
      require('metric_uv', m)
      require('metric_labels', m)
      require('metric_seed', m)
      bounded('metric_rows', sources.count)
      total += m
    }
    if (a.profile_positions) {
      const m = a.profile_positions.count
      for (const name of [
        'profile_breaks',
        'profile_kinds',
        'profile_cells',
        'profile_weights',
      ])
        require(name, m)
      const offsets = require('profile_offsets', 5)
      offsetsValid(offsets, m)
      bounded('profile_cells', n)
      bounded('profile_breaks', 2)
      bounded('profile_kinds', 4)
      total += m
    }
  } else {
    const positions = require('candidate_positions'),
      indices = require('candidate_indices'),
      closed = require('candidate_closed'),
      offsets = require('candidate_offsets', closed.count + 1)
    offsetsValid(offsets, indices.count)
    bounded('candidate_indices', positions.count)
    bounded('candidate_closed', 2)
    const local = require('local_source_rows')
    bounded('local_source_rows', sources.count)
    if (a.source_edges) {
      require('source_edges', positions.count)
      require('source_weights', positions.count)
      bounded('source_edges', local.count)
      const faces = require('surface_faces')
      require('surface_face_ids', faces.count)
      bounded('surface_faces', local.count)
      const edges = require('section_edges')
      bounded('section_edges', positions.count)
      offsetsValid(
        require('section_face_offsets', edges.count + 1),
        require('section_faces').count,
      )
      bounded('section_faces', faces.count)
    } else if (local.count !== positions.count) throw invalid()
    if (a.selection_events)
      for (let i = 0; i < a.selection_events.count; i++) {
        const f = a.selection_events
        if (
          f.get(i, 0) >= d.targetIds.length ||
          f.get(i, 1) >= closed.count ||
          f.get(i, 2) > 2 ||
          f.get(i, 3) > positions.count
        )
          throw invalid()
      }
    total += positions.count
  }
  for (const field of Object.values(a))
    for (let start = 0; start < field.count; start += 16384) {
      signal.throwIfAborted()
      for (let i = start; i < Math.min(field.count, start + 16384); i++)
        for (let j = 0; j < field.components; j++) field.get(i, j)
      await new Promise<void>((resolve) => setTimeout(resolve, 0))
    }
  return total
}
function offsetsValid(offsets: DebugArray, end: number) {
  if (
    !offsets.count ||
    offsets.get(0) !== 0 ||
    offsets.get(offsets.count - 1) !== end
  )
    throw invalid()
  for (let i = 1; i < offsets.count; i++)
    if (offsets.get(i) < offsets.get(i - 1)) throw invalid()
}
export function debugPoint(d: DebugEvidence, u: number, v: number, h = 0) {
  return d.evaluation.origin.map(
    (o, i) =>
      o +
      d.evaluation.rotation[i]![0]! * u +
      d.evaluation.rotation[i]![1]! * v +
      d.evaluation.rotation[i]![2]! * h,
  )
}
