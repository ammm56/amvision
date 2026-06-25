import { computed, type ComputedRef, type Ref } from 'vue'

import type { FlowApplicationBinding, WorkflowJsonObject, WorkflowPreviewRun } from '../types'

export interface WorkflowPreviewValidationOptions {
  lastPreviewRun: Ref<WorkflowPreviewRun | null>
  previewInputBindings: ComputedRef<FlowApplicationBinding[]>
  previewAlternativeImageBindingIds: ComputedRef<string[]>
  hasPreviewBindingValue: (binding: FlowApplicationBinding) => boolean
}

function formatWorkflowJson(value: unknown): string {
  if (value === undefined) return ''
  return JSON.stringify(value, null, 2)
}

function isWorkflowJsonObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readDisplayText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function readDisplayNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isGenericPreviewRunFailureMessage(message: string): boolean {
  return ['workflow 节点执行失败', 'Preview run failed', 'Preview run 失败'].includes(message)
}

export function formatPreviewRunStatusLabel(state: WorkflowPreviewRun['state']): string {
  return `Preview ${state}`
}

export function readPreviewRunBadgeTone(state: WorkflowPreviewRun['state']): 'info' | 'danger' | 'neutral' {
  if (state === 'failed' || state === 'timed_out' || state === 'cancelled') return 'danger'
  if (state === 'succeeded') return 'info'
  return 'neutral'
}

export function readPreviewRunFailureDetails(previewRun: WorkflowPreviewRun | null): WorkflowJsonObject | null {
  if (!previewRun) return null
  const lastError = previewRun.metadata.last_error
  if (!isWorkflowJsonObject(lastError)) return null
  const details = lastError.details
  return isWorkflowJsonObject(details) ? details : null
}

export function formatPreviewRunFailureNodeLabel(details: WorkflowJsonObject | null): string {
  const nodeId = readDisplayText(details?.node_id)
  const nodeTypeId = readDisplayText(details?.node_type_id)
  if (nodeId && nodeTypeId) return `${nodeId} / ${nodeTypeId}`
  return nodeId || nodeTypeId
}

export function formatPreviewRunFailureLocation(details: WorkflowJsonObject | null): string {
  if (!details) return ''
  const runtimeKind = readDisplayText(details.runtime_kind)
  const errorType = readDisplayText(details.error_type)
  const executionIndex = readDisplayNumber(details.execution_index)
  const sequenceIndex = readDisplayNumber(details.sequence_index)
  const parts = [
    runtimeKind,
    executionIndex === null ? '' : `execution #${executionIndex}`,
    sequenceIndex === null ? '' : `sequence #${sequenceIndex}`,
    errorType,
  ].filter(Boolean)
  return parts.join(' / ')
}

export function formatPreviewRunFailureMessage(previewRun: WorkflowPreviewRun | null): string {
  if (!previewRun) return ''
  const errorMessage = readDisplayText(previewRun.error_message)
  const detailMessage = readDisplayText(readPreviewRunFailureDetails(previewRun)?.error_message)
  const nodeLabel = formatPreviewRunFailureNodeLabel(readPreviewRunFailureDetails(previewRun))
  if (detailMessage && (!errorMessage || isGenericPreviewRunFailureMessage(errorMessage))) {
    return nodeLabel ? `${nodeLabel}：${detailMessage}` : detailMessage
  }
  if (errorMessage) {
    return nodeLabel && isGenericPreviewRunFailureMessage(errorMessage) ? `${nodeLabel}：${errorMessage}` : errorMessage
  }
  return detailMessage || 'Preview run failed'
}

