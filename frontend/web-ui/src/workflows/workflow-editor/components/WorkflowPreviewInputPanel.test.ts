import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import type { PreviewInputState } from '../preview/useWorkflowPreviewInputs'
import type { FlowApplicationBinding } from '../types'
import WorkflowPreviewInputPanel from './WorkflowPreviewInputPanel.vue'

const binding: FlowApplicationBinding = {
  binding_id: 'request_image_ref',
  direction: 'input',
  template_port_id: 'request_image_ref',
  binding_kind: 'api-request',
  required: false,
  config: {},
  metadata: { payload_type_id: 'image-ref.v1' },
}

const state: PreviewInputState = {
  payloadTypeId: 'image-ref.v1',
  valueFields: [],
  file: null,
  files: [],
  mediaType: '',
  imageRefTransportKind: 'storage',
  objectKey: '',
  localPath: '',
  imageHandle: '',
  plainValue: '',
  jsonValue: '',
  textValue: '',
}

function mountPanel(
  blockingMessages: string[] = [],
  imageRefTransportKind: PreviewInputState['imageRefTransportKind'] = 'storage',
) {
  return mount(WorkflowPreviewInputPanel, {
    global: { plugins: [i18n] },
    props: {
      bindings: [binding],
      states: {
        request_image_ref: { ...state, imageRefTransportKind },
      },
      blockingMessages,
      imageRefTransportKindOptions: [
        { label: 'ObjectStore 图片', value: 'storage' },
        { label: '本地磁盘图片', value: 'local-path' },
      ],
      getPayloadTypeId: () => 'image-ref.v1',
    },
  })
}

function mountStandardBindings() {
  const payloadTypes: Record<string, string> = {
    request_image_ref: 'image-ref.v1',
    request_image_base64: 'image-base64.v1',
    request_json: 'value.v1',
    request_text: 'text.v1',
    request_file: 'file-ref.v1',
    request_files: 'file-refs.v1',
  }
  const bindings = Object.entries(payloadTypes).map(([bindingId, payloadTypeId]) => ({
    ...binding,
    binding_id: bindingId,
    template_port_id: bindingId,
    metadata: { payload_type_id: payloadTypeId },
  }))
  return mount(WorkflowPreviewInputPanel, {
    global: { plugins: [i18n] },
    props: {
      bindings,
      states: {},
      blockingMessages: [],
      imageRefTransportKindOptions: [],
      getPayloadTypeId: (item) => String(item.metadata.payload_type_id ?? ''),
    },
  })
}

describe('WorkflowPreviewInputPanel', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it('直接显示阻断信息且不再呈现 hover 帮助图标', () => {
    const wrapper = mountPanel(['至少填写一个图片入口'])

    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('至少填写一个图片入口')
    expect(wrapper.text()).toContain('缺少输入')
  })

  it('没有阻断信息时不显示冗余就绪状态', () => {
    const wrapper = mountPanel()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('就绪')
  })

  it.each([
    ['zh-CN', '预览输入', '图像', '存储路径', '媒体类型'],
    ['en-US', 'Preview Inputs', 'Image', 'Storage path', 'Media type'],
    ['ja-JP', 'プレビュー入力', '画像', '保存先パス', 'メディアタイプ'],
    ['ko-KR', '미리보기 입력', '이미지', '저장 경로', '미디어 유형'],
  ] as const)('使用 %s 显示本地化图片引用字段', (locale, title, bindingLabel, storagePathLabel, mediaTypeLabel) => {
    setI18nLocale(locale)
    const wrapper = mountPanel()

    expect(wrapper.text()).toContain(title)
    expect(wrapper.get('.workflow-graph-preview-binding__summary').text()).toBe(bindingLabel)
    expect(wrapper.text()).toContain(storagePathLabel)
    expect(wrapper.text()).toContain(mediaTypeLabel)
    expect(wrapper.text()).not.toContain('request_image_ref')
    expect(wrapper.text()).not.toContain('object_key')
    expect(wrapper.text()).not.toContain('media_type')
    expect(wrapper.text()).not.toContain('image-ref.v1')
  })

  it('为 local-path 输入显示本地绝对路径字段', () => {
    const wrapper = mountPanel([], 'local-path')

    expect(wrapper.text()).toContain('本地绝对路径')
    expect(wrapper.get('input').attributes('placeholder')).toBe('C:\\vision\\inputs\\image.bmp')
    expect(wrapper.text()).not.toContain('存储路径')
  })

  it.each([
    ['zh-CN', ['图像', 'Base64 图像', 'JSON', '文本', '文件', '多个文件']],
    ['en-US', ['Image', 'Base64 image', 'JSON', 'Text', 'File', 'Files']],
    ['ja-JP', ['画像', 'Base64 画像', 'JSON', 'テキスト', 'ファイル', '複数ファイル']],
    ['ko-KR', ['이미지', 'Base64 이미지', 'JSON', '텍스트', '파일', '여러 파일']],
  ] as const)('使用 %s 显示六种标准输入的简洁名称', (locale, labels) => {
    setI18nLocale(locale)
    const wrapper = mountStandardBindings()

    expect(wrapper.findAll('.workflow-graph-preview-binding__summary').map((item) => item.text())).toEqual(labels)
    expect(wrapper.text()).not.toContain('request_')
  })
})
