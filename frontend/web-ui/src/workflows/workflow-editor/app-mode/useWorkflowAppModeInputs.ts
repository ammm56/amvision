import { ref } from 'vue'

import type { WorkflowPreviewFileUpload } from '../preview/useWorkflowPreviewInputs'
import type { WorkflowAppContractInput } from './workflow-app-mode'

export interface WorkflowAppModeInputState {
  file: File | null
  files: File[]
  text: string
  json: string
  imageRefTransport: 'upload' | 'reference'
}

export interface WorkflowAppModeInvokePayload {
  inputBindings: Record<string, unknown>
  fileUploads: WorkflowPreviewFileUpload[]
}

/** 构建 App Mode 的公开输入状态；空字段不会发送，最终约束由 Runtime 契约校验。 */
export function useWorkflowAppModeInputs() {
  const states = ref<Record<string, WorkflowAppModeInputState>>({})

  function initialize(inputs: WorkflowAppContractInput[]): void {
    states.value = Object.fromEntries(inputs.map((input) => [input.binding_id, {
      file: null,
      files: [],
      text: '',
      json: '',
      imageRefTransport: input.transports.includes('multipart-upload') ? 'upload' : 'reference',
    } satisfies WorkflowAppModeInputState]))
  }

  function hasValue(input: WorkflowAppContractInput): boolean {
    const state = states.value[input.binding_id]
    if (!state) return false
    if (input.payload_type_id === 'image-base64.v1' || input.payload_type_id === 'file-ref.v1') return state.file !== null
    if (input.payload_type_id === 'file-refs.v1') return state.files.length > 0
    if (input.payload_type_id === 'image-ref.v1' && state.imageRefTransport === 'upload') return state.file !== null
    if (input.payload_type_id === 'text.v1') return state.text.length > 0
    return state.json.trim().length > 0
  }

  async function build(inputs: WorkflowAppContractInput[]): Promise<WorkflowAppModeInvokePayload> {
    const inputBindings: Record<string, unknown> = {}
    const fileUploads: WorkflowPreviewFileUpload[] = []
    for (const input of inputs) {
      if (!hasValue(input)) continue
      const state = states.value[input.binding_id]
      if (!state) continue
      validateSelectedFiles(input, state)
      if (input.payload_type_id === 'image-base64.v1' && state.file) {
        validateImageBase64SourceSize(input, state.file)
        const payload = {
          image_base64: await readFileBase64(state.file),
          media_type: state.file.type || 'application/octet-stream',
        }
        validateInlinePayloadSize(input, payload)
        inputBindings[input.binding_id] = payload
        continue
      }
      if (input.payload_type_id === 'image-ref.v1' && state.imageRefTransport === 'upload' && state.file) {
        fileUploads.push({ bindingId: input.binding_id, file: state.file })
        continue
      }
      if (input.payload_type_id === 'file-ref.v1' && state.file) {
        fileUploads.push({ bindingId: input.binding_id, file: state.file })
        continue
      }
      if (input.payload_type_id === 'file-refs.v1') {
        fileUploads.push(...state.files.map((file) => ({ bindingId: input.binding_id, file })))
        continue
      }
      if (input.payload_type_id === 'text.v1') {
        const payload = {
          text: state.text,
          media_type: 'text/plain',
          charset: input.charset || 'utf-8',
        }
        validateInlinePayloadSize(input, payload)
        inputBindings[input.binding_id] = payload
        continue
      }
      const parsed = readJson(state.json, input.binding_id)
      const payload = input.payload_type_id === 'value.v1'
        ? { value: parsed }
        : parsed
      validateInlinePayloadSize(input, payload)
      inputBindings[input.binding_id] = payload
    }
    return { inputBindings, fileUploads }
  }

  return { states, initialize, hasValue, build }
}

function readJson(value: string, bindingId: string): unknown {
  try {
    return JSON.parse(value) as unknown
  } catch {
    throw new Error(`${bindingId}: JSON 格式错误`)
  }
}

function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'))
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const separator = result.indexOf(',')
      if (separator < 0) {
        reject(new Error('文件 Base64 读取失败'))
        return
      }
      resolve(result.slice(separator + 1))
    }
    reader.readAsDataURL(file)
  })
}

function validateSelectedFiles(input: WorkflowAppContractInput, state: WorkflowAppModeInputState): void {
  const files = input.payload_type_id === 'file-refs.v1' ? state.files : state.file ? [state.file] : []
  if (input.max_files !== null && input.max_files !== undefined && files.length > input.max_files) {
    throw new Error(`${input.binding_id}: 文件数量超过 ${input.max_files}`)
  }
  for (const file of files) {
    if (input.max_file_bytes !== null && input.max_file_bytes !== undefined && file.size > input.max_file_bytes) {
      throw new Error(`${input.binding_id}: 文件 ${file.name} 超过大小限制`)
    }
    if (input.allowed_media_types.length > 0 && file.type && !mediaTypeAllowed(input.allowed_media_types, file.type)) {
      throw new Error(`${input.binding_id}: 不支持文件类型 ${file.type}`)
    }
  }
}

function mediaTypeAllowed(allowedMediaTypes: string[], actualMediaType: string): boolean {
  const actual = actualMediaType.toLowerCase()
  return allowedMediaTypes.some((item) => {
    const allowed = item.toLowerCase()
    if (allowed === '*/*' || allowed === actual) return true
    return allowed.endsWith('/*') && actual.startsWith(allowed.slice(0, -1))
  })
}

function validateImageBase64SourceSize(input: WorkflowAppContractInput, file: File): void {
  if (input.max_inline_bytes === null || input.max_inline_bytes === undefined) return
  const estimatedBase64Bytes = Math.ceil(file.size / 3) * 4
  if (estimatedBase64Bytes > input.max_inline_bytes) {
    throw new Error(`${input.binding_id}: Base64 数据超过大小限制`)
  }
}

function validateInlinePayloadSize(input: WorkflowAppContractInput, payload: unknown): void {
  if (input.max_inline_bytes === null || input.max_inline_bytes === undefined) return
  const byteLength = new TextEncoder().encode(JSON.stringify(payload)).byteLength
  if (byteLength > input.max_inline_bytes) {
    throw new Error(`${input.binding_id}: 输入数据超过大小限制`)
  }
}
