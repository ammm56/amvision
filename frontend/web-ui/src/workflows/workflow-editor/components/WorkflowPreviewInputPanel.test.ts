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
  mediaType: '',
  imageRefTransportKind: 'storage',
  objectKey: '',
  imageHandle: '',
  plainValue: '',
}

function mountPanel(blockingMessages: string[] = []) {
  return mount(WorkflowPreviewInputPanel, {
    global: { plugins: [i18n] },
    props: {
      bindings: [binding],
      states: { request_image_ref: state },
      blockingMessages,
      imageRefTransportKindOptions: [{ label: 'ObjectStore 图片', value: 'storage' }],
      getPayloadTypeId: () => 'image-ref.v1',
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
})
