import { ref } from 'vue'
import { useSessionStore } from '@/app/stores/session.store'
import { translate } from '@/platform/i18n'
import { ApiError } from '@/shared/api/error'
import { validateWorkflowApplication } from '../services/workflow-application.service'
import { saveWorkflowApp, type WorkflowAppSaveResult } from '../services/workflow-app.service'
import { useWorkflowResourceStream } from '../composables/useWorkflowResourceStream'
import { createWorkflowPreviewRun, getWorkflowPreviewRun, cancelWorkflowPreviewRun } from '../services/workflow-runtime.service'
import type { WorkflowPreviewExecutionScope } from '../services/workflow-runtime.service'
import type { WorkflowPreviewFileUpload } from '../preview/useWorkflowPreviewInputs'
import { validateWorkflowTemplate } from '../services/workflow-template.service'
import type { FlowApplication, WorkflowGraphTemplate, WorkflowJsonObject, WorkflowPreviewRun } from '../types'

export interface WorkflowSaveActionInput {
  projectId: string
  template: WorkflowGraphTemplate
  application: FlowApplication
}

export interface WorkflowPreviewRunActionInput extends WorkflowSaveActionInput {
  inputBindings: WorkflowJsonObject
  fileUploads?: WorkflowPreviewFileUpload[]
  executionScope?: WorkflowPreviewExecutionScope
}

function readErrorMessage(error: unknown, fallback: string): string {
  // 校验接口将节点、端口和绑定的失败原因放在 details.reason，不能只显示总括消息。
  if (error instanceof ApiError && error.details && typeof error.details === 'object' && 'reason' in error.details) {
    const reason = error.details.reason
    if (typeof reason === 'string' && reason.trim() && !error.message.includes(reason.trim())) {
      return `${error.message}：${reason.trim()}`
    }
  }
  return error instanceof Error ? error.message : fallback
}

function readBooleanParameter(parameters: WorkflowJsonObject, parameterName: string): boolean {
  return parameters[parameterName] === true
}

function hasDebugImagePanelNode(template: WorkflowGraphTemplate): boolean {
  return template.nodes.some(
    (node) => node.enabled !== false && readBooleanParameter(node.parameters, 'debug_image_panel_enabled'),
  )
}

function shouldRetainPreviewNodeRecords(
  template: WorkflowGraphTemplate,
  executionScope?: WorkflowPreviewExecutionScope,
): boolean {
  if (executionScope?.kind === 'node') return true
  return template.nodes.some((node) => node.enabled !== false && node.node_type_id.endsWith('-preview'))
    || hasDebugImagePanelNode(template)
}

