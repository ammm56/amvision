import { expect, it } from 'vitest'
import { emptyPreviewState, reducePreviewEvent } from './previewSessionState'
import { PREVIEW_FORMAT, type PreviewEvent } from '../services/workflow-preview-session.service'

it('prunes deleted node results when accepting the next document snapshot', () => {
  const state = emptyPreviewState('s', 'e')
  state.displays = { keep: { node_id: 'keep', payload: { value: false } }, removed: { node_id: 'removed' } }
  reducePreviewEvent(state, message('run.accepted', 1, { run_id: 'r', document_revision: 'd', state: 'accepted', node_ids: ['keep'] }))
  expect(state.displays).toEqual({ keep: { node_id: 'keep', payload: { value: false }, stale: true } })
})

const message = (type: string, seq: number, payload: object): PreviewEvent => ({ format_id: PREVIEW_FORMAT, session_id: 's', epoch: 'e', run_id: 'r', document_revision: 'd', type, seq, payload })
it('preserves false, zero and null; isolates invocations and rejects reverse terminal transitions', () => {
  const state = emptyPreviewState('s', 'e')
  reducePreviewEvent(state, message('run.accepted', 1, { run_id: 'r', state: 'accepted', document_revision: 'd' }))
  reducePreviewEvent(state, message('node.started', 2, { node_id: 'n', invocation_id: 'a', status: 'running' }))
  reducePreviewEvent(state, message('node.started', 3, { node_id: 'n', invocation_id: 'b', status: 'running' }))
  reducePreviewEvent(state, message('node.finished', 4, { node_id: 'n', invocation_id: 'a', status: 'succeeded' }))
  expect(state.nodes.b?.status).toBe('running')
  for (const [i, value] of [0, false, null].entries()) reducePreviewEvent(state, message('display.updated', 5 + i, { node_id: `n${i}`, output_port: 'p', payload: { value } }))
  expect(Object.values(state.displays).map(display => display.payload.value)).toEqual([0, false, null])
  reducePreviewEvent(state, message('run.finished', 10, { status: 'succeeded' }))
  expect(reducePreviewEvent(state, message('run.started', 11, {}))).toBe(false)
  expect(reducePreviewEvent(state, { ...message('display.updated', 12, {}), epoch: 'old' })).toBe(false)
  expect(reducePreviewEvent(state, { ...message('display.updated', 12, {}), document_revision: 'old' })).toBe(false)
})

it('resumes atomically at the snapshot watermark and accepts progress sequence gaps', () => {
  const state = emptyPreviewState('s', 'e')
  reducePreviewEvent(state, message('session.snapshot', 20, { watermark: 20, run: { run_id: 'r', state: 'running', document_revision: 'd' }, nodes: [], displays: [] }))
  expect(reducePreviewEvent(state, message('node.started', 19, { node_id: 'n', invocation_id: 'a' }))).toBe(false)
  expect(reducePreviewEvent(state, message('node.started', 22, { node_id: 'n', invocation_id: 'a', status: 'running' }))).toBe(true)
})
