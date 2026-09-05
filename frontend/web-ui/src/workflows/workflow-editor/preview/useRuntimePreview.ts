import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { useSessionStore } from '@/app/stores/session.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import { apiRequest } from '@/shared/api/http-client'
import { ApiError } from '@/shared/api/error'
import type { FlowApplication, WorkflowGraphTemplate, WorkflowJsonObject } from '../types'
import { useWorkflowPreviewDisplays } from './useWorkflowPreviewDisplays'

const RUNTIME_PREVIEW_RECONNECT_DELAY_MS = 2_000

export interface RuntimePreviewSnapshot {
  workflow_runtime_id: string
  workflow_runtime_revision_id: string
  workflow_app_version_id: string
  runtime_generation: number
  worker_instance_id: string | null
  snapshot_fingerprint: string
  project_id: string
  application_id: string
  observed_state: string
  active: boolean
  display_name: string
  application: FlowApplication
  template: WorkflowGraphTemplate
}

export interface RuntimePreviewFrame {
  format_id: string
  workflow_runtime_id: string
  workflow_runtime_revision_id: string
  workflow_app_version_id: string
  runtime_generation: number
  worker_instance_id: string
  snapshot_fingerprint: string
  workflow_run_id: string
  sequence: number
  state: string
  finished_at: string
  error_message: string | null
  display_error: string | null
  displays: Array<{
    node_id: string; node_type_id: string; output_port: string
    invocation_id: string; duration_ms: number; payload: WorkflowJsonObject
  }>
}

export function matchesRuntimePreview(snapshot: RuntimePreviewSnapshot, frame: RuntimePreviewFrame, sequence: number): boolean {
  return frame.format_id === 'amvision.workflow-runtime-preview.v1'
    && frame.workflow_runtime_id === snapshot.workflow_runtime_id
    && frame.workflow_runtime_revision_id === snapshot.workflow_runtime_revision_id
    && frame.workflow_app_version_id === snapshot.workflow_app_version_id
    && frame.runtime_generation === snapshot.runtime_generation
    && frame.worker_instance_id === snapshot.worker_instance_id
    && frame.snapshot_fingerprint === snapshot.snapshot_fingerprint
    && Number.isSafeInteger(frame.sequence) && frame.sequence > sequence
    && typeof frame.workflow_run_id === 'string' && Array.isArray(frame.displays)
}

function matchesRuntimeWorker(
  current: RuntimePreviewSnapshot,
  next: RuntimePreviewSnapshot,
): boolean {
  return current.workflow_runtime_id === next.workflow_runtime_id
    && current.workflow_runtime_revision_id === next.workflow_runtime_revision_id
    && current.workflow_app_version_id === next.workflow_app_version_id
    && current.runtime_generation === next.runtime_generation
    && current.worker_instance_id === next.worker_instance_id
    && current.snapshot_fingerprint === next.snapshot_fingerprint
}

function shouldRetrySnapshot(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 429 || error.status >= 500
}

