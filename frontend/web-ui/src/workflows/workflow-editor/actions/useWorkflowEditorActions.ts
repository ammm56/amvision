import { ref } from 'vue'
import { validateWorkflowApplication } from '../services/workflow-application.service'
import { saveWorkflowApp, type WorkflowAppSaveResult } from '../services/workflow-app.service'
import { createWorkflowPreviewRun } from '../services/workflow-runtime.service'
import { validateWorkflowTemplate } from '../services/workflow-template.service'
import type { FlowApplication, WorkflowGraphTemplate, WorkflowJsonObject, WorkflowPreviewRun } from '../types'

export interface WorkflowSaveActionInput {
  projectId: string
  template: WorkflowGraphTemplate
  application: FlowApplication
}

export interface WorkflowPreviewRunActionInput extends WorkflowSaveActionInput {
  inputBindings: WorkflowJsonObject
}

function readErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function useWorkflowEditorActions() {
  const saving = ref(false)
  const previewing = ref(false)
  const errorMessage = ref<string | null>(null)
  const statusMessage = ref<string | null>(null)
  const lastPreviewRun = ref<WorkflowPreviewRun | null>(null)

  async function saveWorkflowDocument(input: WorkflowSaveActionInput): Promise<WorkflowAppSaveResult | null> {
    saving.value = true
    errorMessage.value = null
    statusMessage.value = null
    try {
      await validateWorkflowTemplate(input.template)
      await validateWorkflowApplication(input.projectId, input.application, input.template)
      const result = await saveWorkflowApp(input)
      statusMessage.value = '已保存'
      return result
    } catch (error) {
      errorMessage.value = readErrorMessage(error, '保存失败')
      return null
    } finally {
      saving.value = false
    }
  }

  async function runWorkflowPreview(input: WorkflowPreviewRunActionInput): Promise<WorkflowPreviewRun | null> {
    previewing.value = true
    errorMessage.value = null
    statusMessage.value = null
    try {
      await validateWorkflowTemplate(input.template)
      await validateWorkflowApplication(input.projectId, input.application, input.template)
      const previewRun = await createWorkflowPreviewRun({
        projectId: input.projectId,
        template: input.template,
        inputBindings: input.inputBindings,
        executionMetadata: { source: 'workflow-graph-workbench' },
        waitMode: 'sync',
        application: input.application,
      })
      lastPreviewRun.value = previewRun
      statusMessage.value = null
      return previewRun
    } catch (error) {
      errorMessage.value = readErrorMessage(error, 'Preview run 失败')
      return null
    } finally {
      previewing.value = false
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
    lastPreviewRun.value = null
  }

  return {
    saving,
    previewing,
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
