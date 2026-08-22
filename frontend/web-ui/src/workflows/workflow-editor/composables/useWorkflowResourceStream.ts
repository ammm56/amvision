import { onBeforeUnmount, ref } from 'vue'

import { useSessionStore } from '@/app/stores/session.store'
import type { ResourceStreamState, WebSocketEnvelope } from '@/shared/contracts'
import { isControlEvent } from '@/shared/contracts'
import { ResourceStreamClient } from '@/shared/ws/resource-stream-client'

export type WorkflowResourceStreamKind = 'preview-run' | 'run' | 'app-runtime'

interface WorkflowResourceStreamSpec {
  stream: string
  path: string
  queryKey: string
  terminalEventTypes: ReadonlySet<string>
  refreshEveryBusinessEvent: boolean
}

export interface WorkflowResourceStreamOptions<TSnapshot> {
  kind: WorkflowResourceStreamKind
  getSnapshot: (resourceId: string) => Promise<TSnapshot>
  onSnapshot: (snapshot: TSnapshot) => void
  isTerminal: (snapshot: TSnapshot) => boolean
  pollingIntervalMs?: number
  onError?: (error: unknown) => void
}

const DEFAULT_POLLING_INTERVAL_MS = 2000

const STREAM_SPECS: Record<WorkflowResourceStreamKind, WorkflowResourceStreamSpec> = {
  'preview-run': {
    stream: 'workflows.preview-runs.events',
    path: '/workflows/preview-runs/events',
    queryKey: 'preview_run_id',
    terminalEventTypes: new Set([
      'preview.succeeded',
      'preview.failed',
      'preview.timed_out',
      'preview.cancelled',
    ]),
    refreshEveryBusinessEvent: true,
  },
  run: {
    stream: 'workflows.runs.events',
    path: '/workflows/runs/events',
    queryKey: 'workflow_run_id',
    terminalEventTypes: new Set([
      'run.succeeded',
      'run.failed',
      'run.cancelled',
      'run.timed_out',
    ]),
    refreshEveryBusinessEvent: true,
  },
  'app-runtime': {
    stream: 'workflows.app-runtimes.events',
    path: '/workflows/app-runtimes/events',
    queryKey: 'workflow_runtime_id',
    terminalEventTypes: new Set(),
    refreshEveryBusinessEvent: true,
  },
}

/**
 * 订阅现有 Workflow WebSocket 资源流；断线时退回轮询，终态和 lagging
 * 都通过 REST 快照收敛，避免把事件载荷误当作完整资源记录。
 */
export function useWorkflowResourceStream<TSnapshot>(
  options: WorkflowResourceStreamOptions<TSnapshot>,
) {
  const sessionStore = useSessionStore()
  const streamState = ref<ResourceStreamState | null>(null)
  const activeResourceId = ref<string | null>(null)
  const spec = STREAM_SPECS[options.kind]
  const pollingIntervalMs = Math.max(
    250,
    options.pollingIntervalMs ?? DEFAULT_POLLING_INTERVAL_MS,
  )
  let client: ResourceStreamClient | null = null
  let pollingTimer: number | null = null
  let refreshPromise: Promise<void> | null = null

  function start(resourceId: string): void {
    const normalizedResourceId = resourceId.trim()
    if (!normalizedResourceId) {
      stop()
      return
    }
    if (activeResourceId.value === normalizedResourceId && client !== null) return
    stop()
    activeResourceId.value = normalizedResourceId
    startPolling()
    if (!sessionStore.isAuthenticated || !sessionStore.websocketQueryTokenEnabled) return
    client = new ResourceStreamClient({
      stream: spec.stream,
      path: spec.path,
      resourceId: normalizedResourceId,
      query: {
        [spec.queryKey]: normalizedResourceId,
        limit: 200,
      },
      getAccessToken: () => sessionStore.accessToken,
      queryTokenEnabled: () => sessionStore.websocketQueryTokenEnabled,
      onMessage: handleMessage,
      onStateChange: (state) => {
        streamState.value = state
        if (state.connected && !state.stale) {
          stopPolling()
          return
        }
        startPolling()
      },
    })
    try {
      client.connect()
    } catch (error) {
      options.onError?.(error)
      client.close()
      client = null
      startPolling()
    }
  }

  function stop(): void {
    client?.close()
    client = null
    stopPolling()
    activeResourceId.value = null
    streamState.value = null
  }

  function handleMessage(message: WebSocketEnvelope): void {
    if (message.event_type.endsWith('.lagging')) {
      void refreshAuthoritativeSnapshot()
      startPolling()
      return
    }
    if (isControlEvent(message.event_type)) return
    if (
      spec.refreshEveryBusinessEvent
      || spec.terminalEventTypes.has(message.event_type)
    ) {
      void refreshAuthoritativeSnapshot()
    }
  }

  function startPolling(): void {
    if (pollingTimer !== null || activeResourceId.value === null) return
    pollingTimer = window.setInterval(() => {
      void refreshAuthoritativeSnapshot()
    }, pollingIntervalMs)
  }

  function stopPolling(): void {
    if (pollingTimer === null) return
    window.clearInterval(pollingTimer)
    pollingTimer = null
  }

  async function refreshAuthoritativeSnapshot(): Promise<void> {
    if (refreshPromise !== null) return refreshPromise
    const resourceId = activeResourceId.value
    if (resourceId === null) return
    refreshPromise = (async () => {
      try {
        const snapshot = await options.getSnapshot(resourceId)
        if (activeResourceId.value !== resourceId) return
        options.onSnapshot(snapshot)
        if (options.isTerminal(snapshot)) stop()
      } catch (error) {
        if (activeResourceId.value === resourceId) options.onError?.(error)
      } finally {
        refreshPromise = null
      }
    })()
    return refreshPromise
  }

  onBeforeUnmount(stop)

  return {
    activeResourceId,
    streamState,
    start,
    stop,
    refreshNow: refreshAuthoritativeSnapshot,
  }
}
