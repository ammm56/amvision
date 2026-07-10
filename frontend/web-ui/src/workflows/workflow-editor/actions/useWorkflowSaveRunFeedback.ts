import { formatPreviewRunFailureMessage, readPreviewRunFailureDetails } from '../preview/useWorkflowPreviewValidation'
import type { PreviewNodeDisplayRefreshOptions } from '../preview/useWorkflowPreviewDisplays'
import type { WorkflowAppSaveResult } from '../services/workflow-app.service'
import type { WorkflowPreviewRun } from '../types'

export interface WorkflowSaveFeedbackOptions {
  wasNewApp: boolean
}

export interface WorkflowSaveRunFeedbackOptions {
  replaceRouteWithSavedApp: (applicationId: string) => Promise<void>
  refreshSavedWorkflowApp: (applicationId: string) => Promise<void>
  resetPreviewRun: () => void
  revokePreviewImageObjectUrls: () => void
  refreshPreviewNodeDisplays: (previewRun: WorkflowPreviewRun, options?: PreviewNodeDisplayRefreshOptions) => Promise<void>
  focusGraphNode: (nodeId: string) => void
  setActionError: (message: string | null) => void
  setActionStatus: (message: string | null) => void
}

export function useWorkflowSaveRunFeedback(options: WorkflowSaveRunFeedbackOptions) {
  async function applyWorkflowSaveFeedback(result: WorkflowAppSaveResult, feedbackOptions: WorkflowSaveFeedbackOptions): Promise<void> {
    const applicationId = result.applicationDocument.application_id
    if (feedbackOptions.wasNewApp) {
      await options.replaceRouteWithSavedApp(applicationId)
    }
    await options.refreshSavedWorkflowApp(applicationId)
    options.resetPreviewRun()
    options.revokePreviewImageObjectUrls()
  }

  async function applyPreviewRunFeedback(
    previewRun: WorkflowPreviewRun,
    refreshOptions: PreviewNodeDisplayRefreshOptions = {},
  ): Promise<void> {
    await options.refreshPreviewNodeDisplays(previewRun, refreshOptions)
    if (previewRun.state === 'failed') {
      const failedNodeId = readDisplayText(readPreviewRunFailureDetails(previewRun)?.node_id)
      if (failedNodeId) {
        options.focusGraphNode(failedNodeId)
      }
      options.setActionError(formatPreviewRunFailureMessage(previewRun))
    }
    options.setActionStatus(null)
  }

  return {
    applyWorkflowSaveFeedback,
    applyPreviewRunFeedback,
  }
}

function readDisplayText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}
