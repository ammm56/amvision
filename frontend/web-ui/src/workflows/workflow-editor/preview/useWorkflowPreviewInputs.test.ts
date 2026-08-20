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
    expect(payload.imageUploads).toEqual([
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
    expect(payload.imageUploads).toEqual([])
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
