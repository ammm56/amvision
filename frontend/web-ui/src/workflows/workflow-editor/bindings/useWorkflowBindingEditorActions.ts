import type { Ref } from 'vue'

import type { FlowApplicationBinding, WorkflowGraphInput, WorkflowGraphOutput } from '../types'
import { normalizePublicIdentifier, type WorkflowBoundaryKind } from './useWorkflowPublicBindings'

export type WorkflowBindingEditorSelectValue = string | number | boolean | null

interface WorkflowBindingEditorContextMenu {
  bindingId?: string | null
  boundaryKind?: WorkflowBoundaryKind | null
}

export interface WorkflowBindingEditorActionsOptions {
  applicationBindingsDraft: Ref<FlowApplicationBinding[]>
  selectedBoundaryKind: Ref<WorkflowBoundaryKind | null>
  contextMenu: Ref<WorkflowBindingEditorContextMenu | null>
  nodePicker: Ref<unknown | null>
  readTemplatePortForBinding: (binding: FlowApplicationBinding) => WorkflowGraphInput | WorkflowGraphOutput | null
  renameApplicationBinding: (binding: FlowApplicationBinding, nextBindingId: string) => boolean
  setBindingDisplayName: (binding: FlowApplicationBinding, nextDisplayName: string) => void
  updateApplicationBindingRequired: (binding: FlowApplicationBinding, required: boolean) => void
  deletePublicApplicationBinding: (binding: FlowApplicationBinding) => WorkflowBoundaryKind
  resetBoundaryPosition: (boundaryKind: WorkflowBoundaryKind) => void
  selectApplicationBoundary: (boundaryKind: WorkflowBoundaryKind) => void
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowBindingEditorActions(options: WorkflowBindingEditorActionsOptions) {
  function bindingEndpointText(binding: FlowApplicationBinding): string {
    const templatePort = options.readTemplatePortForBinding(binding)
    if (!templatePort) return '未找到 template port'
    if (binding.direction === 'input' && 'target_node_id' in templatePort) return `${templatePort.target_node_id}.${templatePort.target_port}`
    if (binding.direction === 'output' && 'source_node_id' in templatePort) return `${templatePort.source_node_id}.${templatePort.source_port}`
    return binding.template_port_id
  }

  function updateBindingIdFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const oldBindingId = binding.binding_id
    const nextBindingId = normalizePublicIdentifier(target.value, oldBindingId)
    if (!options.renameApplicationBinding(binding, nextBindingId)) {
      target.value = oldBindingId
      options.setErrorMessage(`公开 id 已存在：${nextBindingId}`)
      return
    }
    target.value = binding.binding_id
    options.setStatusMessage('已更新公开 id')
    options.setErrorMessage(null)
  }

  function updateBindingDisplayNameFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const nextDisplayName = target.value.trim() || binding.binding_id
    options.setBindingDisplayName(binding, nextDisplayName)
    options.setStatusMessage('已更新显示名称')
  }

  function updateBindingKindFromValue(binding: FlowApplicationBinding, value: WorkflowBindingEditorSelectValue): void {
    const fallbackKind = binding.direction === 'input' ? 'api-request' : 'http-response'
    binding.binding_kind = selectValueToString(value).trim() || fallbackKind
    options.setStatusMessage('已更新 binding kind')
  }

  function updateBindingRequiredFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    options.updateApplicationBindingRequired(binding, target.checked)
    options.setStatusMessage('已更新输入必填状态')
  }

  function deleteApplicationBinding(binding: FlowApplicationBinding): void {
    options.selectedBoundaryKind.value = options.deletePublicApplicationBinding(binding)
    options.setStatusMessage('已删除公开接口')
    options.setErrorMessage(null)
  }

  function deleteContextApplicationBinding(): void {
    const bindingId = options.contextMenu.value?.bindingId
    if (!bindingId) return
    const binding = options.applicationBindingsDraft.value.find((item) => item.binding_id === bindingId)
    if (!binding) return
    deleteApplicationBinding(binding)
    options.contextMenu.value = null
    options.nodePicker.value = null
  }

  function resetContextBoundaryPosition(): void {
    const boundaryKind = options.contextMenu.value?.boundaryKind ?? options.selectedBoundaryKind.value
    if (!boundaryKind) return
    options.resetBoundaryPosition(boundaryKind)
    options.selectApplicationBoundary(boundaryKind)
    options.setStatusMessage('已重置边界位置')
  }

  return {
    bindingEndpointText,
    updateBindingIdFromEvent,
    updateBindingDisplayNameFromEvent,
    updateBindingKindFromValue,
    updateBindingRequiredFromEvent,
    deleteApplicationBinding,
    deleteContextApplicationBinding,
    resetContextBoundaryPosition,
  }
}

function selectValueToString(value: WorkflowBindingEditorSelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}
