import type { ComputedRef, Ref } from 'vue'

import type { WorkflowSaveActionInput, WorkflowPreviewRunActionInput } from './useWorkflowEditorActions'
import type { PreviewNodeDisplayRefreshOptions } from '../preview/useWorkflowPreviewDisplays'
import type { WorkflowPreviewInputPayload } from '../preview/useWorkflowPreviewInputs'
import type { WorkflowAppSaveResult } from '../services/workflow-app.service'
import type {
  FlowApplication,
  FlowApplicationBinding,
  WorkflowGraphTemplate,
  WorkflowPreviewRun,
} from '../types'
import type { WorkflowValidationIssue } from '../validation/useWorkflowPreflight'

export interface WorkflowPreviewRunUiOptions {
  preserveImageViewerNodeId?: string | null
  targetNodeId?: string | null
}

export interface WorkflowSaveRunOrchestrationOptions {
  workflowApp: Ref<unknown | null>
  isNewApp: ComputedRef<boolean>
  selectedProjectId: ComputedRef<string>
  readNewWorkflowAppSaveBlocker: () => string | null
  buildCurrentTemplate: () => WorkflowGraphTemplate | null
  buildCurrentApplication: (template: WorkflowGraphTemplate) => FlowApplication | null
  runWorkflowPreflight: (template: WorkflowGraphTemplate, application: FlowApplication) => WorkflowValidationIssue | null
  applyWorkflowValidationIssue: (issue: WorkflowValidationIssue) => void
  buildPreviewInputBindings: (bindings?: FlowApplicationBinding[]) => Promise<WorkflowPreviewInputPayload | null>
  saveWorkflowDocument: (input: WorkflowSaveActionInput) => Promise<WorkflowAppSaveResult | null>
  runWorkflowPreview: (input: WorkflowPreviewRunActionInput) => Promise<WorkflowPreviewRun | null>
  applyWorkflowSaveFeedback: (result: WorkflowAppSaveResult, options: { wasNewApp: boolean }) => Promise<void>
  applyPreviewRunFeedback: (previewRun: WorkflowPreviewRun, options?: PreviewNodeDisplayRefreshOptions) => Promise<void>
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

  async function runPreview(uiOptions: WorkflowPreviewRunUiOptions = {}): Promise<void> {
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
    const targetNodeId = readOptionalText(uiOptions.targetNodeId)
    const scopedInputBindings = targetNodeId
      ? collectNodeScopeInputBindings(template, application, targetNodeId)
      : undefined
    const previewInputPayload = await options.buildPreviewInputBindings(scopedInputBindings)
    if (!previewInputPayload) return
    options.clearActionMessages()
    options.clearContextMenu()
    const preserveImageViewerNodeId = readOptionalText(uiOptions.preserveImageViewerNodeId)
    if (!preserveImageViewerNodeId) {
      options.revokePreviewImageObjectUrls()
    }
    const previewRun = await options.runWorkflowPreview({
      projectId: options.selectedProjectId.value,
      template,
      application,
      inputBindings: previewInputPayload.inputBindings,
      imageUploads: previewInputPayload.imageUploads,
      executionScope: targetNodeId
        ? { kind: 'node', targetNodeId }
        : { kind: 'application' },
    })
    if (!previewRun) return
    await options.applyPreviewRunFeedback(previewRun, { reopenImageViewerNodeId: preserveImageViewerNodeId })
  }

  return {
    saveCurrentWorkflowApp,
    runPreview,
  }
}

function collectNodeScopeInputBindings(
  template: WorkflowGraphTemplate,
  application: FlowApplication,
  targetNodeId: string,
): FlowApplicationBinding[] {
  const enabledNodeIds = new Set(
    template.nodes
      .filter((node) => node.enabled !== false)
      .map((node) => node.node_id),
  )
  if (!enabledNodeIds.has(targetNodeId)) return []
  const reverseAdjacency = new Map<string, string[]>()
  for (const nodeId of enabledNodeIds) reverseAdjacency.set(nodeId, [])
  for (const edge of template.edges) {
    if (!enabledNodeIds.has(edge.source_node_id) || !enabledNodeIds.has(edge.target_node_id)) continue
    reverseAdjacency.get(edge.target_node_id)?.push(edge.source_node_id)
  }
  const scopedNodeIds = new Set([targetNodeId])
  const pendingNodeIds = [targetNodeId]
  while (pendingNodeIds.length > 0) {
    const nodeId = pendingNodeIds.shift()
    if (!nodeId) continue
    for (const sourceNodeId of reverseAdjacency.get(nodeId) ?? []) {
      if (scopedNodeIds.has(sourceNodeId)) continue
      scopedNodeIds.add(sourceNodeId)
      pendingNodeIds.push(sourceNodeId)
    }
  }
  const scopedTemplateInputIds = new Set(
    template.template_inputs
      .filter((input) => scopedNodeIds.has(input.target_node_id))
      .map((input) => input.input_id),
  )
  return application.bindings.filter(
    (binding) => binding.direction === 'input'
      && scopedTemplateInputIds.has(binding.template_port_id),
  )
}

function readOptionalText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}
