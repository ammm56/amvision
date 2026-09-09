import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useWorkflowPreviewSession } from './useWorkflowPreviewSession'
import { useSessionStore } from '@/app/stores/session.store'
import { ApiError } from '@/shared/api/error'
import type { WorkflowPreviewRun } from '../types'

const io = vi.hoisted(() => ({ load: vi.fn(), get: vi.fn(), stream: vi.fn(), stop: vi.fn() }))
vi.mock('@/platform/i18n', () => ({ translate: (key: string) => key }))
vi.mock('./previewDisplayResults', () => ({ loadPreviewDisplayResult: io.load }))
vi.mock('../services/workflow-runtime.service', () => ({ getWorkflowPreviewRun: io.get }))
vi.mock('../composables/useWorkflowResourceStream', () => ({ useWorkflowResourceStream: io.stream }))
const run = (id = 'run', state = 'succeeded') => ({ preview_run_id: id, project_id: 'p', application_id: 'a', state,
  node_records: [], metadata: {}, outputs: {}, template_outputs: {} }) as unknown as WorkflowPreviewRun

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  sessionStorage.clear()
  useSessionStore().currentUser = { principal_id: 'u' } as NonNullable<ReturnType<typeof useSessionStore>['currentUser']>
  io.stream.mockReturnValue({ start: vi.fn(), stop: io.stop, refreshNow: vi.fn() })
  io.load.mockImplementation(async (r) => ({ run: r, errors: [] }))
})

it('deduplicates fast terminal, repeated subscription and poll results', async () => {
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  const token = session.begin({ projectId: 'p', applicationId: 'a' })
  await session.accepted(run(), token)
  io.stream.mock.calls[0]![0].onSnapshot(run())
  await flushPromises()
  expect(feedback).toHaveBeenCalledTimes(1)
  expect(io.load).toHaveBeenCalledTimes(1)
  expect(sessionStorage.length).toBe(0)
})

it('restores a terminal run with the same completion feedback', async () => {
  io.get.mockResolvedValue(run())
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  await session.restore('p', 'a', 'run')
  expect(feedback).toHaveBeenCalledTimes(1)
  expect(session.displayState.value).toBe('ready')
})

it('aborts old result loading and rejects late results after switching app', async () => {
  let release!: (value: unknown) => void
  io.load.mockImplementation(() => new Promise((resolve) => { release = resolve }))
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  const token = session.begin({ projectId: 'p', applicationId: 'a' })
  const first = session.accepted(run(), token)
  const signal = io.load.mock.calls[0]![1] as AbortSignal
  session.begin({ projectId: 'p', applicationId: 'other' })
  expect(signal.aborted).toBe(true)
  release({ run: run(), errors: [] })
  await first
  expect(feedback).not.toHaveBeenCalled()
  expect(session.lastPreviewRun.value).toBeNull()
})

it('keeps business success separate from a retryable display failure', async () => {
  io.load.mockRejectedValueOnce(new Error('network'))
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  await session.accepted(run(), session.begin({ projectId: 'p', applicationId: 'a' }))
  expect(session.lastPreviewRun.value?.state).toBe('succeeded')
  expect(session.displayState.value).toBe('failed')
  expect(sessionStorage.length).toBe(1)
  await session.retry()
  expect(session.displayState.value).toBe('ready')
  expect(sessionStorage.length).toBe(0)
})

it.each(['failed', 'cancelled', 'timed_out'])('loads completed display nodes after %s', async (state) => {
  const session = useWorkflowPreviewSession(), feedback = vi.fn()
  session.setFeedback(feedback)
  await session.accepted(run('run', state), session.begin({ projectId: 'p', applicationId: 'a' }))
  expect(feedback).toHaveBeenCalledWith(expect.objectContaining({ state }), expect.anything())
  expect(session.previewing.value).toBe(false)
})

it('reports a missing record and stops invalid subscriptions', async () => {
  io.get.mockRejectedValue(new ApiError(404, { message: 'missing' }))
  const session = useWorkflowPreviewSession()
  await session.restore('p', 'a', 'missing')
  expect(session.queryError.value).toContain('missing')
  expect(session.previewing.value).toBe(false)
  expect(io.stop).toHaveBeenCalled()
})
