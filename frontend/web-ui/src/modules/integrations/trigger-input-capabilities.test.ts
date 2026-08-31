import { describe, expect, it } from 'vitest'

import {
  HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS,
  supportsTriggerInputPayloadType,
} from './trigger-input-capabilities'

describe('trigger input capabilities', () => {
  it.each(['zeromq-topic', 'local-shared-memory'])(
    '%s only accepts image reference, JSON value and text',
    (triggerKind) => {
      for (const payloadTypeId of HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS) {
        expect(supportsTriggerInputPayloadType(triggerKind, payloadTypeId)).toBe(true)
      }
      expect(supportsTriggerInputPayloadType(triggerKind, 'image-base64.v1')).toBe(false)
      expect(supportsTriggerInputPayloadType(triggerKind, 'file-ref.v1')).toBe(false)
      expect(supportsTriggerInputPayloadType(triggerKind, 'file-refs.v1')).toBe(false)
    },
  )

  it('keeps non-high-performance protocol inputs unchanged', () => {
    expect(supportsTriggerInputPayloadType('http-api', 'file-ref.v1')).toBe(true)
    expect(supportsTriggerInputPayloadType('webhook', 'image-base64.v1')).toBe(true)
  })
})
