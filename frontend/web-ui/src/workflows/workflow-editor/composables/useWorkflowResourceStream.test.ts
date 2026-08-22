import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import type { ResourceStreamState, WebSocketEnvelope } from '@/shared/contracts'
import type { WorkflowRun } from '../types'
import { useWorkflowResourceStream } from './useWorkflowResourceStream'

const resourceStreamMock = vi.hoisted(() => {
  class Client {
    static instances: Client[] = []

    connected = false
    closed = false

    constructor(readonly options: {
      stream: string
      path: string
      resourceId: string
      query?: Record<string, string | number | boolean | null | undefined>
      onMessage: (message: WebSocketEnvelope) => void
      onStateChange?: (state: ResourceStreamState) => void
    }) {
      Client.instances.push(this)
    }

    connect(): void {
      this.connected = true
    }

    close(): void {
      this.closed = true
    }
  }
  return { Client }
})

vi.mock('@/shared/ws/resource-stream-client', () => ({
  ResourceStreamClient: resourceStreamMock.Client,
}))

describe('useWorkflowResourceStream', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resourceStreamMock.Client.instances = []
    vi.useFakeTimers()
  })

  it('uses the existing Run stream and converges terminal events through REST', async () => {
    authenticateSession()
    const snapshots: WorkflowRun[] = []
    const getSnapshot = vi.fn().mockResolvedValue(buildRun('timed_out'))
    let stream: ReturnType<typeof useWorkflowResourceStream<WorkflowRun>> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        stream = useWorkflowResourceStream<WorkflowRun>({
          kind: 'run',
          getSnapshot,
          onSnapshot: (snapshot) => snapshots.push(snapshot),
          isTerminal: (snapshot) => snapshot.state === 'timed_out',
          pollingIntervalMs: 250,
        })
        return () => h('div')
      },
    }))

    stream!.start('workflow-run-1')
    const client = resourceStreamMock.Client.instances[0]
    expect(client.options).toMatchObject({
      stream: 'workflows.runs.events',
      path: '/workflows/runs/events',
      resourceId: 'workflow-run-1',
      query: { workflow_run_id: 'workflow-run-1', limit: 200 },
    })

    client.options.onMessage(buildMessage('run.timed_out'))
    await flushPromises()

    expect(getSnapshot).toHaveBeenCalledWith('workflow-run-1')
    expect(snapshots.map((snapshot) => snapshot.state)).toEqual(['timed_out'])
    expect(client.closed).toBe(true)
    expect(stream!.activeResourceId.value).toBeNull()
    wrapper.unmount()
  })

  it('refreshes a lagging AppRuntime stream through the authoritative REST endpoint', async () => {
    authenticateSession()
    const getSnapshot = vi.fn().mockResolvedValue({
      workflow_runtime_id: 'runtime-1',
      observed_state: 'running',
    })
    let stream: ReturnType<typeof useWorkflowResourceStream<Record<string, unknown>>> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        stream = useWorkflowResourceStream<Record<string, unknown>>({
          kind: 'app-runtime',
          getSnapshot,
          onSnapshot: vi.fn(),
          isTerminal: () => false,
        })
        return () => h('div')
      },
    }))

    stream!.start('runtime-1')
    resourceStreamMock.Client.instances[0].options.onMessage(
      buildMessage('workflows.app-runtimes.lagging'),
    )
    await flushPromises()

    expect(getSnapshot).toHaveBeenCalledWith('runtime-1')
    expect(stream!.activeResourceId.value).toBe('runtime-1')
    wrapper.unmount()
  })

  it('keeps polling as a fallback when WebSocket query authentication is unavailable', async () => {
    const snapshots = [buildRun('running'), buildRun('succeeded')]
    const getSnapshot = vi.fn()
      .mockResolvedValueOnce(snapshots[0])
      .mockResolvedValueOnce(snapshots[1])
    const received: WorkflowRun[] = []
    let stream: ReturnType<typeof useWorkflowResourceStream<WorkflowRun>> | null = null
    const wrapper = mount(defineComponent({
      setup() {
        stream = useWorkflowResourceStream<WorkflowRun>({
          kind: 'preview-run',
          getSnapshot,
          onSnapshot: (snapshot) => received.push(snapshot),
          isTerminal: (snapshot) => snapshot.state === 'succeeded',
          pollingIntervalMs: 250,
        })
        return () => h('div')
      },
    }))

    stream!.start('preview-run-1')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()

    expect(resourceStreamMock.Client.instances).toHaveLength(0)
    expect(received.map((snapshot) => snapshot.state)).toEqual(['running', 'succeeded'])
    expect(stream!.activeResourceId.value).toBeNull()
    wrapper.unmount()
  })
})

function authenticateSession(): void {
  useSessionStore().$patch({
    accessToken: 'token',
    websocketQueryTokenEnabled: true,
    currentUser: {
      principal_id: 'user-1',
      principal_type: 'user',
      project_ids: ['project-1'],
      scopes: ['workflows:read'],
      username: 'user',
      display_name: 'User',
      auth_provider_kind: 'local',
      auth_credential_kind: 'session',
    },
  })
}

function buildMessage(eventType: string): WebSocketEnvelope {
  return {
    stream: 'workflows.runs.events',
    event_type: eventType,
    event_version: 'v1',
    occurred_at: '2026-08-22T00:00:00Z',
    resource_kind: 'workflow_run',
    resource_id: 'workflow-run-1',
    cursor: '1',
    payload: {},
  }
}

function buildRun(state: WorkflowRun['state']): WorkflowRun {
  return {
    format_id: 'amvision.workflow-run.v1',
    workflow_run_id: 'workflow-run-1',
    workflow_runtime_id: 'workflow-runtime-1',
    project_id: 'project-1',
    application_id: 'application-1',
    state,
    created_at: '2026-08-22T00:00:00Z',
    requested_timeout_seconds: 30,
    input_payload: {},
    outputs: {},
    template_outputs: {},
    node_records: [],
    metadata: {},
  }
}
