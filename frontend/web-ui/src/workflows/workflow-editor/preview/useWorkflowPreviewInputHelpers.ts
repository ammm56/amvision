import type { ComputedRef } from 'vue'

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
    const requiredText = binding.required ? '必填输入' : '可选输入'
    if (payloadTypeId === 'image-base64.v1') return `${requiredText}。选择图片文件后会自动转换为 image-base64 payload。`
    if (payloadTypeId === 'image-ref.v1') return `${requiredText}。可填写 ObjectStore object_key，或填写运行内存 image_handle。`
    if (payloadTypeId === 'value.v1') return `${requiredText}。按字段名和值提交 value payload。`
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
