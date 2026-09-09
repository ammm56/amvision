import { ref } from 'vue'
import { translate } from '@/platform/i18n'
import { ApiError } from '@/shared/api/error'
import { validateWorkflowApplication } from '../services/workflow-application.service'
import { saveWorkflowApp, type WorkflowAppSaveResult } from '../services/workflow-app.service'
import { useWorkflowPreviewSession, isTerminalPreviewRun } from '../preview/useWorkflowPreviewSession'
import type { PreviewNodeDisplayRefreshOptions } from '../preview/useWorkflowPreviewDisplays'
import { createWorkflowPreviewRun, cancelWorkflowPreviewRun } from '../services/workflow-runtime.service'
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
  displayOptions?: PreviewNodeDisplayRefreshOptions
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
  const previewSession = useWorkflowPreviewSession()
  const { previewing, previewCancelling, lastPreviewRun } = previewSession
  const saving = ref(false)
  const errorMessage = ref<string | null>(null)
  const statusMessage = ref<string | null>(null)

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
    const generation = previewSession.begin({ projectId: input.projectId, applicationId: input.application.application_id, ...input.displayOptions })
    errorMessage.value = null
    statusMessage.value = null
    try {
      await validateWorkflowTemplate(input.template)
      await validateWorkflowApplication(input.projectId, input.application, input.template)
      if (!previewSession.isCurrent(generation)) return null
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
      if (!previewSession.isCurrent(generation)) return null
      await previewSession.accepted(previewRun, generation)
      statusMessage.value = null
      return previewRun
    } catch (error) {
      if (previewSession.isCurrent(generation)) errorMessage.value = readErrorMessage(error, translate('workflowEditor.feedback.previewRunFailed'))
      return null
    } finally {
      if (previewSession.isCurrent(generation)) {
        previewing.value = Boolean(lastPreviewRun.value && !isTerminalPreviewRun(lastPreviewRun.value))
      }
    }
  }

  async function cancelPreviewRun(): Promise<void> {
    if (!lastPreviewRun.value || ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(lastPreviewRun.value.state) || !previewing.value || previewCancelling.value) return
    const targetRunId = lastPreviewRun.value.preview_run_id
    previewCancelling.value = true
    try {
      await cancelWorkflowPreviewRun(lastPreviewRun.value.preview_run_id)
      if (lastPreviewRun.value?.preview_run_id === targetRunId) await previewSession.refreshNow()
    } catch (error) {
      if (lastPreviewRun.value?.preview_run_id === targetRunId) {
        previewCancelling.value = false
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

  return {
    saving,
    previewing,
    previewCancelling,
    cancelPreviewRun,
    restorePreviewRun: previewSession.restore,
    retryPreviewResult: previewSession.retry,
    previewQueryError: previewSession.queryError,
    previewDisplayError: previewSession.displayError,
    previewDisplayState: previewSession.displayState,
    setPreviewFeedback: previewSession.setFeedback,
    errorMessage,
    statusMessage,
    lastPreviewRun,
    saveWorkflowDocument,
    runWorkflowPreview,
    clearActionMessages,
    setActionError,
    setActionStatus,
    resetPreviewRun: previewSession.reset,
  }
}
