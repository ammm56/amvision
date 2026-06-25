import type { Ref } from 'vue'

import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import type { FlowApplicationBinding } from '../types'

export interface WorkflowGraphPanelStateOptions {
  selectedNodeId: Ref<string | null>
  selectedBoundaryKind: Ref<WorkflowBoundaryKind | null>
  appEntryBoundaryId: string
  appResultBoundaryId: string
  selectApplicationBoundary: (kind: WorkflowBoundaryKind) => void
  setStatusMessage: (message: string) => void
}

export function useWorkflowGraphPanelState(options: WorkflowGraphPanelStateOptions) {
  function selectBoundaryBinding(kind: WorkflowBoundaryKind, binding: FlowApplicationBinding): void {
    options.selectApplicationBoundary(kind)
    options.setStatusMessage(`已选择 ${binding.binding_id}`)
  }

  function isMinimapNodeSelected(nodeId: string): boolean {
    if (options.selectedNodeId.value === nodeId) return true
    if (options.selectedBoundaryKind.value === 'entry') return nodeId === options.appEntryBoundaryId
    if (options.selectedBoundaryKind.value === 'result') return nodeId === options.appResultBoundaryId
    return false
  }

  return {
    selectBoundaryBinding,
    isMinimapNodeSelected,
  }
}
