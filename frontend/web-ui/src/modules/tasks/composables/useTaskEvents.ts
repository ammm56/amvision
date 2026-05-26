import { onBeforeUnmount, ref } from 'vue'

import { useSessionStore } from '@/app/stores/session.store'
import { ResourceStreamClient } from '@/shared/ws/resource-stream-client'
import type { ResourceStreamState, TaskEvent, WebSocketEnvelope } from '@/shared/contracts'

export function useTaskEvents(getTaskId: () => string, onTaskEvent: (event: TaskEvent) => void) {
  const sessionStore = useSessionStore()
  const streamState = ref<ResourceStreamState | null>(null)
  let client: ResourceStreamClient | null = null

  function start(): void {
    if (!sessionStore.isAuthenticated || !sessionStore.websocketQueryTokenEnabled) {
      return
    }
    const taskId = getTaskId()
    client = new ResourceStreamClient({
      stream: 'tasks.events',
      path: '/tasks/events',
      resourceId: taskId,
      query: { task_id: taskId },
      getAccessToken: () => sessionStore.accessToken,
      queryTokenEnabled: () => sessionStore.websocketQueryTokenEnabled,
      onMessage: (message: WebSocketEnvelope) => {
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
        streamState.value = state
      },
    })
    client.connect()
  }

  function stop(): void {
    client?.close()
    client = null
  }

  onBeforeUnmount(stop)

  return { streamState, start, stop }
}