import type { ComputedRef } from 'vue'

import { translate } from '@/platform/i18n'
import type { FlowApplicationBinding, WorkflowJsonObject } from '../types'

export interface WorkflowPreviewInputHelperOptions {
  previewInputBindings: ComputedRef<FlowApplicationBinding[]>
  previewBlockingMessages: ComputedRef<string[]>
  getBindingPayloadTypeId: (binding: FlowApplicationBinding) => string
  buildPreviewInputBindingsPayload: (bindings: FlowApplicationBinding[]) => Promise<WorkflowJsonObject>
  hasPreviewBindingValue: (binding: FlowApplicationBinding) => boolean
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

  async function buildPreviewInputBindings(
    scopedBindings?: FlowApplicationBinding[],
  ): Promise<WorkflowJsonObject | null> {
    const bindings = scopedBindings ?? options.previewInputBindings.value
    const blockingMessages = scopedBindings
      ? (() => {
        const missingBindingIds = bindings
          .filter((binding) => binding.required && !options.hasPreviewBindingValue(binding))
          .map((binding) => binding.binding_id)
        return missingBindingIds.length > 0
          ? [translate('workflowEditor.feedback.previewRequiredBindings', {
            bindings: missingBindingIds.join(', '),
          })]
          : []
      })()
      : options.previewBlockingMessages.value
    if (blockingMessages.length > 0) {
      options.setErrorMessage(blockingMessages.join('；'))
      return null
    }
    return options.buildPreviewInputBindingsPayload(bindings)
  }

  return {
    previewBindingHelpText,
    buildPreviewInputBindings,
  }
}
