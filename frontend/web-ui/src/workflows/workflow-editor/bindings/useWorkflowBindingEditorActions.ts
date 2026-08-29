import type { Ref } from 'vue'

import { translate } from '@/platform/i18n'
import type { FlowApplicationBinding } from '../types'
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
  function updateBindingIdFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const oldBindingId = binding.binding_id
    const nextBindingId = normalizePublicIdentifier(target.value, oldBindingId)
    if (!options.renameApplicationBinding(binding, nextBindingId)) {
      target.value = oldBindingId
      options.setErrorMessage(translate('workflowEditor.feedback.publicIdExists', { id: nextBindingId }))
      return
    }
    target.value = binding.binding_id
    options.setStatusMessage(translate('workflowEditor.feedback.publicIdUpdated'))
    options.setErrorMessage(null)
  }

  function updateBindingDisplayNameFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const nextDisplayName = target.value.trim() || binding.binding_id
    options.setBindingDisplayName(binding, nextDisplayName)
    options.setStatusMessage(translate('workflowEditor.feedback.displayNameUpdated'))
  }

  function updateBindingKindFromValue(binding: FlowApplicationBinding, value: WorkflowBindingEditorSelectValue): void {
    const fallbackKind = binding.direction === 'input' ? 'api-request' : 'http-response'
    binding.binding_kind = selectValueToString(value).trim() || fallbackKind
    options.setStatusMessage(translate('workflowEditor.feedback.bindingKindUpdated'))
  }

  function updateBindingRequiredFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    options.updateApplicationBindingRequired(binding, target.checked)
    options.setStatusMessage(translate('workflowEditor.feedback.requiredStateUpdated'))
  }

  function updateBindingDescriptionFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLTextAreaElement) && !(target instanceof HTMLInputElement)) return
    const description = target.value.trim()
    binding.metadata = { ...binding.metadata }
    if (description) binding.metadata.description = description
    else delete binding.metadata.description
    options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
    options.setErrorMessage(null)
  }

  function updateBindingRequestSchemaFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLTextAreaElement)) return
    const source = target.value.trim()
    if (!source) {
      removeBindingConfigField(binding, 'request_schema')
      options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
      options.setErrorMessage(null)
      return
    }
    try {
      const schema = JSON.parse(source) as unknown
      if (!schema || typeof schema !== 'object' || Array.isArray(schema)) throw new Error()
      binding.config = { ...binding.config, request_schema: schema }
      target.value = JSON.stringify(schema, null, 2)
      options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
      options.setErrorMessage(null)
    } catch {
      options.setErrorMessage(translate('workflowEditor.feedback.requestSchemaInvalid'))
    }
  }

  function updateBindingMediaTypesFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const mediaTypes = target.value
      .split(',')
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean)
    if (mediaTypes.length > 0) binding.config = { ...binding.config, allowed_media_types: [...new Set(mediaTypes)] }
    else removeBindingConfigField(binding, 'allowed_media_types')
    target.value = mediaTypes.join(', ')
    options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
    options.setErrorMessage(null)
  }

  function updateBindingCharsetFromEvent(binding: FlowApplicationBinding, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const charset = target.value.trim().toLowerCase()
    if (charset) binding.config = { ...binding.config, charset }
    else removeBindingConfigField(binding, 'charset')
    target.value = charset
    options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
    options.setErrorMessage(null)
  }

  function updateBindingPositiveLimitFromEvent(
    binding: FlowApplicationBinding,
    fieldName: 'max_inline_bytes' | 'max_file_bytes' | 'max_files',
    event: Event,
  ): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const source = target.value.trim()
    if (!source) {
      removeBindingConfigField(binding, fieldName)
      options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
      options.setErrorMessage(null)
      return
    }
    const value = Number(source)
    if (!Number.isSafeInteger(value) || value <= 0) {
      options.setErrorMessage(translate('workflowEditor.feedback.bindingLimitInvalid'))
      return
    }
    binding.config = { ...binding.config, [fieldName]: value }
    target.value = String(value)
    options.setStatusMessage(translate('workflowEditor.feedback.bindingPolicyUpdated'))
    options.setErrorMessage(null)
  }

  function deleteApplicationBinding(binding: FlowApplicationBinding): void {
    options.selectedBoundaryKind.value = options.deletePublicApplicationBinding(binding)
    options.setStatusMessage(translate('workflowEditor.feedback.publicBindingDeleted'))
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
    options.setStatusMessage(translate('workflowEditor.feedback.boundaryPositionReset'))
  }

  return {
    updateBindingIdFromEvent,
    updateBindingDisplayNameFromEvent,
    updateBindingKindFromValue,
    updateBindingRequiredFromEvent,
    updateBindingDescriptionFromEvent,
    updateBindingRequestSchemaFromEvent,
    updateBindingMediaTypesFromEvent,
    updateBindingCharsetFromEvent,
    updateBindingPositiveLimitFromEvent,
    deleteApplicationBinding,
    deleteContextApplicationBinding,
    resetContextBoundaryPosition,
  }
}

function removeBindingConfigField(binding: FlowApplicationBinding, fieldName: string): void {
  const config = { ...binding.config }
  delete config[fieldName]
  binding.config = config
}

function selectValueToString(value: WorkflowBindingEditorSelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}
