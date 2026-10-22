import { afterEach, describe, expect, it } from 'vitest'
import { setI18nLocale } from '@/platform/i18n'
import { ApiError } from './error'

afterEach(() => setI18nLocale('zh-CN'))

describe('safe training validation errors', () => {
  it.each(['zh-CN', 'en-US', 'ja-JP', 'ko-KR'] as const)('localizes the known rule in %s', (locale) => {
    setI18nLocale(locale)
    const error = new ApiError(422, {
      code: 'request_validation_failed', message: '请求参数校验失败',
      details: { errors: [{ rule: 'yolox_epoch_schedule_invalid', reason: 'private-input-value' }] },
    })
    expect(error.message).toContain('YOLOX')
    expect(error.message).toContain('no-aug')
    expect(error.message).not.toContain('private-input-value')
    expect(error.message).not.toBe('请求参数校验失败')
  })

  it('retains the generic response for unknown rules and malformed details', () => {
    for (const details of [null, { errors: {} }, { errors: [{ rule: 'toString', reason: 'secret' }] }]) {
      expect(new ApiError(422, { code: 'request_validation_failed', message: 'validation failed', details }).message).toBe('validation failed')
    }
  })
})
