import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useWorkflowPreviewSession } from './useWorkflowPreviewSession'
import { useSessionStore } from '@/app/stores/session.store'
import type { WorkflowPreviewRunActionInput } from '../actions/useWorkflowEditorActions'

const io = vi.hoisted(() => ({ options: null as any, create: vi.fn(), submit: vi.fn(), release: vi.fn(), cancel: vi.fn(), upload: vi.fn(), close: vi.fn(), revision: '', pendingResources: 0, snapshot: null as any, connectError: '' }))
vi.mock('../services/workflow-preview-session.service', () => ({
  PREVIEW_FORMAT: 'amvision.workflow-preview-session.v1',
  createPreviewSession: io.create, submitPreviewSession: io.submit, releasePreviewSession: io.release, cancelPreviewSession: io.cancel,
  PreviewSessionConnection: class {
    constructor(public identity: any, options: any) { io.options = options }
    async connect() {
      if (io.connectError) { io.options.onConnection(false, io.connectError, true); throw new Error(io.connectError) }
      io.options.onEvent(event('session.snapshot', io.snapshot ?? { watermark: 0, run: null, nodes: [], displays: [] }, 0))
    }
    upload = io.upload
    close = io.close
    readBlob = vi.fn()
    resourceStatus = () => ({ pending: io.pendingResources, errors: [] })
  },
}))
const identity = { format_id: 'amvision.workflow-preview-session.v1', session_id: 'session', epoch: 'epoch', memory_limit_bytes: 1 }
const input = { projectId: 'p', application: { application_id: 'a' }, template: {}, inputBindings: {} } as WorkflowPreviewRunActionInput
function event(type: string, payload: object, seq: number) {
  return { ...identity, run_id: seq ? 'run' : null, document_revision: seq ? io.revision : null, type, payload, seq }
}
beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  io.pendingResources = 0
  io.snapshot = null
  io.connectError = ''
  sessionStorage.clear()
  useSessionStore().currentUser = { principal_id: 'u' } as any
  io.create.mockResolvedValue(identity)
  io.release.mockResolvedValue(undefined)
  io.submit.mockImplementation(async (_sid, body) => {
    io.revision = body.document_revision
    io.options.onEvent(event('run.accepted', { run_id: 'run', document_revision: io.revision, state: 'accepted' }, 1))
    return { ...identity, run_id: 'run', state: 'accepted' }
  })
})

it('shows node display before the graph finishes and ignores duplicate events', async () => {
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  await session.execute(input, session.begin({ projectId: 'p', applicationId: 'a' }))
  io.options.onEvent(event('run.started', {}, 2))
  const display = event('display.updated', { node_id: 'n', node_type_id: 'core.value-preview', output_port: 'preview', payload: { type: 'value-preview', value: 0 } }, 3)
  io.options.onEvent(display)
  io.options.onEvent(display)
  await flushPromises()
  expect(session.previewing.value).toBe(true)
  const updates = feedback.mock.calls.filter(call => !call[1]?.markStale)
  expect(updates).toHaveLength(1)
  expect(updates[0]![0].node_records[0].outputs.preview.value).toBe(0)
  expect(updates[0]![1].incremental).toBe(true)
  session.reset()
})

it('keeps successful execution separate from display loading failures', async () => {
  const session = useWorkflowPreviewSession(), feedback = vi.fn().mockImplementation((_run, options) => options?.markStale ? Promise.resolve() : Promise.reject(new Error('decode')))
  session.setFeedback(feedback)
  await session.execute(input, session.begin({ projectId: 'p', applicationId: 'a' }))
  io.options.onEvent(event('display.updated', { node_id: 'n', output_port: 'preview', payload: { type: 'value-preview', value: false } }, 2))
  await flushPromises()
  io.options.onEvent(event('run.finished', { status: 'succeeded' }, 3))
  await flushPromises()
  expect(session.lastPreviewRun.value?.state).toBe('succeeded')
  expect(session.previewing.value).toBe(false)
  expect(session.displayError.value).toBe('decode')
  session.reset()
})

it('ignores events from the previous app after switching and releases its session', async () => {
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  await session.execute(input, session.begin({ projectId: 'p', applicationId: 'a' }))
  feedback.mockClear()
  const previous = io.options
  session.begin({ projectId: 'p', applicationId: 'b' })
  previous.onEvent(event('run.finished', { status: 'succeeded' }, 2))
  expect(session.lastPreviewRun.value).toBeNull()
  expect(io.release).toHaveBeenCalledWith('session')
  expect(feedback).not.toHaveBeenCalled()
  session.reset()
})

it('cancelling only requests cancellation and waits for the real terminal event', async () => {
  const session = useWorkflowPreviewSession()
  await session.execute(input, session.begin({ projectId: 'p', applicationId: 'a' }))
  await session.cancel()
  expect(io.cancel).toHaveBeenCalledWith('session', 'run')
  expect(session.previewing.value).toBe(true)
  io.options.onEvent(event('run.finished', { status: 'cancelled' }, 2))
  expect(session.previewing.value).toBe(false)
  session.reset()
})

it('records full delivery only after current-run resources complete', async () => {
  const session = useWorkflowPreviewSession()
  await session.execute(input, session.begin({ projectId: 'p', applicationId: 'a' }))
  io.pendingResources = 1
  io.options.onEvent(event('run.finished', { status: 'succeeded', delivery_state: 'pending' }, 2))
  io.options.onEvent(event('run.outputs', { delivery_state: 'ready' }, 3))
  await flushPromises()
  expect(sessionStorage.length).toBe(1)
  expect(session.lastPreviewRun.value?.timings?.client_total_ms).toBeUndefined()
  io.pendingResources = 0
  io.options.onResources()
  await flushPromises()
  expect(session.lastPreviewRun.value?.timings?.client_total_ms).toBeGreaterThanOrEqual(0)
  expect(sessionStorage.length).toBe(0)
  const previousView = session.lastPreviewRun.value
  session.begin({ projectId: 'p', applicationId: 'a' })
  io.options.onResources()
  await flushPromises()
  // 上轮 Blob 的迟到回调不得把尚未上传的新运行标记为完整交付。
  expect(session.lastPreviewRun.value).toBe(previousView)
  session.reset()
})

it('restores partial history once without treating released resources as execution errors', async () => {
  const session = useWorkflowPreviewSession()
  sessionStorage.setItem('amvision.preview-session.v1:["u","p","a"]', JSON.stringify(identity))
  io.snapshot = { watermark: 0, run: { run_id: 'run', state: 'succeeded', delivery_state: 'ready' }, nodes: [], displays: [], values: [], expired_resources: 3 }
  await session.restore('p', 'a')
  await flushPromises()
  expect(session.resultsExpired.value).toBe(true)
  expect(session.displayError.value).toBeNull()
  expect(session.queryError.value).toBeNull()
  expect(sessionStorage.length).toBe(0)
  session.begin({ projectId: 'p', applicationId: 'a' })
  expect(session.resultsExpired.value).toBe(false)
  session.reset()
})

it('removes an expired stored identity instead of retrying it after every reload', async () => {
  const session = useWorkflowPreviewSession()
  sessionStorage.setItem('amvision.preview-session.v1:["u","p","a"]', JSON.stringify(identity))
  io.connectError = 'preview_session_expired'
  await session.restore('p', 'a')
  expect(session.queryError.value).toBeNull()
  expect(session.resultsExpired.value).toBe(true)
  expect(sessionStorage.length).toBe(0)
  expect(session.previewing.value).toBe(false)
  session.reset()
})
