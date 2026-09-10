import type { PreviewEvent } from '../services/workflow-preview-session.service'
import { PREVIEW_FORMAT } from '../services/workflow-preview-session.service'

export type PreviewRunStatus = 'accepted' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timed_out'
export const PREVIEW_TERMINAL = new Set<string>(['succeeded', 'failed', 'cancelled', 'timed_out'])

export interface PreviewSessionState {
  sessionId: string
  epoch: string
  watermark: number
  run: Record<string, any> | null
  nodes: Record<string, Record<string, any>>
  displays: Record<string, Record<string, any>>
  values: Record<string, Record<string, any>>
}

export function emptyPreviewState(sessionId: string, epoch: string): PreviewSessionState {
  return { sessionId, epoch, watermark: -1, run: null, nodes: {}, displays: {}, values: {} }
}

/** 纯状态归并：只接收本会话的快照和之后的事件，不因合并进度出现序号间隙而重查。 */
export function reducePreviewEvent(state: PreviewSessionState, event: PreviewEvent): boolean {
  if (event.format_id !== PREVIEW_FORMAT || event.session_id !== state.sessionId || event.epoch !== state.epoch
    || !Number.isSafeInteger(event.seq) || event.seq < 0) return false
  const payload = event.payload
  if (event.type === 'session.snapshot') {
    if (event.seq < state.watermark || payload.watermark !== event.seq) return false
    state.run = payload.run ? { ...payload.run } : null
    state.nodes = Object.fromEntries((payload.nodes ?? []).map((node: Record<string, any>) => [node.invocation_id, node]))
    state.displays = Object.fromEntries((payload.displays ?? []).map((display: Record<string, any>) => [JSON.stringify([display.node_id, display.output_port]), display]))
    state.values = Object.fromEntries((payload.values ?? []).map((value: Record<string, any>) => [JSON.stringify([value.node_id, value.output_port]), value]))
    state.watermark = event.seq
    return true
  }
  if (event.seq <= state.watermark) return false
  if (event.type === 'run.accepted') {
    if (payload.run_id !== event.run_id || payload.document_revision !== event.document_revision) return false
    state.run = { ...payload }
    state.nodes = {}
    const retained = Array.isArray(payload.node_ids) ? new Set(payload.node_ids) : null
    state.displays = Object.fromEntries(Object.entries(state.displays).filter(([, value]) => !retained || retained.has(value.node_id)).map(([key, value]) => [key, { ...value, stale: true }]))
    state.values = {}
  } else {
    if (!state.run || event.run_id !== state.run.run_id || event.document_revision !== state.run.document_revision) return false
    const terminal = PREVIEW_TERMINAL.has(state.run.state)
    if (event.type === 'run.started') {
      if (state.run.state !== 'accepted') return false
      state.run = { ...state.run, state: 'running' }
    } else if (event.type === 'run.finished') {
      if (terminal || !PREVIEW_TERMINAL.has(payload.status)) return false
      state.run = { ...state.run, state: payload.status, outputs: payload.outputs ?? {}, error: payload.error ?? null, delivery_state: payload.delivery_state, timings: payload.timings }
    } else if (event.type === 'run.outputs') {
      if (!terminal) return false
      state.run = { ...state.run, ...payload, timings: { ...state.run.timings, ...payload.timings } }
    } else if (event.type.startsWith('node.')) {
      if (terminal || !payload.invocation_id || !payload.node_id) return false
      const old = state.nodes[payload.invocation_id]
      if (old && (PREVIEW_TERMINAL.has(old.status) || old.status === 'skipped')) return false
      if (PREVIEW_TERMINAL.has(payload.status) || payload.status === 'skipped') {
        for (const [key, node] of Object.entries(state.nodes)) {
          if (key !== payload.invocation_id && node.node_id === payload.node_id && (PREVIEW_TERMINAL.has(node.status) || node.status === 'skipped')) delete state.nodes[key]
        }
      }
      state.nodes[payload.invocation_id] = { ...old, ...payload }
    } else if (event.type === 'display.updated' || event.type === 'display.unavailable') {
      state.displays[JSON.stringify([payload.node_id, payload.output_port])] = { ...payload }
    } else if (event.type === 'value.updated') {
      state.values[JSON.stringify([payload.node_id, payload.output_port])] = { ...payload }
    } else return false
  }
  state.watermark = event.seq
  return true
}
