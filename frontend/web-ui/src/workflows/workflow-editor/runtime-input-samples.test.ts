import { describe, expect, it } from 'vitest'

import { buildWorkflowRuntimeInputSample } from './runtime-input-samples'

describe('Workflow Runtime input samples', () => {
  it('builds a valid ObjectStore image-ref sample', () => {
    expect(buildWorkflowRuntimeInputSample('image-ref.v1', 'request_image_ref', 'storage')).toEqual({
      transport_kind: 'storage',
      object_key: 'workflows/inputs/sample.png',
      media_type: 'image/png',
    })
  })

  it('builds a valid absolute local-path image-ref sample', () => {
    expect(buildWorkflowRuntimeInputSample('image-ref.v1', 'request_image_ref', 'local-path')).toEqual({
      transport_kind: 'local-path',
      local_path: 'C:\\vision\\inputs\\sample.png',
      media_type: 'image/png',
    })
  })
})