export function useWorkflowEditorActions() {
  const session = useSessionStore()
  let previewStorageKey = ''
  function storageKey(projectId: string, applicationId: string): string {
    return session.currentUser?.principal_id
      ? `amvision.preview.v1:${JSON.stringify([session.currentUser.principal_id, projectId, applicationId])}` : ''
  }
  function rememberPreview(run: WorkflowPreviewRun): void {
    if (!previewStorageKey) return
    try {
      if (isTerminalPreviewRun(run)) sessionStorage.removeItem(previewStorageKey)
      else sessionStorage.setItem(previewStorageKey, run.preview_run_id)
    } catch { /* 禁用浏览器存储时仍允许预览和按 ID 查询。 */ }
  }
  const saving = ref(false)
  const previewing = ref(false)
  const previewCancelling = ref(false)
  let previewGeneration = 0
  const errorMessage = ref<string | null>(null)
  const statusMessage = ref<string | null>(null)
  const lastPreviewRun = ref<WorkflowPreviewRun | null>(null)
  const previewRunStream = useWorkflowResourceStream<WorkflowPreviewRun>({
    kind: 'preview-run',
    getSnapshot: getWorkflowPreviewRun,
    onSnapshot: (previewRun) => {
      lastPreviewRun.value = previewRun
      rememberPreview(previewRun)
      previewing.value = !isTerminalPreviewRun(previewRun)
      if (!previewing.value) previewCancelling.value = false
    },
    isTerminal: isTerminalPreviewRun,
  })

  async function saveWorkflowDocument(input: WorkflowSaveActionInput): Promise<WorkflowAppSaveResult | null> {
    if (saving.value) return null
    saving.value = true
    errorMessage.value = null
    statusMessage.value = null
    try {
      await validateWorkflowTemplate(input.template)
      await validateWorkflowApplication(input.projectId, input.application, input.template)
      const result = await saveWorkflowApp(input)
      statusMessage.value = translate('workflowEditor.feedback.saved')
      return result
    } catch (error) {
      errorMessage.value = readErrorMessage(error, translate('workflowEditor.feedback.saveFailed'))
      return null
    } finally {
      saving.value = false
    }
  }

  async function runWorkflowPreview(input: WorkflowPreviewRunActionInput): Promise<WorkflowPreviewRun | null> {
    if (previewing.value) {
      statusMessage.value = translate('workflowEditor.feedback.previewAlreadyRunning')
      return null
    }
    const generation = ++previewGeneration
    previewStorageKey = storageKey(input.projectId, input.application.application_id)
    previewing.value = true
    errorMessage.value = null
    statusMessage.value = null
    try {
      await validateWorkflowTemplate(input.template)
      await validateWorkflowApplication(input.projectId, input.application, input.template)
      if (generation !== previewGeneration) return null
      const previewRun = await createWorkflowPreviewRun({
        projectId: input.projectId,
        template: input.template,
        inputBindings: input.inputBindings,
        fileUploads: input.fileUploads ?? [],
        executionMetadata: {
          source: 'workflow-graph-workbench',
          debug_image_panels_enabled: hasDebugImagePanelNode(input.template),
          retain_node_records_enabled: shouldRetainPreviewNodeRecords(input.template, input.executionScope),
        },
        waitMode: 'async',
        application: input.application,
        executionScope: input.executionScope,
      })
      if (generation !== previewGeneration) return null
      lastPreviewRun.value = previewRun
      rememberPreview(previewRun)
      if (!isTerminalPreviewRun(previewRun)) {
        previewRunStream.start(previewRun.preview_run_id)
      }
      statusMessage.value = null
      return previewRun
    } catch (error) {
      if (generation === previewGeneration) errorMessage.value = readErrorMessage(error, translate('workflowEditor.feedback.previewRunFailed'))
      return null
    } finally {
      if (generation === previewGeneration) {
        previewing.value = Boolean(lastPreviewRun.value && !isTerminalPreviewRun(lastPreviewRun.value))
      }
    }
  }

  async function cancelPreviewRun(): Promise<void> {
    if (!lastPreviewRun.value || isTerminalPreviewRun(lastPreviewRun.value) || !previewing.value || previewCancelling.value) return
    const generation = previewGeneration
    previewCancelling.value = true
    try {
      await cancelWorkflowPreviewRun(lastPreviewRun.value.preview_run_id)
      if (generation === previewGeneration) await previewRunStream.refreshNow()
    } catch (error) {
      if (generation === previewGeneration) {
        previewCancelling.value = false
        errorMessage.value = readErrorMessage(error, translate('workflowEditor.feedback.previewRunFailed'))
      }
    }
  }

  async function restorePreviewRun(projectId: string, applicationId: string): Promise<void> {
    if (previewing.value || !projectId || !applicationId) return
    const key = storageKey(projectId, applicationId)
    if (!key) return
    let id: string | null
    try { id = sessionStorage.getItem(key) } catch { return }
    if (!id) return
    const generation = ++previewGeneration
    previewStorageKey = key
    try {
      const run = await getWorkflowPreviewRun(id)
      if (generation !== previewGeneration || run.project_id !== projectId || run.application_id !== applicationId) return
      lastPreviewRun.value = run
      rememberPreview(run)
      previewing.value = !isTerminalPreviewRun(run)
      if (previewing.value) previewRunStream.start(run.preview_run_id)
    } catch (error) {
      if (generation === previewGeneration) {
        if (error instanceof ApiError && [403, 404].includes(error.status)) {
          try { sessionStorage.removeItem(key) } catch { /* 存储不可用不影响页面。 */ }
        }
        errorMessage.value = readErrorMessage(error, translate('workflowEditor.feedback.previewRunFailed'))
      }
    }
  }

  function clearActionMessages(): void {
    errorMessage.value = null
    statusMessage.value = null
  }

  function setActionError(message: string | null): void {
    errorMessage.value = message
  }

  function setActionStatus(message: string | null): void {
    statusMessage.value = message
  }

  function resetPreviewRun(): void {
    previewGeneration += 1
    previewing.value = false
    previewCancelling.value = false
    previewRunStream.stop()
    lastPreviewRun.value = null
  }

  return {
    saving,
    previewing,
    previewCancelling,
    cancelPreviewRun,
    restorePreviewRun,
    errorMessage,
    statusMessage,
    lastPreviewRun,
    saveWorkflowDocument,
    runWorkflowPreview,
    clearActionMessages,
    setActionError,
    setActionStatus,
    resetPreviewRun,
  }
}

function isTerminalPreviewRun(previewRun: WorkflowPreviewRun): boolean {
  return ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(previewRun.state)
}
