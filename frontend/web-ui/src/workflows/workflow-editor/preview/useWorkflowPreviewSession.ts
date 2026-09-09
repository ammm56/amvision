import { onBeforeUnmount, ref } from 'vue'
import { ApiError } from '@/shared/api/error'
import { translate } from '@/platform/i18n'
import { useSessionStore } from '@/app/stores/session.store'
import { useWorkflowResourceStream } from '../composables/useWorkflowResourceStream'
import { getWorkflowPreviewRun } from '../services/workflow-runtime.service'
import { loadPreviewDisplayResult } from './previewDisplayResults'
import type { WorkflowPreviewRun } from '../types'
import type { PreviewNodeDisplayRefreshOptions } from './useWorkflowPreviewDisplays'

export interface PreviewSessionContext extends PreviewNodeDisplayRefreshOptions {
  projectId: string
  applicationId: string
}
export type PreviewFeedback = (run: WorkflowPreviewRun, options?: PreviewNodeDisplayRefreshOptions) => Promise<void>

export function isTerminalPreviewRun(run: WorkflowPreviewRun): boolean {
  return ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(run.state)
}

/** 编辑态会话只管理控制与显示，不拥有业务执行进程。 */
export function useWorkflowPreviewSession() {
  const account = useSessionStore()
  const lastPreviewRun = ref<WorkflowPreviewRun | null>(null)
  const previewing = ref(false)
  const previewCancelling = ref(false)
  const queryError = ref<string | null>(null)
  const displayError = ref<string | null>(null)
  const displayState = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
  let generation = 0
  let context: PreviewSessionContext | null = null
  let principalId: string | undefined
  let runId = ''
  let completedKey = ''
  let pending: Promise<void> | null = null
  let feedback: PreviewFeedback | null = null
  let clearDisplays: (() => void) | undefined
  let cancelDisplayRefresh: (() => void) | undefined
  let resultController: AbortController | null = null

  function storageKey(projectId: string, applicationId: string): string {
    return account.currentUser?.principal_id
      ? `amvision.preview.v1:${JSON.stringify([account.currentUser.principal_id, projectId, applicationId])}` : ''
  }
  function remember(run: WorkflowPreviewRun, terminal = false): void {
    if (!context) return
    const key = storageKey(context.projectId, context.applicationId)
    if (!key) return
    try {
      if (terminal) sessionStorage.removeItem(key)
      else sessionStorage.setItem(key, run.preview_run_id)
    } catch { /* 浏览器存储被禁用时仍可完成当前预览。 */ }
  }
  function isCurrent(token: number): boolean {
    return token === generation && principalId === account.currentUser?.principal_id && context?.isCurrent?.() !== false
  }
  function reset(): void {
    generation++
    stream.stop()
    resultController?.abort()
    clearDisplays?.()
    context = null
    runId = ''
    completedKey = ''
    pending = null
    previewing.value = false
    previewCancelling.value = false
    lastPreviewRun.value = null
    queryError.value = null
    displayError.value = null
    displayState.value = 'idle'
  }
  function begin(next: PreviewSessionContext): number {
    generation++
    stream.stop()
    resultController?.abort()
    cancelDisplayRefresh?.()
    context = next
    principalId = account.currentUser?.principal_id
    runId = ''
    completedKey = ''
    pending = null
    previewing.value = true
    previewCancelling.value = false
    lastPreviewRun.value = null
    queryError.value = null
    displayError.value = null
    displayState.value = 'idle'
    return generation
  }
  function queryFailed(error: unknown): void {
    if (!isCurrent(generation)) return
    queryError.value = `${translate('workflowEditor.feedback.previewQueryFailed')}: ${error instanceof Error ? error.message : String(error)}`
    if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
      stream.stop()
      previewing.value = false
      previewCancelling.value = false
      if (runId) remember({ preview_run_id: runId } as WorkflowPreviewRun, true)
    }
  }
  async function acceptSnapshot(run: WorkflowPreviewRun, token = generation): Promise<void> {
    if (!isCurrent(token) || !context) return
    if ((run.project_id && run.project_id !== context.projectId)
      || (run.application_id && run.application_id !== context.applicationId)
      || (runId && run.preview_run_id !== runId)) return
    if (lastPreviewRun.value && isTerminalPreviewRun(lastPreviewRun.value) && !isTerminalPreviewRun(run)) return
    runId = run.preview_run_id
    lastPreviewRun.value = run
    queryError.value = null
    previewing.value = !isTerminalPreviewRun(run)
    remember(run)
    if (!isTerminalPreviewRun(run)) return
    previewCancelling.value = false
    const key = `${run.preview_run_id}:${run.state}:${run.finished_at ?? ''}`
    if (completedKey === key) { remember(run, true); return }
    if (pending) return pending
    const refreshOptions = { ...context, isCurrent: () => isCurrent(token) }
    displayState.value = 'loading'
    displayError.value = null
    resultController = new AbortController()
    const signal = resultController.signal
    const operation = (async () => {
      try {
        // 只在终态读取完整结果，轮询和 WebSocket 事件不反复搬运大图。
        const { run: complete, errors } = await loadPreviewDisplayResult(run, signal)
        if (!isCurrent(token) || complete.preview_run_id !== runId) return
        if (!isTerminalPreviewRun(complete)
          || (complete.project_id && complete.project_id !== context?.projectId)
          || (complete.application_id && complete.application_id !== context?.applicationId)) {
          throw new Error(translate('workflowEditor.feedback.previewResultUnavailable'))
        }
        lastPreviewRun.value = complete
        await feedback?.(complete, refreshOptions)
        if (!isCurrent(token)) return
        if (errors.length) throw new Error(errors.join('; '))
        completedKey = key
        displayState.value = 'ready'
        remember(complete, true)
      } catch (error) {
        if (!isCurrent(token)) return
        displayState.value = 'failed'
        displayError.value = `${translate('workflowEditor.feedback.previewDisplayFailed')}: ${error instanceof Error ? error.message : String(error)}`
      }
    })()
    pending = operation
    try { await operation } finally { if (pending === operation) pending = null }
  }
  const stream = useWorkflowResourceStream<WorkflowPreviewRun>({
    kind: 'preview-run', getSnapshot: (id) => getWorkflowPreviewRun(id, false),
    onSnapshot: (run) => { void acceptSnapshot(run) }, isTerminal: isTerminalPreviewRun, onError: queryFailed,
  })
  async function accepted(run: WorkflowPreviewRun, token: number): Promise<void> {
    await acceptSnapshot(run, token)
    if (isCurrent(token) && !isTerminalPreviewRun(run)) stream.start(run.preview_run_id)
  }
  async function restore(projectId: string, applicationId: string, explicitRunId?: string): Promise<void> {
    if (previewing.value || !projectId || !applicationId) return
    let id = explicitRunId ?? ''
    if (!id) {
      try { id = sessionStorage.getItem(storageKey(projectId, applicationId)) ?? '' } catch { return }
    }
    if (!id) return
    const token = begin({ projectId, applicationId })
    runId = id
    try {
      const run = await getWorkflowPreviewRun(id, false)
      if (!isCurrent(token)) return
      if (run.project_id !== projectId || run.application_id !== applicationId) { reset(); return }
      await accepted(run, token)
    } catch (error) {
      if (isCurrent(token)) {
        queryFailed(error)
        if (!(error instanceof ApiError && [401, 403, 404].includes(error.status))) stream.start(id)
      }
    }
  }
  async function retry(): Promise<void> {
    if (lastPreviewRun.value && isTerminalPreviewRun(lastPreviewRun.value)) await acceptSnapshot(lastPreviewRun.value)
    else await stream.refreshNow()
  }
  function setFeedback(handler: PreviewFeedback, clear?: () => void, cancelRefresh?: () => void): void {
    feedback = handler
    clearDisplays = clear
    cancelDisplayRefresh = cancelRefresh
  }
  onBeforeUnmount(reset)
  return { lastPreviewRun, previewing, previewCancelling, queryError, displayError, displayState,
    begin, isCurrent, accepted, restore, retry, reset, setFeedback, refreshNow: stream.refreshNow }
}
