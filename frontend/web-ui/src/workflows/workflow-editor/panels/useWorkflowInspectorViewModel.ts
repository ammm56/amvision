import { computed, type ComputedRef, type Ref } from 'vue'

import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import type { WorkflowAppDocument } from '../services/workflow-app.service'
import type { FlowApplicationBinding, WorkflowGraphEdge, WorkflowPreviewRun } from '../types'

export type WorkflowInspectorDetail<NodeView> =
  | { kind: 'node'; node: NodeView }
  | { kind: 'edge'; edge: WorkflowGraphEdge }
  | { kind: 'boundary'; title: string; bindings: FlowApplicationBinding[] }
  | { kind: 'application'; applicationId: string; templateInputText: string; templateOutputText: string; previewRunText: string | null }
  | { kind: 'empty' }

export interface WorkflowInspectorViewModelOptions<NodeView> {
  workflowApp: Ref<WorkflowAppDocument | null>
  isNewApp: ComputedRef<boolean>
  selectedNode: ComputedRef<NodeView | null>
  selectedEdge: ComputedRef<WorkflowGraphEdge | null>
  selectedBoundaryKind: Ref<WorkflowBoundaryKind | null>
  selectedBoundaryTitle: ComputedRef<string>
  selectedBoundaryBindings: ComputedRef<FlowApplicationBinding[]>
  lastPreviewRun: Ref<WorkflowPreviewRun | null>
}

export function useWorkflowInspectorViewModel<NodeView>(options: WorkflowInspectorViewModelOptions<NodeView>) {
  const showNewAppDraftPanel = computed(() => Boolean(options.workflowApp.value && options.isNewApp.value))
  const showAppContractPanel = computed(() => Boolean(options.workflowApp.value))

  const inspectorDetail = computed<WorkflowInspectorDetail<NodeView>>(() => {
    if (options.selectedNode.value) {
      return { kind: 'node', node: options.selectedNode.value }
    }
    if (options.selectedEdge.value) {
      return { kind: 'edge', edge: options.selectedEdge.value }
    }
    if (options.selectedBoundaryKind.value) {
      return {
        kind: 'boundary',
        title: options.selectedBoundaryTitle.value,
        bindings: options.selectedBoundaryBindings.value,
      }
    }
    if (options.workflowApp.value) {
      return {
        kind: 'application',
        applicationId: options.workflowApp.value.applicationDocument.application_id,
        templateInputText: options.workflowApp.value.graphDocument.template_input_ids.join(', '),
        templateOutputText: options.workflowApp.value.graphDocument.template_output_ids.join(', '),
        previewRunText: options.lastPreviewRun.value
          ? `${options.lastPreviewRun.value.preview_run_id} / ${options.lastPreviewRun.value.state}`
          : null,
      }
    }
    return { kind: 'empty' }
  })

  return {
    showNewAppDraftPanel,
    showAppContractPanel,
    inspectorDetail,
  }
}
