import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import { setI18nLocale } from '@/platform/i18n'
import type { FlowApplicationBinding } from '../types'
import { useWorkflowPreviewValidation } from './useWorkflowPreviewValidation'

const bindings: FlowApplicationBinding[] = [
  {
    binding_id: 'request_image_ref',
    direction: 'input',
    template_port_id: 'request_image_ref',
    binding_kind: 'api-request',
    required: false,
    config: {},
    metadata: { payload_type_id: 'image-ref.v1' },
  },
  {
    binding_id: 'request_image_base64',
    direction: 'input',
    template_port_id: 'request_image_base64',
    binding_kind: 'api-request',
    required: false,
    config: {},
    metadata: { payload_type_id: 'image-base64.v1' },
  },
]

describe('useWorkflowPreviewValidation', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it.each([
    ['zh-CN', '至少填写一个图片入口：图像 或 Base64 图像'],
    ['en-US', 'Provide at least one image input: Image or Base64 image'],
    ['ja-JP', '画像入力を少なくとも 1 つ指定してください：画像 または Base64 画像'],
    ['ko-KR', '이미지 입력을 하나 이상 제공하세요: 이미지 또는 Base64 이미지'],
  ] as const)('使用 %s 显示本地化校验输入名称', (locale, expected) => {
    setI18nLocale(locale)
    const validation = useWorkflowPreviewValidation({
      lastPreviewRun: ref(null),
      previewInputBindings: computed(() => bindings),
      previewAlternativeImageBindingIds: computed(() => bindings.map((binding) => binding.binding_id)),
      hasPreviewBindingValue: () => false,
    })

    expect(validation.previewBlockingMessages.value).toEqual([expected])
    expect(validation.previewBlockingMessages.value[0]).not.toContain('request_')
  })
})
