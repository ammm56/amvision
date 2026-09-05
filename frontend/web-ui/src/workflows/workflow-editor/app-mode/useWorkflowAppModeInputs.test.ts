import { describe, expect, it } from 'vitest'

import type { WorkflowAppContractInput } from './workflow-app-mode'
import { useWorkflowAppModeInputs } from './useWorkflowAppModeInputs'

function input(bindingId: string, payloadTypeId: string): WorkflowAppContractInput {
  return {
    binding_id: bindingId,
    template_port_id: bindingId,
    payload_type_id: payloadTypeId,
    binding_kind: 'api-request',
    required: false,
    config: {},
    payload_schema: {},
    request_schema: {},
    allowed_media_types: [],
    max_inline_bytes: null,
    max_file_bytes: null,
    max_files: null,
    transports: ['inline-json', 'multipart-upload'],
    charset: 'utf-8',
  }
}

describe('useWorkflowAppModeInputs', () => {
  it('omits empty public inputs and wraps value/text payloads correctly', async () => {
    const inputs = [input('request_json', 'value.v1'), input('request_text', 'text.v1'), input('request_file', 'file-ref.v1')]
    const form = useWorkflowAppModeInputs()
    form.initialize(inputs)
    form.states.value.request_json.json = '{"station":2}'
    form.states.value.request_text.text = 'lot-1'

    await expect(form.build(inputs)).resolves.toEqual({
      inputBindings: {
        request_json: { value: { station: 2 } },
        request_text: { text: 'lot-1', media_type: 'text/plain', charset: 'utf-8' },
      },
      fileUploads: [],
    })
  })

  it('keeps image-ref multipart upload on its own binding', async () => {
    const inputs = [input('request_image_ref', 'image-ref.v1')]
    inputs[0].allowed_media_types = ['image/*']
    const form = useWorkflowAppModeInputs()
    form.initialize(inputs)
    const file = new File(['image'], 'image.bmp', { type: 'image/bmp' })
    form.states.value.request_image_ref.file = file

    const payload = await form.build(inputs)

    expect(payload.inputBindings).toEqual({})
    expect(payload.fileUploads).toEqual([{ bindingId: 'request_image_ref', file }])
  })

  it('builds image Base64 and explicit image-reference payloads without rebinding', async () => {
    const inputs = [
      input('request_image_base64', 'image-base64.v1'),
      input('request_image_ref', 'image-ref.v1'),
    ]
    inputs[1].transports = ['json-reference']
    const form = useWorkflowAppModeInputs()
    form.initialize(inputs)
    form.states.value.request_image_base64.file = new File(
      [new Uint8Array([1, 2, 3])],
      'image.png',
      { type: 'image/png' },
    )
    form.states.value.request_image_ref.imageRefTransport = 'reference'
    form.states.value.request_image_ref.json = '{"transport_kind":"storage","object_key":"inputs/image.png"}'

    await expect(form.build(inputs)).resolves.toEqual({
      inputBindings: {
        request_image_base64: { image_base64: 'AQID', media_type: 'image/png' },
        request_image_ref: { transport_kind: 'storage', object_key: 'inputs/image.png' },
      },
      fileUploads: [],
    })
  })

  it('keeps single and multiple files on their declared multipart bindings', async () => {
    const inputs = [input('request_file', 'file-ref.v1'), input('request_files', 'file-refs.v1')]
    inputs[1].max_files = 2
    const form = useWorkflowAppModeInputs()
    form.initialize(inputs)
    const single = new File(['one'], 'one.json', { type: 'application/json' })
    const first = new File(['two'], 'two.json', { type: 'application/json' })
    const second = new File(['three'], 'three.json', { type: 'application/json' })
    form.states.value.request_file.file = single
    form.states.value.request_files.files = [first, second]

    const payload = await form.build(inputs)

    expect(payload.inputBindings).toEqual({})
    expect(payload.fileUploads).toEqual([
      { bindingId: 'request_file', file: single },
      { bindingId: 'request_files', file: first },
      { bindingId: 'request_files', file: second },
    ])
  })

  it('rejects an oversized inline Base64 image before reading it', async () => {
    const inputs = [input('request_image_base64', 'image-base64.v1')]
    inputs[0].max_inline_bytes = 4
    const form = useWorkflowAppModeInputs()
    form.initialize(inputs)
    form.states.value.request_image_base64.file = new File(['1234'], 'image.bmp', { type: 'image/bmp' })

    await expect(form.build(inputs)).rejects.toThrow('Base64 数据超过大小限制')
  })
})
