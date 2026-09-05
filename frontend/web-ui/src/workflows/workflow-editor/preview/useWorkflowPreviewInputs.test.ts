import { describe, expect, it, vi } from 'vitest'

import type { FlowApplicationBinding } from '../types'
import { useWorkflowPreviewInputs } from './useWorkflowPreviewInputs'

vi.mock('@/platform/i18n', () => ({
  translate: (key: string) => key,
}))

describe('workflow Preview image inputs', () => {
  it('defaults image-ref preview inputs to image upload', () => {
    const binding = buildBinding('request_image_ref', 'image-ref.v1')
    const previewInputs = useWorkflowPreviewInputs({
      getBindingPayloadTypeId: item => String(item.config.payload_type_id),
    })

    previewInputs.initializePreviewInputs([binding])

    expect(previewInputs.previewInputState.value.request_image_ref.imageRefTransportKind).toBe('upload')
  })

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

  it('edits industrial structured payloads as direct JSON without value wrapping', async () => {
    const bindings = [
      buildBinding('reference_path', 'points.v1'),
      buildBinding('reference_contours', 'contours.v1'),
      buildBinding('left_camera', 'camera-calibration.v1'),
    ]
    const previewInputs = useWorkflowPreviewInputs({
      getBindingPayloadTypeId: (binding) => String(binding.config.payload_type_id),
    })
    previewInputs.initializePreviewInputs(bindings)

    expect(previewInputs.hasPreviewBindingValue(bindings[0])).toBe(true)
    const payload = await previewInputs.buildPreviewInputBindings(bindings)

    expect(payload.inputBindings.reference_path).toMatchObject({
      coordinate_space: 'source-image-pixels',
      unit: 'pixel',
      count: 2,
    })
    expect(payload.inputBindings.reference_contours).toMatchObject({ count: 1 })
    expect(payload.inputBindings.left_camera).toMatchObject({
      camera_model: 'pinhole',
      image_size: [640, 480],
    })
    expect(payload.inputBindings.reference_path).not.toHaveProperty('value')
  })

  it.each([
    'camera-calibration.v1',
    'circles.v1',
    'contours.v1',
    'ellipses.v1',
    'lines.v1',
    'localizations.v1',
    'measurements.v1',
    'planar-transform.v1',
    'points.v1',
    'regions.v1',
    'stereo-calibration.v1',
  ])('provides an object sample for structured payload %s', async (payloadTypeId) => {
    const binding = buildBinding('structured_input', payloadTypeId)
    const previewInputs = useWorkflowPreviewInputs({
      getBindingPayloadTypeId: item => String(item.config.payload_type_id),
    })
    previewInputs.initializePreviewInputs([binding])

    const payload = await previewInputs.buildPreviewInputBindings([binding])

    expect(payload.inputBindings.structured_input).toEqual(expect.any(Object))
    expect(Array.isArray(payload.inputBindings.structured_input)).toBe(false)
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
