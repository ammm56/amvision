import type { ComputedRef, Ref } from 'vue'

import type { WorkflowSaveActionInput, WorkflowPreviewRunActionInput } from './useWorkflowEditorActions'
import type { WorkflowAppSaveResult } from '../services/workflow-app.service'
import type { FlowApplication, WorkflowGraphTemplate, WorkflowJsonObject, WorkflowPreviewRun } from '../types'
import type { WorkflowValidationIssue } from '../validation/useWorkflowPreflight'

export interface WorkflowSaveRunOrchestrationOptions {
  workflowApp: Ref<unknown | null>
  isNewApp: ComputedRef<boolean>
  selectedProjectId: ComputedRef<string>
  readNewWorkflowAppSaveBlocker: () => string | null
  buildCurrentTemplate: () => WorkflowGraphTemplate | null
  buildCurrentApplication: (template: WorkflowGraphTemplate) => FlowApplication | null
  runWorkflowPreflight: (template: WorkflowGraphTemplate, application: FlowApplication) => WorkflowValidationIssue | null
  applyWorkflowValidationIssue: (issue: WorkflowValidationIssue) => void
  buildPreviewInputBindings: () => Promise<WorkflowJsonObject | null>
  saveWorkflowDocument: (input: WorkflowSaveActionInput) => Promise<WorkflowAppSaveResult | null>
  runWorkflowPreview: (input: WorkflowPreviewRunActionInput) => Promise<WorkflowPreviewRun | null>
  applyWorkflowSaveFeedback: (result: WorkflowAppSaveResult, options: { wasNewApp: boolean }) => Promise<void>
  applyPreviewRunFeedback: (previewRun: WorkflowPreviewRun) => Promise<void>
  clearActionMessages: () => void
  revokePreviewImageObjectUrls: () => void
  setActionError: (message: string | null) => void
  clearContextMenu: () => void
}

export function useWorkflowSaveRunOrchestration(options: WorkflowSaveRunOrchestrationOptions) {
  async function saveCurrentWorkflowApp(): Promise<void> {
    if (!options.workflowApp.value) return
    const saveBlocker = options.readNewWorkflowAppSaveBlocker()
    if (saveBlocker) {
      options.setActionError(saveBlocker)
      return
    }
    const template = options.buildCurrentTemplate()
    if (!template) return
    const application = options.buildCurrentApplication(template)
    if (!application) return
    const preflightIssue = options.runWorkflowPreflight(template, application)
    if (preflightIssue) {
      options.applyWorkflowValidationIssue(preflightIssue)
      return
    }
    const wasNewApp = options.isNewApp.value
    options.clearActionMessages()
    options.clearContextMenu()
    const result = await options.saveWorkflowDocument({
      projectId: options.selectedProjectId.value,
      application,
      template,
    })
    if (!result) return
    await options.applyWorkflowSaveFeedback(result, { wasNewApp })
  }

  async function runPreview(): Promise<void> {
    if (!options.workflowApp.value) return
    const previewBlocker = options.readNewWorkflowAppSaveBlocker()
    if (previewBlocker) {
      options.setActionError(previewBlocker)
      return
    }
    const template = options.buildCurrentTemplate()
    if (!template) return
    const application = options.buildCurrentApplication(template)
    if (!application) return
    const preflightIssue = options.runWorkflowPreflight(template, application)
    if (preflightIssue) {
      options.applyWorkflowValidationIssue(preflightIssue)
      return
    }
    const inputBindings = await options.buildPreviewInputBindings()
    if (!inputBindings) return
    options.clearActionMessages()
    options.clearContextMenu()
    options.revokePreviewImageObjectUrls()
    const previewRun = await options.runWorkflowPreview({
      projectId: options.selectedProjectId.value,
      template,
      application,
      inputBindings,
    })
    if (!previewRun) return
    await options.applyPreviewRunFeedback(previewRun)
  }

  return {
    saveCurrentWorkflowApp,
    runPreview,
  }
}
