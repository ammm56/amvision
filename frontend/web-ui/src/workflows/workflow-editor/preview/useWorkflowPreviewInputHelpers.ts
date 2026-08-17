import type { ComputedRef } from 'vue'

import { translate } from '@/platform/i18n'
import type { FlowApplicationBinding } from '../types'
import type { WorkflowPreviewInputPayload } from './useWorkflowPreviewInputs'

export interface WorkflowPreviewInputHelperOptions {
  previewInputBindings: ComputedRef<FlowApplicationBinding[]>
  previewBlockingMessages: ComputedRef<string[]>
  buildPreviewInputBindingsPayload: (bindings: FlowApplicationBinding[]) => Promise<WorkflowPreviewInputPayload>
  hasPreviewBindingValue: (binding: FlowApplicationBinding) => boolean
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowPreviewInputHelpers(options: WorkflowPreviewInputHelperOptions) {
  async function buildPreviewInputBindings(
    scopedBindings?: FlowApplicationBinding[],
  ): Promise<WorkflowPreviewInputPayload | null> {
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
    buildPreviewInputBindings,
  }
}
