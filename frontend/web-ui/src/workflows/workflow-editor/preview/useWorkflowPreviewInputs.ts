import { ref } from 'vue'

import type { FlowApplicationBinding } from '../types'

export type PreviewSelectValue = string | number | boolean | null

export interface PreviewSelectOption {
  label: string
  value: PreviewSelectValue
  description?: string
}

export interface PreviewValueField {
  id: string
  key: string
  value: string
}

export interface PreviewInputState {
  payloadTypeId: string
  valueFields: PreviewValueField[]
  file: File | null
  mediaType: string
  imageRefTransportKind: 'storage' | 'memory'
  objectKey: string
  imageHandle: string
  plainValue: string
}

export const previewImageRefTransportKindOptions: PreviewSelectOption[] = [
  { label: 'ObjectStore 图片', value: 'storage' },
  { label: '运行内存 image handle', value: 'memory' },
]

interface WorkflowPreviewInputsOptions {
  getBindingPayloadTypeId: (binding: FlowApplicationBinding) => string
}

export interface InitializePreviewInputsOptions {
  preserveExisting?: boolean
}

export function useWorkflowPreviewInputs(options: WorkflowPreviewInputsOptions) {
  const previewInputState = ref<Record<string, PreviewInputState>>({})

  function hasPreviewBindingValue(binding: FlowApplicationBinding): boolean {
    const state = previewInputState.value[binding.binding_id]
    if (!state) return false
    const payloadTypeId = options.getBindingPayloadTypeId(binding)
    if (payloadTypeId === 'value.v1') {
      return state.valueFields.some((field) => field.key.trim() && field.value.trim())
    }
    if (payloadTypeId === 'image-base64.v1') return state.file !== null
    if (payloadTypeId === 'image-ref.v1') {
      if (state.imageRefTransportKind === 'storage') return Boolean(state.objectKey.trim())
      return Boolean(state.imageHandle.trim() && state.mediaType.trim())
    }
    return Boolean(state.plainValue.trim())
  }

  function createEmptyPreviewInputState(binding: FlowApplicationBinding): PreviewInputState {
    const payloadTypeId = options.getBindingPayloadTypeId(binding)
    const valueFields = readPreviewValueFields(binding)
    if (payloadTypeId === 'value.v1' && valueFields.length === 0) {
      valueFields.push({
        id: createPreviewFieldId(),
        key: binding.binding_id.includes('deployment') ? 'deployment_instance_id' : '',
        value: '',
      })
    }
    return {
      payloadTypeId,
      valueFields,
      file: null,
      mediaType: '',
      imageRefTransportKind: 'storage',
      objectKey: '',
      imageHandle: '',
      plainValue: '',
    }
  }

  function initializePreviewInputs(applicationBindings: FlowApplicationBinding[], initOptions: InitializePreviewInputsOptions = {}): void {
    const nextInputState: Record<string, PreviewInputState> = {}
    for (const binding of applicationBindings) {
      if (binding.direction !== 'input') continue
      nextInputState[binding.binding_id] = initOptions.preserveExisting
        ? reuseCompatiblePreviewInputState(binding)
        : createEmptyPreviewInputState(binding)
    }
    previewInputState.value = nextInputState
  }

  function reuseCompatiblePreviewInputState(binding: FlowApplicationBinding): PreviewInputState {
    const previousState = previewInputState.value[binding.binding_id]
    if (!previousState) return createEmptyPreviewInputState(binding)
    const payloadTypeId = options.getBindingPayloadTypeId(binding)
    if (previousState.payloadTypeId === payloadTypeId) return previousState
    return createEmptyPreviewInputState(binding)
  }

  function setPreviewInputStateForBinding(binding: FlowApplicationBinding): void {
    previewInputState.value = {
      ...previewInputState.value,
      [binding.binding_id]: createEmptyPreviewInputState(binding),
    }
  }

  function renamePreviewInputState(oldBindingId: string, nextBindingId: string, binding: FlowApplicationBinding): void {
    const previousState = previewInputState.value[oldBindingId]
    const nextState = { ...previewInputState.value }
    delete nextState[oldBindingId]
    nextState[nextBindingId] = previousState ?? createEmptyPreviewInputState(binding)
    previewInputState.value = nextState
  }

  function removePreviewInputState(bindingId: string): void {
    removePreviewInputStates([bindingId])
  }

  function removePreviewInputStates(bindingIds: Iterable<string>): void {
    const nextState = { ...previewInputState.value }
    for (const bindingId of bindingIds) {
      delete nextState[bindingId]
    }
    previewInputState.value = nextState
  }

  function addPreviewValueField(bindingId: string): void {
    const state = previewInputState.value[bindingId]
    if (!state) return
    state.valueFields.push({ id: createPreviewFieldId(), key: '', value: '' })
  }

  function removePreviewValueField(bindingId: string, fieldId: string): void {
    const state = previewInputState.value[bindingId]
    if (!state) return
    state.valueFields = state.valueFields.filter((field) => field.id !== fieldId)
    if (state.valueFields.length === 0) addPreviewValueField(bindingId)
  }

  function setPreviewImageRefTransportKind(bindingId: string, value: PreviewSelectValue): void {
    const state = previewInputState.value[bindingId]
    if (!state) return
    state.imageRefTransportKind = selectValueToString(value) === 'memory' ? 'memory' : 'storage'
  }

  async function buildPreviewInputBindings(bindings: FlowApplicationBinding[]): Promise<Record<string, unknown>> {
    const inputBindings: Record<string, unknown> = {}
    for (const binding of bindings) {
      if (!hasPreviewBindingValue(binding)) continue
      inputBindings[binding.binding_id] = await buildPreviewPayload(binding)
    }
    return inputBindings
  }

  async function buildPreviewPayload(binding: FlowApplicationBinding): Promise<unknown> {
    const state = previewInputState.value[binding.binding_id]
    const payloadTypeId = options.getBindingPayloadTypeId(binding)
    if (!state) return null
    if (payloadTypeId === 'value.v1') return buildValuePreviewPayload(state)
    if (payloadTypeId === 'image-base64.v1') return buildImageBase64PreviewPayload(state)
    if (payloadTypeId === 'image-ref.v1') return buildImageRefPreviewPayload(state)
    return { value: parsePreviewScalarValue(state.plainValue) }
  }

  return {
    previewInputState,
    hasPreviewBindingValue,
    createEmptyPreviewInputState,
    initializePreviewInputs,
    setPreviewInputStateForBinding,
    renamePreviewInputState,
    removePreviewInputState,
    removePreviewInputStates,
    addPreviewValueField,
    removePreviewValueField,
    setPreviewImageRefTransportKind,
    buildPreviewInputBindings,
  }
}

