import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import { ApiError } from '@/shared/api/error'
import {
  matchesRuntimePreview,
  type RuntimePreviewFrame,
  type RuntimePreviewSnapshot,
  useRuntimePreview,
} from './useRuntimePreview'

const previewMocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))

vi.mock('@/shared/api/http-client', () => ({ apiRequest: previewMocks.apiRequest }))
vi.mock('@/platform/runtime/runtime-config', () => ({
  getRuntimeConfig: () => ({ wsBaseUrl: 'ws://runtime.test/ws/v1' }),
}))

class FakeWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []

  readonly url: string
  readyState = FakeWebSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readonly sent: string[] = []

  constructor(url: string | URL) {
    this.url = String(url)
    FakeWebSocket.instances.push(this)
  }

  send(value: string): void {
    this.sent.push(value)
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.(new CloseEvent('close', { code: 1_000 }))
  }

  emitMessage(value: object): void {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent<string>)
  }

  emitClose(code = 1_006): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.(new CloseEvent('close', { code }))
  }
}

describe('runtime preview identity', () => {
  const snapshot = { workflow_runtime_id: 'runtime', workflow_runtime_revision_id: 'revision', workflow_app_version_id: 'version', runtime_generation: 3, worker_instance_id: 'worker', snapshot_fingerprint: 'hash' } as RuntimePreviewSnapshot
  const frame = { ...snapshot, format_id: 'amvision.workflow-runtime-preview.v1', workflow_run_id: 'run', sequence: 5, displays: [] } as unknown as RuntimePreviewFrame
  it('accepts only this actual worker and newer run', () => {
    expect(matchesRuntimePreview(snapshot, frame, 4)).toBe(true)
    expect(matchesRuntimePreview(snapshot, frame, 5)).toBe(false)
    for (const key of ['workflow_runtime_id', 'workflow_runtime_revision_id', 'workflow_app_version_id', 'worker_instance_id', 'snapshot_fingerprint']) {
      expect(matchesRuntimePreview(snapshot, { ...frame, [key]: 'old' }, 4)).toBe(false)
    }
    expect(matchesRuntimePreview(snapshot, { ...frame, runtime_generation: 2 }, 4)).toBe(false)
  })
})

