import { onBeforeUnmount, ref, watch } from 'vue'

import { useSessionStore } from '@/app/stores/session.store'
import { ResourceStreamClient } from '@/shared/ws/resource-stream-client'
import type { ResourceStreamState, TaskEvent, WebSocketEnvelope } from '@/shared/contracts'

export function useTaskEvents(
  getTaskId: () => string,
  onTaskEvent: (event: TaskEvent) => void,
  getAfterCursor: () => string | null = () => null,
) {
  const sessionStore = useSessionStore()
  const streamState = ref<ResourceStreamState | null>(null)
  let client: ResourceStreamClient | null = null
  let disposed = false
  let generation = 0

  function start(): void {
    if (disposed || client !== null) return
    if (!sessionStore.isAuthenticated || !sessionStore.websocketQueryTokenEnabled) {
      return
    }
    const taskId = getTaskId()
    if (!taskId) return
    const currentGeneration = generation
    const isCurrent = () => !disposed && generation === currentGeneration && getTaskId() === taskId
    client = new ResourceStreamClient({
      stream: 'tasks.events',
      path: '/tasks/events',
      resourceId: taskId,
      query: { task_id: taskId, after_cursor: getAfterCursor() },
      getAccessToken: () => sessionStore.accessToken,
      queryTokenEnabled: () => sessionStore.websocketQueryTokenEnabled,
      onMessage: (message: WebSocketEnvelope) => {
        if (!isCurrent()) return
        if (message.payload.task_id !== taskId) return
        if (!message.event_type.endsWith('.connected') && !message.event_type.endsWith('.heartbeat')) {
          onTaskEvent({
            ...(message.payload as Record<string, unknown>),
            event_type: message.event_type,
            occurred_at: message.occurred_at,
            payload: (message.payload as Record<string, unknown>).data as Record<string, unknown> | undefined,
          })
        }
      },
      onStateChange: (state) => {
        if (!isCurrent()) return
        streamState.value = state
      },
    })
    client.connect()
  }

  function stop(): void {
    generation += 1
    client?.close()
    client = null
    streamState.value = null
  }

  watch(getTaskId, stop, { flush: 'sync' })
  onBeforeUnmount(() => {
    disposed = true
    stop()
  })

  return { streamState, start, stop }
}
