import type { Ref } from 'vue'

import { translate } from '@/platform/i18n'
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
    options.setStatusMessage(translate('workflowEditor.feedback.selectedBinding', { id: binding.binding_id }))
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