function readPreviewValueFields(binding: FlowApplicationBinding): PreviewValueField[] {
  const rawValue = binding.config.default_value ?? binding.config.example_value ?? binding.metadata.default_value ?? binding.metadata.example_value
  const valueObject = normalizePreviewValueObject(rawValue)
  return Object.entries(valueObject).map(([key, value]) => ({ id: createPreviewFieldId(), key, value: String(value ?? '') }))
}

function normalizePreviewValueObject(rawValue: unknown): Record<string, unknown> {
  if (!rawValue || typeof rawValue !== 'object' || Array.isArray(rawValue)) return {}
  const rawRecord = rawValue as Record<string, unknown>
  const nestedValue = rawRecord.value
  if (nestedValue && typeof nestedValue === 'object' && !Array.isArray(nestedValue)) return nestedValue as Record<string, unknown>
  return rawRecord
}

function buildValuePreviewPayload(state: PreviewInputState): Record<string, unknown> {
  const value: Record<string, unknown> = {}
  for (const field of state.valueFields) {
    const key = field.key.trim()
    if (!key) continue
    value[key] = parsePreviewScalarValue(field.value)
  }
  return { value }
}

async function buildImageBase64PreviewPayload(state: PreviewInputState): Promise<Record<string, unknown>> {
  if (!state.file) return {}
  const imageBase64 = await readFileAsBase64(state.file)
  return {
    image_base64: imageBase64,
    media_type: state.mediaType.trim() || state.file.type || 'application/octet-stream',
  }
}

function buildImageRefPreviewPayload(state: PreviewInputState): Record<string, unknown> {
  if (state.imageRefTransportKind === 'memory') {
    return {
      transport_kind: 'memory',
      image_handle: state.imageHandle.trim(),
      media_type: state.mediaType.trim(),
    }
  }
  const payload: Record<string, unknown> = {
    transport_kind: 'storage',
    object_key: state.objectKey.trim(),
  }
  if (state.mediaType.trim()) payload.media_type = state.mediaType.trim()
  return payload
}

function parsePreviewScalarValue(value: string): unknown {
  const trimmedValue = value.trim()
  if (trimmedValue === 'true') return true
  if (trimmedValue === 'false') return false
  if (trimmedValue === 'null') return null
  if (trimmedValue !== '' && !Number.isNaN(Number(trimmedValue))) return Number(trimmedValue)
  return value
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const commaIndex = result.indexOf(',')
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('读取图片文件失败'))
    reader.readAsDataURL(file)
  })
}

function createPreviewFieldId(): string {
  return `preview-field-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function selectValueToString(value: PreviewSelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}
