import { onBeforeUnmount, ref } from 'vue'

import { useSessionStore } from '@/app/stores/session.store'
import type { ResourceStreamState, WebSocketEnvelope } from '@/shared/contracts'
import { ResourceStreamClient } from '@/shared/ws/resource-stream-client'

export const TRAINING_TELEMETRY_PROTOCOL = 'training.telemetry.v1'

export interface TrainingTelemetryPayload {
  protocol: typeof TRAINING_TELEMETRY_PROTOCOL
  task_id: string
  attempt_id?: string | null
  attempt_no: number
  sequence: number
  timestamp: string
  task_type: string
  model_type: string
  stage: string
  granularity: 'batch' | 'epoch' | 'validation' | 'runtime'
  epoch?: number | null
  epoch_index?: number | null
  max_epochs?: number | null
  step?: number | null
  steps_per_epoch?: number | null
  global_step?: number | null
  total_steps?: number | null
  progress_percent?: number | null
  learning_rate?: number | null
  metrics: Record<string, number>
  input_size?: number[] | null
  runtime: Record<string, unknown>
}

export function useTrainingTelemetry(
  getTaskId: () => string,
  onTelemetry: (payload: TrainingTelemetryPayload) => void,
  onSnapshotRequired: () => void,
) {
  const sessionStore = useSessionStore()
  const streamState = ref<ResourceStreamState | null>(null)
  let client: ResourceStreamClient | null = null

  function start(): void {
    if (client !== null) return
    if (!sessionStore.isAuthenticated || !sessionStore.websocketQueryTokenEnabled) return
    const taskId = getTaskId()
    if (!taskId) return
    client = new ResourceStreamClient({
      stream: 'training.telemetry',
      path: '/training/telemetry',
      resourceId: taskId,
      query: { task_id: taskId, limit: 500 },
      getAccessToken: () => sessionStore.accessToken,
      queryTokenEnabled: () => sessionStore.websocketQueryTokenEnabled,
      onMessage: (message: WebSocketEnvelope) => {
        if (message.event_type.endsWith('.lagging')) {
          onSnapshotRequired()
          return
        }
        if (!message.event_type.startsWith('training.')) return
        const payload = readTrainingTelemetryPayload(message.payload)
        if (payload !== null) onTelemetry(payload)
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

function readTrainingTelemetryPayload(value: unknown): TrainingTelemetryPayload | null {
  if (!isRecord(value) || value.protocol !== TRAINING_TELEMETRY_PROTOCOL) return null
  if (
    typeof value.task_id !== 'string'
    || typeof value.attempt_no !== 'number'
    || !Number.isInteger(value.attempt_no)
    || typeof value.sequence !== 'number'
    || !Number.isInteger(value.sequence)
    || typeof value.timestamp !== 'string'
    || typeof value.task_type !== 'string'
    || typeof value.model_type !== 'string'
    || typeof value.stage !== 'string'
    || !['batch', 'epoch', 'validation', 'runtime'].includes(String(value.granularity))
    || !isRecord(value.metrics)
    || !isRecord(value.runtime)
  ) return null
  const metrics = Object.fromEntries(
    Object.entries(value.metrics).filter((entry): entry is [string, number] => (
      typeof entry[1] === 'number' && Number.isFinite(entry[1])
    )),
  )
  return {
    ...(value as unknown as TrainingTelemetryPayload),
    metrics,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
