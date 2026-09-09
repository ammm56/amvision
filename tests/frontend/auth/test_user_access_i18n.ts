import { describe, expect, it } from 'vitest'
import { userAccessMessages } from '../../../frontend/web-ui/src/platform/i18n/user-access'

function flattenMessages(messages: Record<string, unknown>, prefix = ''): Record<string, string> {
  return Object.fromEntries(Object.entries(messages).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'string' ? [[path, value]] : Object.entries(flattenMessages(value as Record<string, unknown>, path))
  }))
}

describe('权限多语言文案', () => {
  for (const locale of ['ja-JP', 'ko-KR'] as const) {
    it(`${locale} 包含全部权限文案且不回退英文`, () => {
      const source = flattenMessages(userAccessMessages['en-US'])
      const translated = flattenMessages(userAccessMessages[locale])
      expect(Object.keys(translated).sort()).toEqual(Object.keys(source).sort())
      for (const [key, value] of Object.entries(translated)) {
        expect(value, key).not.toEqual(source[key])
        expect(value, key).toMatch(locale === 'ja-JP' ? /[\u3040-\u30ff\u4e00-\u9fff]/ : /[\uac00-\ud7af]/)
      }
    })
  }
})
