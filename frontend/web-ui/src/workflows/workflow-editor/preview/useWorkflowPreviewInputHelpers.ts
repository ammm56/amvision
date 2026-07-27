import type { ComputedRef } from 'vue'

import { translate } from '@/platform/i18n'
import type { FlowApplicationBinding, WorkflowJsonObject } from '../types'

export interface WorkflowPreviewInputHelperOptions {
  previewInputBindings: ComputedRef<FlowApplicationBinding[]>
  previewBlockingMessages: ComputedRef<string[]>
  getBindingPayloadTypeId: (binding: FlowApplicationBinding) => string
  buildPreviewInputBindingsPayload: (bindings: FlowApplicationBinding[]) => Promise<WorkflowJsonObject>
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowPreviewInputHelpers(options: WorkflowPreviewInputHelperOptions) {
  function previewBindingHelpText(binding: FlowApplicationBinding): string {
    const payloadTypeId = options.getBindingPayloadTypeId(binding) || 'unknown'
    const requiredText = binding.required
      ? translate('workflowEditor.feedback.requiredInput')
      : translate('workflowEditor.feedback.optionalInput')
    if (payloadTypeId === 'image-base64.v1') {
      return translate('workflowEditor.feedback.imageBase64InputHint', { requirement: requiredText })
    }
    if (payloadTypeId === 'image-ref.v1') {
      return translate('workflowEditor.feedback.imageRefInputHint', { requirement: requiredText })
    }
    if (payloadTypeId === 'value.v1') {
      return translate('workflowEditor.feedback.valueInputHint', { requirement: requiredText })
    }
    return `${requiredText}。payload type: ${payloadTypeId}。`
  }

  async function buildPreviewInputBindings(): Promise<WorkflowJsonObject | null> {
    if (options.previewBlockingMessages.value.length > 0) {
      options.setErrorMessage(options.previewBlockingMessages.value.join('；'))
      return null
    }
    return options.buildPreviewInputBindingsPayload(options.previewInputBindings.value)
  }

  return {
    previewBindingHelpText,
    buildPreviewInputBindings,
  }
}