/** Runtime 只读观察；只接后续结果，不创建 Preview、不回放或自动调用。 */
export function useRuntimePreview() {
  const session = useSessionStore()
  const snapshot = shallowRef<RuntimePreviewSnapshot | null>(null)
  const status = ref('disconnected')
  const error = ref('')
  const loading = ref(false)
  const lastRun = shallowRef<Omit<RuntimePreviewFrame, 'displays'> | null>(null)
  const invocations = shallowRef<Record<string, string>>({})
  const displays = useWorkflowPreviewDisplays()
  let socket: WebSocket | null = null
  let generation = 0
  let sequence = 0
  let rendering = false
  let monitoredRuntimeId = ''
  let reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null

  function cancelReconnect() {
    if (reconnectTimer === null) return
    globalThis.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  function clearDisplay() {
    displays.revokePreviewImageObjectUrls()
    lastRun.value = null
    invocations.value = {}
    sequence = 0
  }

  function scheduleReconnect(runtimeId: string, requestGeneration: number) {
    if (
      reconnectTimer !== null
      || generation !== requestGeneration
      || monitoredRuntimeId !== runtimeId
    ) return
    reconnectTimer = globalThis.setTimeout(() => {
      reconnectTimer = null
      void connect(runtimeId, requestGeneration)
    }, RUNTIME_PREVIEW_RECONNECT_DELAY_MS)
  }

  function close() {
    monitoredRuntimeId = ''
    generation += 1
    cancelReconnect()
    const oldSocket = socket
    socket = null
    if (oldSocket) {
      oldSocket.onmessage = null
      oldSocket.onclose = null
      oldSocket.onerror = null
      oldSocket.close()
    }
    status.value = 'disconnected'
    clearDisplay()
    rendering = false
    loading.value = false
  }

  async function connect(runtimeId: string, requestGeneration: number) {
    if (generation !== requestGeneration || monitoredRuntimeId !== runtimeId) return
    loading.value = true
    try {
      const next = await apiRequest<RuntimePreviewSnapshot>(`/workflows/app-runtimes/${encodeURIComponent(runtimeId)}/preview-snapshot`)
      if (generation !== requestGeneration || monitoredRuntimeId !== runtimeId) return
      if (snapshot.value && !matchesRuntimeWorker(snapshot.value, next)) clearDisplay()
      snapshot.value = next
      error.value = ''
      if (next.observed_state !== 'running' || !next.active || !next.worker_instance_id) {
        status.value = 'stopped'
        scheduleReconnect(runtimeId, requestGeneration)
        return
      }
      if (!session.websocketQueryTokenEnabled || !session.accessToken) {
        status.value = 'authUnavailable'
        return
      }
      const url = new URL(`${getRuntimeConfig().wsBaseUrl.replace(/\/$/, '')}/workflows/app-runtimes/preview`)
      for (const key of ['workflow_runtime_id', 'workflow_runtime_revision_id', 'runtime_generation', 'worker_instance_id'] as const) {
        url.searchParams.set(key, String(next[key]))
      }
      url.searchParams.set('access_token', session.accessToken)
      const activeSocket = new WebSocket(url)
      socket = activeSocket
      status.value = 'connecting'
      activeSocket.onmessage = async (event: MessageEvent<string>) => {
        if (generation !== requestGeneration || socket !== activeSocket || rendering) return
        let receivedDisplay = false
        try {
          const frame = JSON.parse(event.data) as RuntimePreviewFrame
          if (frame.state === 'connected') {
            status.value = 'waiting'
            return
          }
          if (!matchesRuntimePreview(next, frame, sequence)) return
          receivedDisplay = true
          const nodes = new Map(next.template.nodes.map((node) => [node.node_id, node.node_type_id]))
          if (frame.displays.some((item) => nodes.get(item.node_id) !== item.node_type_id)) return
          rendering = true
          sequence = frame.sequence
          const { displays: items, ...summary } = frame
          lastRun.value = summary
          invocations.value = Object.fromEntries(items.map((item) => [item.node_id, item.invocation_id]))
          await displays.refreshDisplayOutputs({ project_id: next.project_id, readonly: true }, items.map((item) => ({
            nodeId: item.node_id, nodeTypeId: item.node_type_id, outputName: item.output_port, payload: item.payload,
          })), { keyByOutput: true })
          if (generation === requestGeneration && socket === activeSocket) {
            status.value = 'live'
            error.value = frame.error_message || frame.display_error || ''
          }
        } catch (cause) {
          if (generation === requestGeneration && socket === activeSocket) error.value = String(cause)
        } finally {
          if (generation === requestGeneration && socket === activeSocket) {
            rendering = false
            if (receivedDisplay && activeSocket.readyState === WebSocket.OPEN) activeSocket.send('ready')
          }
        }
      }
      activeSocket.onclose = () => {
        if (generation !== requestGeneration || socket !== activeSocket) return
        socket = null
        generation += 1
        const reconnectGeneration = generation
        displays.cancelPendingDisplayRefresh()
        rendering = false
        status.value = 'disconnected'
        scheduleReconnect(runtimeId, reconnectGeneration)
      }
      activeSocket.onerror = () => {
        if (generation === requestGeneration && socket === activeSocket) status.value = 'disconnected'
      }
    } catch (cause) {
      if (generation === requestGeneration && monitoredRuntimeId === runtimeId) {
        error.value = String(cause)
        status.value = 'disconnected'
        if (shouldRetrySnapshot(cause)) scheduleReconnect(runtimeId, requestGeneration)
      }
    } finally {
      if (generation === requestGeneration) loading.value = false
    }
  }

  async function load(runtimeId: string) {
    close()
    const normalizedRuntimeId = runtimeId.trim()
    snapshot.value = null
    error.value = ''
    if (!normalizedRuntimeId) return
    monitoredRuntimeId = normalizedRuntimeId
    await connect(normalizedRuntimeId, generation)
  }

  onBeforeUnmount(close)
  return { snapshot, status, error, loading, lastRun, invocations, displays, load, close }
}