export function useWorkflowPreviewValidation(options: WorkflowPreviewValidationOptions) {
  const missingRequiredPreviewBindingIds = computed(() => options.previewInputBindings.value
    .filter((binding) => binding.required && !options.hasPreviewBindingValue(binding))
    .map((binding) => binding.binding_id))

  const missingAlternativePreviewBindingGroups = computed(() => {
    if (options.previewAlternativeImageBindingIds.value.length < 2) return []
    const hasAnyImageInput = options.previewAlternativeImageBindingIds.value.some((bindingId) => {
      const binding = options.previewInputBindings.value.find((item) => item.binding_id === bindingId)
      return binding ? options.hasPreviewBindingValue(binding) : false
    })
    return hasAnyImageInput ? [] : [options.previewAlternativeImageBindingIds.value]
  })

  const previewBlockingMessages = computed(() => {
    const messages: string[] = []
    if (missingRequiredPreviewBindingIds.value.length > 0) {
      messages.push(`Preview run 需要填写：${missingRequiredPreviewBindingIds.value.join(', ')}`)
    }
    for (const group of missingAlternativePreviewBindingGroups.value) {
      messages.push(`至少填写一个图片入口：${group.join(' 或 ')}`)
    }
    return messages
  })

  const previewHelpText = computed(() => {
    const messages = [...previewBlockingMessages.value]
    if (options.previewAlternativeImageBindingIds.value.length > 1) {
      messages.push(`图片入口至少填写一个：${options.previewAlternativeImageBindingIds.value.join(' 或 ')}`)
    }
    return messages.join('；')
  })

  const lastPreviewHttpResponse = computed(() => {
    const outputs = options.lastPreviewRun.value?.outputs
    if (!isWorkflowJsonObject(outputs)) return null
    const response = outputs.http_response
    return isWorkflowJsonObject(response) ? response : null
  })
  const lastPreviewHttpStatus = computed(() => readDisplayNumber(lastPreviewHttpResponse.value?.status_code))
  const lastPreviewHttpResponseJson = computed(() => lastPreviewHttpResponse.value ? formatWorkflowJson(lastPreviewHttpResponse.value) : '')
  const lastPreviewHttpResponseBodyJson = computed(() => {
    if (!lastPreviewHttpResponse.value || !("body" in lastPreviewHttpResponse.value)) return ''
    return formatWorkflowJson(lastPreviewHttpResponse.value.body)
  })
  const lastPreviewHttpResponseBodyValue = computed(() => {
    if (!lastPreviewHttpResponse.value || !("body" in lastPreviewHttpResponse.value)) return lastPreviewHttpResponse.value
    return lastPreviewHttpResponse.value.body
  })
  const lastPreviewFailureDetails = computed(() => readPreviewRunFailureDetails(options.lastPreviewRun.value))
  const lastPreviewFailureNodeId = computed(() => readDisplayText(lastPreviewFailureDetails.value?.node_id))
  const lastPreviewFailureMessage = computed(() => formatPreviewRunFailureMessage(options.lastPreviewRun.value))
  const lastPreviewFailureDetailMessage = computed(() => readDisplayText(lastPreviewFailureDetails.value?.error_message))
  const lastPreviewFailureNodeLabel = computed(() => formatPreviewRunFailureNodeLabel(lastPreviewFailureDetails.value))
  const lastPreviewFailureLocation = computed(() => formatPreviewRunFailureLocation(lastPreviewFailureDetails.value))
  const lastPreviewFailureDetailsJson = computed(() => lastPreviewFailureDetails.value ? formatWorkflowJson(lastPreviewFailureDetails.value) : '')

  return {
    missingRequiredPreviewBindingIds,
    missingAlternativePreviewBindingGroups,
    previewBlockingMessages,
    previewHelpText,
    lastPreviewHttpResponse,
    lastPreviewHttpStatus,
    lastPreviewHttpResponseJson,
    lastPreviewHttpResponseBodyJson,
    lastPreviewHttpResponseBodyValue,
    lastPreviewFailureDetails,
    lastPreviewFailureNodeId,
    lastPreviewFailureMessage,
    lastPreviewFailureDetailMessage,
    lastPreviewFailureNodeLabel,
    lastPreviewFailureLocation,
    lastPreviewFailureDetailsJson,
  }
}
