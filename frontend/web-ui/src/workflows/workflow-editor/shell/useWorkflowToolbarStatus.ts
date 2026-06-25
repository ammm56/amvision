import { computed, type ComputedRef, type Ref } from 'vue'

export interface WorkflowToolbarPreviewRun {
  state: string
}

export interface WorkflowToolbarStatusOptions {
  statusMessage: Ref<string | null>
  lastPreviewRun: Ref<WorkflowToolbarPreviewRun | null>
  formatPreviewRunStatusLabel: (state: string) => string
}

export function useWorkflowToolbarStatus(options: WorkflowToolbarStatusOptions): {
  toolbarStatusMessage: ComputedRef<string | null>
} {
  const toolbarStatusMessage = computed(() => {
    const message = options.statusMessage.value?.trim()
    if (!message) return null
    if (options.lastPreviewRun.value && message === options.formatPreviewRunStatusLabel(options.lastPreviewRun.value.state)) return null
    return message
  })

  return {
    toolbarStatusMessage,
  }
}
