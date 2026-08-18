import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { FlowApplicationBinding } from '../types'
import WorkflowAppContractPanel from './WorkflowAppContractPanel.vue'
import WorkflowNewAppDraftPanel from './WorkflowNewAppDraftPanel.vue'
import WorkflowNodeDetailPanel from './WorkflowNodeDetailPanel.vue'
import WorkflowPublicBindingEditorPanel from './WorkflowPublicBindingEditorPanel.vue'

const inputBinding: FlowApplicationBinding = {
  binding_id: 'request_image_ref',
  direction: 'input',
  template_port_id: 'request_image_ref',
  binding_kind: 'api-request',
  required: false,
  config: {},
  metadata: { payload_type_id: 'image-ref.v1' },
}

describe('workflow 属性面板文本', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it('节点摘要只显示节点名称和启用开关', () => {
    const node = {
      node: {
        node_id: 'image_ref_coalesce',
        node_type_id: 'core.logic.image-ref-coalesce',
        enabled: true,
      },
      definition: { category: 'core.logic.transform' },
    } as unknown as WorkflowGraphNodeView
    const wrapper = mount(WorkflowNodeDetailPanel, {
      global: { plugins: [i18n] },
      props: { node, readTitle: () => 'Image Ref Coalesce' },
    })

    expect(wrapper.text()).toContain('Image Ref Coalesce')
    expect(wrapper.text()).not.toContain('core.logic.image-ref-coalesce')
    expect(wrapper.text()).not.toContain('core.logic.transform')
  })

  it('应用接口摘要不显示 schema 和 binding kind', () => {
    const wrapper = mount(WorkflowAppContractPanel, {
      global: { plugins: [i18n] },
      props: { inputBindings: [inputBinding], outputBindings: [] },
    })

    expect(wrapper.text()).toContain('request_image_ref')
    expect(wrapper.text()).toContain('可选')
    expect(wrapper.text()).not.toContain('image-ref.v1')
    expect(wrapper.text()).not.toContain('api-request')
  })

  it('公开接口编辑器隐藏端点和 schema 并本地化绑定类型', () => {
    const wrapper = mount(WorkflowPublicBindingEditorPanel, {
      global: { plugins: [i18n] },
      props: {
        title: 'App Entry',
        bindings: [inputBinding],
        readDisplayName: () => 'request_image_ref',
        readKindOptions: () => [{ label: 'api-request', value: 'api-request' }],
      },
    })

    expect(wrapper.text()).toContain('绑定类型')
    expect(wrapper.text()).not.toContain('core_logic_image_ref_coalesce.primary')
    expect(wrapper.text()).not.toContain('image-ref.v1')
  })

  it('可保存时不显示首次保存说明，阻断时保留必要错误', () => {
    const draft = {
      displayName: '新建应用',
      applicationId: 'workflow-app',
      graphId: 'workflow-graph',
      graphVersion: '1.0.0',
      description: '',
    }
    const readyWrapper = mount(WorkflowNewAppDraftPanel, {
      global: { plugins: [i18n] },
      props: { draft, saveBlocker: null },
    })
    const blockedWrapper = mount(WorkflowNewAppDraftPanel, {
      global: { plugins: [i18n] },
      props: { draft, saveBlocker: '至少添加一个节点后才能首次保存。' },
    })

    expect(readyWrapper.text()).not.toContain('首次保存会创建应用和图。')
    expect(readyWrapper.find('.workflow-graph-preview-hint').exists()).toBe(false)
    expect(blockedWrapper.text()).toContain('至少添加一个节点后才能首次保存。')
  })
})
