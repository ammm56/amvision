import { describe, expect, it } from 'vitest'

import { buildWorkflowAppRequestExamples } from './workflow-app-request-examples'

describe('Workflow App request examples', () => {
  it('uses the published v1 contract to generate JSON, multipart, and .NET examples', () => {
    const result = buildWorkflowAppRequestExamples({
      format_id: 'amvision.workflow-app-contract.v1',
      inputs: [
        { binding_id: 'request_json', payload_type_id: 'value.v1' },
        { binding_id: 'request_text', payload_type_id: 'text.v1' },
        { binding_id: 'request_image_ref', payload_type_id: 'image-ref.v1' },
        { binding_id: 'request_file', payload_type_id: 'file-ref.v1' },
        { binding_id: 'request_files', payload_type_id: 'file-refs.v1' },
      ],
    }, 'runtime-1')

    expect(result).not.toBeNull()
    expect(JSON.parse(result!.json)).toMatchObject({
      request_json: { value: {} },
      request_text: { text: 'sample text' },
      request_file: { storage_ref: 'object-store' },
    })
    expect(result!.multipartCurl).toContain("-F 'request_image_ref=@sample.png;type=image/png'")
    expect(result!.multipartCurl.match(/request_files=@/gu)).toHaveLength(2)
    expect(result!.dotnet).toContain('.AddJson("request_json"')
    expect(result!.dotnet).toContain('.AddFiles("request_files"')
  })

  it('does not guess examples for legacy or absent contracts', () => {
    expect(buildWorkflowAppRequestExamples(null, '')).toBeNull()
    expect(buildWorkflowAppRequestExamples({ format_id: 'amvision.workflow-app-contract.v1' }, '')).toBeNull()
  })
})
