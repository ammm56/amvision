import { describe, expect, it, vi } from 'vitest'

import type { FlowApplicationBinding } from '../types'
import { useWorkflowPreviewInputs } from './useWorkflowPreviewInputs'

vi.mock('@/platform/i18n', () => ({
  translate: (key: string) => key,
}))

describe('workflow Preview image inputs', () => {
  it('maps an image-base64 file picker to its image-ref multipart binding', async () => {
    const bindings = [
      buildBinding('request_image_ref', 'image-ref.v1'),
      buildBinding('request_image_base64', 'image-base64.v1'),
    ]
    const previewInputs = useWorkflowPreviewInputs({
      getBindingPayloadTypeId: (binding) => String(binding.config.payload_type_id),
    })
    previewInputs.initializePreviewInputs(bindings)
    const imageFile = new File(['bmp-bytes'], 'tray.bmp', { type: 'image/bmp' })
    previewInputs.previewInputState.value.request_image_base64.file = imageFile

    const payload = await previewInputs.buildPreviewInputBindings(bindings)

    expect(payload.inputBindings).toEqual({})
    expect(payload.fileUploads).toEqual([
      { bindingId: 'request_image_ref', file: imageFile },
    ])
  })

  it('builds an explicit local-path image-ref preview input', async () => {
    const bindings = [buildBinding('request_image_ref', 'image-ref.v1')]
    const previewInputs = useWorkflowPreviewInputs({
      getBindingPayloadTypeId: (binding) => String(binding.config.payload_type_id),
    })
    previewInputs.initializePreviewInputs(bindings)
    const state = previewInputs.previewInputState.value.request_image_ref
    state.imageRefTransportKind = 'local-path'
    state.localPath = 'W:\\vision\\inputs\\tray.bmp'
    state.mediaType = 'image/bmp'

    const payload = await previewInputs.buildPreviewInputBindings(bindings)

    expect(payload.inputBindings).toEqual({
      request_image_ref: {
        transport_kind: 'local-path',
        local_path: 'W:\\vision\\inputs\\tray.bmp',
        media_type: 'image/bmp',
      },
    })
    expect(payload.fileUploads).toEqual([])
  })

  it('builds typed JSON, text, single-file, and ordered multi-file inputs', async () => {
    const bindings = [
      buildBinding('request_json', 'value.v1'),
      buildBinding('request_text', 'text.v1'),
      buildBinding('request_file', 'file-ref.v1'),
      buildBinding('request_files', 'file-refs.v1'),
    ]
    const previewInputs = useWorkflowPreviewInputs({
      getBindingPayloadTypeId: (binding) => String(binding.config.payload_type_id),
    })
    previewInputs.initializePreviewInputs(bindings)
    previewInputs.previewInputState.value.request_json.jsonValue = '{"threshold":0.7}'
    previewInputs.previewInputState.value.request_text.textValue = 'lot-001'
    const recipe = new File(['{}'], 'recipe.json', { type: 'application/json' })
    const first = new File(['a'], 'a.txt', { type: 'text/plain' })
    const second = new File(['b'], 'b.txt', { type: 'text/plain' })
    previewInputs.previewInputState.value.request_file.file = recipe
    previewInputs.previewInputState.value.request_files.files = [first, second]

    const payload = await previewInputs.buildPreviewInputBindings(bindings)

    expect(payload.inputBindings).toEqual({
      request_json: { value: { threshold: 0.7 } },
      request_text: { text: 'lot-001', media_type: 'text/plain', charset: 'utf-8' },
    })
    expect(payload.fileUploads).toEqual([
      { bindingId: 'request_file', file: recipe },
      { bindingId: 'request_files', file: first },
      { bindingId: 'request_files', file: second },
    ])
  })
})

function buildBinding(
  bindingId: string,
  payloadTypeId: string,
): FlowApplicationBinding {
  return {
    binding_id: bindingId,
    direction: 'input',
    template_port_id: bindingId,
    binding_kind: 'template-input',
    required: false,
    config: { payload_type_id: payloadTypeId },
    metadata: {},
  }
}
