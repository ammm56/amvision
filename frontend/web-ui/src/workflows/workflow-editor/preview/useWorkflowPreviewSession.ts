import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { useSessionStore } from '@/app/stores/session.store'
import { cancelPreviewSession, createPreviewSession, PreviewSessionConnection, releasePreviewSession, submitPreviewSession, type PreviewEvent } from '../services/workflow-preview-session.service'
import { emptyPreviewState, PREVIEW_TERMINAL, reducePreviewEvent, type PreviewSessionState } from './previewSessionState'
import type { PreviewNodeDisplayRefreshOptions } from './useWorkflowPreviewDisplays'
import type { WorkflowPreviewRunActionInput } from '../actions/useWorkflowEditorActions'
import type { WorkflowPreviewRun } from '../types'

export interface PreviewSessionContext extends PreviewNodeDisplayRefreshOptions {
  projectId: string
  applicationId: string
}
export type PreviewFeedback = (run: WorkflowPreviewRun, options?: PreviewNodeDisplayRefreshOptions) => Promise<void>
export const isTerminalPreviewRun = (run: WorkflowPreviewRun) => PREVIEW_TERMINAL.has(run.state)

/** 编辑器只保存当前内存会话身份；重连恢复状态，不自动重跑业务。 */
export function useWorkflowPreviewSession() {
  const account = useSessionStore()
  const lastPreviewRun = shallowRef<WorkflowPreviewRun | null>(null)
  const previewing = ref(false)
  const previewCancelling = ref(false)
  const queryError = ref<string | null>(null)
  const displayError = ref<string | null>(null)
  const displayState = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
  let generation = 0
  let context: PreviewSessionContext | null = null
  let principalId: string | undefined
  let connection: PreviewSessionConnection | null = null
  let state: PreviewSessionState | null = null
  let feedback: PreviewFeedback | null = null
  let clearDisplays: (() => void) | undefined
  let cancelDisplayRefresh: (() => void) | undefined
  let requestedRevision: string | null = null
  let createdAt = ''
  let viewFrame: number | null = null
  let pendingDisplays = 0
  let clientStarted: number | null = null
  let clientTimings: Record<string, number> = {}
  const displayFailures = new Map<string, string>()
  const displayVersions = new Map<string, number>()
  const editorId = crypto.randomUUID()

  function storageKey(projectId: string, applicationId: string): string {
    return `amvision.preview-session.v1:${JSON.stringify([account.currentUser?.principal_id, projectId, applicationId])}`
  }
  function remember(): void {
    if (!context || !connection) return
    try { sessionStorage.setItem(storageKey(context.projectId, context.applicationId), JSON.stringify(connection.identity)) } catch { /* 存储禁用不影响当前预览。 */ }
  }
  function isCurrent(token: number): boolean {
    return generation === token && context !== null && principalId === account.currentUser?.principal_id && context.isCurrent?.() !== false
  }
  function reset(): void {
    if (viewFrame !== null) cancelAnimationFrame(viewFrame)
    viewFrame = null
    generation++
    const previous = connection
    connection = null
    previous?.close()
    if (previous) void releasePreviewSession(previous.identity.session_id).catch(() => { /* 断线宽限最终回收。 */ })
    if (context) {
      try { sessionStorage.removeItem(storageKey(context.projectId, context.applicationId)) } catch { /* 无持久化依赖。 */ }
    }
    clearDisplays?.()
    context = null
    state = null
    requestedRevision = null
    lastPreviewRun.value = null
    clientStarted = null
    clientTimings = {}
    previewing.value = previewCancelling.value = false
    queryError.value = displayError.value = null
    pendingDisplays = 0
    displayFailures.clear()
    displayVersions.clear()
    displayState.value = 'idle'
  }
  function begin(next: PreviewSessionContext): number {
    if (context && (context.projectId !== next.projectId || context.applicationId !== next.applicationId || principalId !== account.currentUser?.principal_id)) reset()
    generation++
    clientStarted = performance.now()
    clientTimings = {}
    cancelDisplayRefresh?.()
    context = next
    principalId = account.currentUser?.principal_id
    requestedRevision = crypto.randomUUID()
    previewing.value = true
    previewCancelling.value = false
    queryError.value = displayError.value = null
    pendingDisplays = 0
    displayFailures.clear()
    displayVersions.clear()
    displayState.value = 'idle'
    return generation
  }
  function view(): WorkflowPreviewRun | null {
    if (!state?.run || !context || !connection) return null
    const run = state.run
    const active = connection
    return { format_id: active.identity.format_id, session_id: state.sessionId, preview_run_id: run.run_id,
      document_revision: run.document_revision, project_id: context.projectId, application_id: context.applicationId,
      state: run.state, created_at: createdAt, timings: { ...run.timings, ...clientTimings }, delivery_state: run.delivery_state,
      outputs: run.outputs ?? {}, node_records: Object.values(state.nodes),
      error: run.error ? { code: run.error.type ?? 'preview_failed', message: run.error.message,
        details: typeof run.error.details === 'object' ? run.error.details : { node_id: run.error.node_id } } : null,
      values: Object.values(state.values), readValue: (blobId, offset, path) => active.readValue(blobId, offset, path),
      readMemoryBlob: (blobId, mediaType) => active.readBlob(blobId, mediaType) }
  }
  function refreshView(): void {
    lastPreviewRun.value = view()
    if (lastPreviewRun.value) {
      previewing.value = !isTerminalPreviewRun(lastPreviewRun.value)
      if (!previewing.value) previewCancelling.value = false
    }
  }
  async function display(payloads: Record<string, any>[], token: number, terminal = false): Promise<void> {
    const run = view()
    if (!run || !isCurrent(token)) return
    function updateStatus(): void {
      if (!isCurrent(token)) return
      const resources = connection?.resourceStatus() ?? { pending: 0, errors: [] }
      displayError.value = [...displayFailures.values(), ...resources.errors].join('; ') || null
      displayState.value = displayError.value || state?.run?.delivery_state === 'unavailable' ? 'failed'
        : pendingDisplays || resources.pending || state?.run?.delivery_state === 'pending' ? 'loading' : 'ready'
      if (state?.run?.document_revision === requestedRevision && state?.run?.delivery_state === 'ready' && displayState.value === 'ready' && clientStarted !== null && !clientTimings.client_total_ms) {
        clientTimings.client_total_ms = performance.now() - clientStarted
        refreshView()
      }
    }
    await Promise.all(payloads.map(async item => {
      const key = JSON.stringify([item.node_id, item.output_port])
      const version = (displayVersions.get(key) ?? 0) + 1
      displayVersions.set(key, version)
      if (item.error) { displayFailures.set(key, `${item.node_id}: ${item.error}`); updateStatus(); return }
      if (!item.payload) return
      pendingDisplays++
      updateStatus()
      try {
        await feedback?.({ ...run, node_records: [{ node_id: item.node_id, node_type_id: item.node_type_id,
          duration_ms: item.duration_ms, outputs: { [item.output_port]: item.payload } }] },
        { ...context!, incremental: true, isCurrent: () => isCurrent(token) && displayVersions.get(key) === version })
        if (isCurrent(token) && displayVersions.get(key) === version) displayFailures.delete(key)
      } catch (error) {
        if (isCurrent(token) && displayVersions.get(key) === version) displayFailures.set(key, error instanceof Error ? error.message : String(error))
      } finally {
        if (isCurrent(token)) pendingDisplays--
        updateStatus()
      }
    }))
    if (terminal) updateStatus()
  }
  function accept(event: PreviewEvent): void {
    if (!state || !isCurrent(generation)) return
    if (requestedRevision && event.document_revision && event.document_revision !== requestedRevision) return
    if (!reducePreviewEvent(state, event)) return
    if (event.type === 'run.started' && clientStarted !== null) clientTimings.client_run_started_ms = performance.now() - clientStarted
    if (event.type === 'node.started' && clientStarted !== null && clientTimings.client_first_node_ms === undefined) clientTimings.client_first_node_ms = performance.now() - clientStarted
    if (event.type === 'run.accepted') createdAt = new Date().toISOString()
    if (event.type === 'run.finished' && clientStarted !== null) clientTimings.client_business_ms = performance.now() - clientStarted
    if (event.type.startsWith('node.') || event.type === 'value.updated') {
      if (viewFrame === null) {
        const token = generation
        viewFrame = requestAnimationFrame(() => { viewFrame = null; if (isCurrent(token)) refreshView() })
      }
    } else refreshView()
    if (event.type === 'run.accepted' && lastPreviewRun.value) {
      const token = generation
      void Promise.resolve(feedback?.(lastPreviewRun.value, { ...context!, incremental: true, markStale: true, retainedNodeIds: event.payload.node_ids })).catch(error => {
        if (isCurrent(token)) { displayError.value = String(error); displayState.value = 'failed' }
      })
    }
    if (event.type === 'session.snapshot') void display(Object.values(state.displays), generation, Boolean(state.run && PREVIEW_TERMINAL.has(state.run.state)))
    else if (event.type.startsWith('display.')) void display([event.payload], generation)
    else if (event.type === 'run.finished' || event.type === 'run.outputs') void display([], generation, true)
  }
  async function open(identity: Awaited<ReturnType<typeof createPreviewSession>>, token: number): Promise<void> {
    if (!isCurrent(token)) { await releasePreviewSession(identity.session_id); return }
    state = emptyPreviewState(identity.session_id, identity.epoch)
    const next = new PreviewSessionConnection(identity, {
      getAccessToken: () => account.accessToken, queryTokenEnabled: () => account.websocketQueryTokenEnabled,
      onEvent: accept,
      onResources: () => { if (connection === next) void display([], generation, true) },
      onConnection: (connected, error, expired) => {
        if (connection !== next) return
        queryError.value = connected ? null : error ?? 'preview_connection_lost'
        if (expired) {
          previewing.value = false
          previewCancelling.value = false
          next.close()
          connection = null
        }
      },
    })
    connection = next
    await next.connect()
    remember()
  }
  async function execute(input: WorkflowPreviewRunActionInput, token: number): Promise<WorkflowPreviewRun | null> {
    if (!connection) await open(await createPreviewSession(input.projectId, input.application.application_id, editorId), token)
    if (!isCurrent(token) || !connection) return null
    const uploadStarted = performance.now()
    const inputIds: Record<string, string[]> = {}
    for (const upload of input.fileUploads ?? []) {
      if (!isCurrent(token)) return null
      inputIds[upload.bindingId] ??= []
      inputIds[upload.bindingId]!.push(await connection.upload(upload.file, timings => {
        if (isCurrent(token)) for (const [key, value] of Object.entries(timings)) clientTimings[key] = (clientTimings[key] ?? 0) + value
      }))
    }
    if (!isCurrent(token)) return null
    clientTimings.client_upload_ms = performance.now() - uploadStarted
    clientTimings.client_before_submit_ms = performance.now() - clientStarted!
    const submitStarted = performance.now()
    const accepted = await submitPreviewSession(connection.identity.session_id, {
      request_id: crypto.randomUUID(), document_revision: requestedRevision,
      application: input.application, template: input.template, input_bindings: input.inputBindings, input_ids: inputIds,
      execution_scope: input.executionScope?.kind === 'node' ? { kind: 'node', target_node_id: input.executionScope.targetNodeId } : { kind: 'application' },
    })
    if (!isCurrent(token)) return null
    clientTimings.client_submit_ms = performance.now() - submitStarted
    if (!state?.run || state.run.run_id !== accepted.run_id) {
      state!.run = { run_id: accepted.run_id, document_revision: requestedRevision, state: 'accepted', outputs: {}, error: null }
      createdAt = new Date().toISOString()
      refreshView()
    }
    return lastPreviewRun.value
  }
  async function restore(projectId: string, applicationId: string): Promise<void> {
    if (connection || previewing.value || !projectId || !applicationId) return
    let identity
    try { identity = JSON.parse(sessionStorage.getItem(storageKey(projectId, applicationId)) ?? 'null') } catch { return }
    if (!identity?.session_id || !identity?.epoch) return
    const token = begin({ projectId, applicationId })
    requestedRevision = null
    try { await open(identity, token) } catch (error) {
      if (isCurrent(token)) { queryError.value = String(error); previewing.value = false }
    }
  }
  async function retry(): Promise<void> { if (state) await display(Object.values(state.displays), generation) }
  async function cancel(): Promise<void> {
    if (connection && state?.run) await cancelPreviewSession(connection.identity.session_id, state.run.run_id)
  }
  function setFeedback(handler: PreviewFeedback, clear?: () => void, cancelRefresh?: () => void): void {
    feedback = handler; clearDisplays = clear; cancelDisplayRefresh = cancelRefresh
  }
  onBeforeUnmount(reset)
  return { lastPreviewRun, previewing, previewCancelling, queryError, displayError, displayState,
    begin, isCurrent, execute, restore, retry, reset, setFeedback, cancel }
}
