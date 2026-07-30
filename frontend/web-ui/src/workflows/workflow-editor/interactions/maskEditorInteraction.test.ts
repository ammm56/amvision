import { describe, expect, it } from 'vitest'

import {
  buildAppliedMaskBinding,
  isAppliedMaskBinding,
} from './maskEditorInteraction'

describe('Mask Editor binding', () => {
  it('builds one atomic binding from the stored mask and source image identity', () => {
    const binding = buildAppliedMaskBinding(
      ' projects/project-1/inputs/workflow-applications/app-1/prompt-masks/node-1.png ',
      ' content_sha256:abc123 ',
    )

    expect(binding).toEqual({
      mask_object_key: 'projects/project-1/inputs/workflow-applications/app-1/prompt-masks/node-1.png',
      mask_source_identity: 'content_sha256:abc123',
    })
    expect(isAppliedMaskBinding({ ...binding }, binding!)).toBe(true)
  })

  it('rejects a partial binding', () => {
    expect(buildAppliedMaskBinding('', 'content_sha256:abc123')).toBeNull()
    expect(buildAppliedMaskBinding('projects/project-1/mask.png', '')).toBeNull()
  })

  it('detects writeback loss before a Preview is started', () => {
    const binding = buildAppliedMaskBinding(
      'projects/project-1/mask.png',
      'content_sha256:abc123',
    )!

    expect(isAppliedMaskBinding({
      mask_object_key: binding.mask_object_key,
    }, binding)).toBe(false)
  })
})
