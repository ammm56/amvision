import { afterEach, describe, expect, it } from 'vitest'

import { formatTaskKind } from '@/modules/tasks/task-kind'
import { defaultLocale, setI18nLocale, supportedLocaleOptions } from '@/platform/i18n'
import { taskKindMessages } from '@/platform/i18n/task-kinds'

function flattenMessages(messages: Record<string, unknown>, prefix = ''): Record<string, string> {
  return Object.fromEntries(
    Object.entries(messages).flatMap(([key, value]) => {
      const path = prefix ? `${prefix}.${key}` : key
      return typeof value === 'string'
        ? [[path, value]]
        : Object.entries(flattenMessages(value as Record<string, unknown>, path))
    }),
  )
}

afterEach(() => {
  setI18nLocale(defaultLocale)
})

describe('taskKinds i18n and formatTaskKind', () => {
  it('defines identical keys across all supported locales without English fallbacks in CJK locales', () => {
    const en = flattenMessages(taskKindMessages['en-US'])
    const expectedKeys = Object.keys(en).sort()
    for (const option of supportedLocaleOptions) {
      const current = flattenMessages(taskKindMessages[option.locale])
      expect(Object.keys(current).sort(), option.locale).toEqual(expectedKeys)
      if (option.locale !== 'en-US') {
        for (const [key, value] of Object.entries(current)) {
          expect(value.trim(), `${option.locale}:${key}`).not.toBe('')
          if (!key.startsWith('patterns.')) {
            expect(value, `${option.locale}:${key}`).not.toEqual(en[key])
          }
        }
      }
    }
  })

  it('switches task kind formatting cleanly across locales', () => {
    setI18nLocale('zh-CN')
    expect(formatTaskKind('dataset-import')).toBe('数据集导入')
    expect(formatTaskKind('yolo11-classification-training')).toBe('图像分类训练（YOLO11）')
    expect(formatTaskKind('yolox-conversion')).toBe('模型转换（YOLOX）')
    expect(formatTaskKind('classification-evaluation')).toBe('图像分类评估')

    setI18nLocale('en-US')
    expect(formatTaskKind('dataset-import')).toBe('Dataset import')
    expect(formatTaskKind('yolo11-classification-training')).toBe('YOLO11 Classification training')
    expect(formatTaskKind('yolox-conversion')).toBe('YOLOX model conversion')
    expect(formatTaskKind('classification-evaluation')).toBe('Classification evaluation')

    setI18nLocale('ja-JP')
    expect(formatTaskKind('dataset-import')).toBe('データセットインポート')
    expect(formatTaskKind('yolo11-classification-training')).toBe('画像分類学習（YOLO11）')

    setI18nLocale('ko-KR')
    expect(formatTaskKind('dataset-import')).toBe('데이터셋 가져오기')
    expect(formatTaskKind('yolo11-classification-training')).toBe('이미지 분류 학습(YOLO11)')
  })

  it('handles empty and unknown task kinds safely', () => {
    expect(formatTaskKind('')).toBe('-')
    expect(formatTaskKind(null)).toBe('-')
    expect(formatTaskKind('custom-unknown-job')).toBe('custom-unknown-job')
  })
})