describe('runtime preview reconnect', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useSessionStore().$patch({
      accessToken: 'token',
      websocketQueryTokenEnabled: true,
    })
    previewMocks.apiRequest.mockReset()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('follows a stopped runtime to its replacement worker without manual refresh', async () => {
    const first = buildSnapshot('worker-old', 'running')
    const stopped = buildSnapshot(null, 'stopped')
    const restarted = buildSnapshot('worker-new', 'running')
    previewMocks.apiRequest
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(stopped)
      .mockResolvedValueOnce(restarted)
    let preview: ReturnType<typeof useRuntimePreview> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        preview = useRuntimePreview()
        return () => h('div')
      },
    }))

    await preview!.load(first.workflow_runtime_id)
    const oldSocket = FakeWebSocket.instances[0]!
    oldSocket.emitMessage({ format_id: 'amvision.workflow-runtime-preview.v1', state: 'connected' })
    oldSocket.emitMessage(buildFrame(first, 12, 'run-old'))
    await flushPromises()
    expect(preview!.lastRun.value?.workflow_run_id).toBe('run-old')
    expect(oldSocket.sent).toEqual(['ready'])

    oldSocket.emitClose()
    expect(preview!.status.value).toBe('disconnected')
    await vi.advanceTimersByTimeAsync(4_000)
    await flushPromises()
    expect(preview!.status.value).toBe('stopped')
    expect(FakeWebSocket.instances).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(2_000)
    await flushPromises()
    expect(FakeWebSocket.instances).toHaveLength(2)
    const newSocket = FakeWebSocket.instances[1]!
    expect(newSocket.url).toContain('worker_instance_id=worker-new')
    expect(preview!.lastRun.value).toBeNull()
    newSocket.emitMessage({ format_id: 'amvision.workflow-runtime-preview.v1', state: 'connected' })
    newSocket.emitMessage(buildFrame(restarted, 1, 'run-new'))
    await flushPromises()
    expect(preview!.status.value).toBe('live')
    expect(preview!.lastRun.value?.workflow_run_id).toBe('run-new')
    expect(newSocket.sent).toEqual(['ready'])

    wrapper.unmount()
    newSocket.emitClose()
    await vi.advanceTimersByTimeAsync(4_000)
    expect(previewMocks.apiRequest).toHaveBeenCalledTimes(3)
  })

  it('does not retry a permanent missing-runtime response', async () => {
    previewMocks.apiRequest.mockRejectedValue(new ApiError(404, { message: 'missing' }))
    let preview: ReturnType<typeof useRuntimePreview> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        preview = useRuntimePreview()
        return () => h('div')
      },
    }))

    await preview!.load('runtime-missing')
    await vi.advanceTimersByTimeAsync(10_000)
    expect(previewMocks.apiRequest).toHaveBeenCalledTimes(1)
    expect(preview!.status.value).toBe('disconnected')
    wrapper.unmount()
  })

  it('preserves the last display when the same runtime is refreshed', async () => {
    const current = buildSnapshot('worker-1', 'running')
    previewMocks.apiRequest.mockResolvedValue(current)
    let preview: ReturnType<typeof useRuntimePreview> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        preview = useRuntimePreview()
        return () => h('div')
      },
    }))

    await preview!.load(current.workflow_runtime_id)
    FakeWebSocket.instances[0]!.emitMessage(buildFrame(current, 1, 'run-current'))
    await flushPromises()
    await preview!.load(current.workflow_runtime_id)

    expect(preview!.lastRun.value?.workflow_run_id).toBe('run-current')
    expect(FakeWebSocket.instances).toHaveLength(2)
    wrapper.unmount()
  })

  it('clears the last display when refresh detects a replacement worker', async () => {
    const current = buildSnapshot('worker-1', 'running')
    const replacement = {
      ...current,
      runtime_generation: 2,
      worker_instance_id: 'worker-2',
      snapshot_fingerprint: 'fingerprint-2',
    }
    previewMocks.apiRequest
      .mockResolvedValueOnce(current)
      .mockResolvedValueOnce(replacement)
    let preview: ReturnType<typeof useRuntimePreview> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        preview = useRuntimePreview()
        return () => h('div')
      },
    }))

    await preview!.load(current.workflow_runtime_id)
    FakeWebSocket.instances[0]!.emitMessage(buildFrame(current, 1, 'run-old'))
    await flushPromises()
    await preview!.load(current.workflow_runtime_id)

    expect(preview!.lastRun.value).toBeNull()
    wrapper.unmount()
  })

  it('does not retry automatically after the fixed connection limit is reached', async () => {
    const current = buildSnapshot('worker-1', 'running')
    previewMocks.apiRequest.mockResolvedValue(current)
    let preview: ReturnType<typeof useRuntimePreview> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        preview = useRuntimePreview()
        return () => h('div')
      },
    }))

    await preview!.load(current.workflow_runtime_id)
    FakeWebSocket.instances[0]!.emitClose(4_429)
    await vi.advanceTimersByTimeAsync(30_000)

    expect(preview!.status.value).toBe('capacityExceeded')
    expect(previewMocks.apiRequest).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('retries a WebSocket that never acknowledges the connection', async () => {
    const current = buildSnapshot('worker-1', 'running')
    previewMocks.apiRequest.mockResolvedValue(current)
    let preview: ReturnType<typeof useRuntimePreview> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        preview = useRuntimePreview()
        return () => h('div')
      },
    }))

    await preview!.load(current.workflow_runtime_id)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(preview!.status.value).toBe('disconnected')
    await vi.advanceTimersByTimeAsync(2_000)
    await flushPromises()

    expect(previewMocks.apiRequest).toHaveBeenCalledTimes(2)
    expect(FakeWebSocket.instances).toHaveLength(2)
    wrapper.unmount()
  })
})

function buildSnapshot(
  workerInstanceId: string | null,
  observedState: string,
): RuntimePreviewSnapshot {
  return {
    workflow_runtime_id: 'runtime-1',
    workflow_runtime_revision_id: 'revision-1',
    workflow_app_version_id: 'version-1',
    runtime_generation: 1,
    worker_instance_id: workerInstanceId,
    snapshot_fingerprint: 'fingerprint-1',
    project_id: 'project-1',
    application_id: 'app-1',
    observed_state: observedState,
    active: observedState === 'running',
    display_name: 'Runtime',
    application: { format_id: 'amvision.flow-application.v1' } as RuntimePreviewSnapshot['application'],
    contract: {
      format_id: 'amvision.workflow-app-contract.v1',
      application_id: 'app-1',
      inputs: [],
      outputs: [],
    },
    app_mode: null,
    template: { format_id: 'amvision.workflow-graph-template.v1', nodes: [] } as unknown as RuntimePreviewSnapshot['template'],
    node_definitions: [],
    node_definition_warnings: [],
  }
}

function buildFrame(
  snapshot: RuntimePreviewSnapshot,
  sequence: number,
  workflowRunId: string,
): RuntimePreviewFrame {
  return {
    format_id: 'amvision.workflow-runtime-preview.v1',
    workflow_runtime_id: snapshot.workflow_runtime_id,
    workflow_runtime_revision_id: snapshot.workflow_runtime_revision_id,
    workflow_app_version_id: snapshot.workflow_app_version_id,
    runtime_generation: snapshot.runtime_generation,
    worker_instance_id: snapshot.worker_instance_id!,
    snapshot_fingerprint: snapshot.snapshot_fingerprint,
    workflow_run_id: workflowRunId,
    sequence,
    state: 'succeeded',
    finished_at: '2026-09-05T00:00:00Z',
    error_message: null,
    display_error: null,
    displays: [],
  }
}
