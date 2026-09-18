import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import { i18n } from '@/platform/i18n'
import WorkflowAppModeConfigDialog from './WorkflowAppModeConfigDialog.vue'

const candidates = [
  { node_id: 'preview-1', output_port: 'body', title: 'Image Preview', size: 'medium' as const, node_title: 'Image Preview', output_title: 'Body' },
  { node_id: 'preview-2', output_port: 'body', title: 'Value Preview', size: 'medium' as const, node_title: 'Value Preview', output_title: 'Body' },
]

describe('WorkflowAppModeConfigDialog', () => {
  it('随图用途独立于数据面板勾选，隐藏图片只改变用途提示且取消不写入', async () => {
    const image = { ...candidates[0]!, node_type_id: 'core.io.image-preview', presentationSource: { nodeId: 'values', title: '治具检测', enabled: true } }
    const secondImage = { ...image, node_id: 'image-2', title: '结果图' }
    const values = { ...candidates[1]!, node_id: 'values', node_type_id: 'core.io.value-display', node_title: '治具检测', title: '治具检测',
      connectedImages: [{ nodeId: image.node_id, title: image.title, enabled: true }, { nodeId: secondImage.node_id, title: secondImage.title, enabled: true }] }
    const config = { format_id: 'amvision.workflow-app-mode.v1' as const, title: '', displays: [image, secondImage] }
    const before = JSON.stringify({ config, image, secondImage, values })
    const wrapper = mount(WorkflowAppModeConfigDialog, { global: { plugins: [i18n] }, props: { applicationTitle: 'Test', config, candidates: [image, secondImage, values] } })
    const rows = wrapper.findAll('.app-mode-dialog__row')
    const valueRow = rows[2]!
    expect(valueRow.text()).toContain('另加独立面板')
    expect(valueRow.findAll('.app-mode-dialog__usage')).toHaveLength(2)
    expect(valueRow.text()).toContain('随图显示')
    expect(valueRow.find('input[type="checkbox"]').element).toHaveProperty('checked', false)
    await valueRow.find('input[type="checkbox"]').setValue(true)
    await valueRow.find('input[type="checkbox"]').setValue(false)
    expect(valueRow.findAll('.app-mode-dialog__usage')).toHaveLength(2)
    await rows[0]!.find('input[type="checkbox"]').setValue(false)
    expect(valueRow.text()).toContain('已连接，图片面板未显示')
    expect(valueRow.text()).toContain('随图显示')
    await rows[1]!.find('input[type="checkbox"]').setValue(false)
    expect(valueRow.text()).toContain('未在此页面显示')
    expect(valueRow.text()).toContain('显示独立面板')
    const cancel = wrapper.findAll('button').find(button => button.text() === '取消')!
    await cancel.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('apply')).toBeUndefined()
    expect(JSON.stringify({ config, image, secondImage, values })).toBe(before)
    wrapper.unmount()
  })

  it('无关联数据面板、失效来源与语言切换均有明确显示', async () => {
    const locale = i18n.global.locale.value
    const wrapper = mount(WorkflowAppModeConfigDialog, { global: { plugins: [i18n] }, props: { applicationTitle: 'Test', config: null,
      candidates: [
        { ...candidates[0]!, node_type_id: 'core.io.image-preview', presentationSource: { nodeId: 'disabled', title: 'Disabled source', enabled: false } },
        { ...candidates[1]!, node_type_id: 'core.io.value-display', connectedImages: [] },
      ] } })
    try {
      expect(wrapper.text()).toContain('未在此页面显示')
      await wrapper.find('input[type="checkbox"]').setValue(true)
      expect(wrapper.get('footer .ui-button--primary').attributes('disabled')).toBeDefined()
      for (const language of ['en-US', 'ja-JP', 'ko-KR', 'zh-CN'] as const) {
        i18n.global.locale.value = language
        await nextTick()
        expect(wrapper.text()).toContain(i18n.global.t('workflowEditor.appMode.configTitle'))
      }
    } finally {
      i18n.global.locale.value = locale
      wrapper.unmount()
    }
  })
  it('shows the graph source without saving a second binding', async () => {
    const wrapper = mount(WorkflowAppModeConfigDialog, {
      global: { plugins: [i18n] }, props: { applicationTitle: 'Test', config: null,
        candidates: [{ ...candidates[0]!, node_type_id: 'core.io.image-preview', presentationSource: { nodeId: 'values', title: 'Statistics', enabled: true } }] },
    })
    await wrapper.find('input[type="checkbox"]').setValue(true)
    expect(wrapper.find('.app-mode-dialog__usage select').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('preview-1')
    expect(wrapper.text()).not.toContain('Body')
    await wrapper.get('.app-mode-dialog__usage button').trigger('click')
    expect(wrapper.emitted('locate')).toEqual([['values']])
    await wrapper.get('footer .ui-button--primary').trigger('click')
    const config = wrapper.emitted('apply')![0]![0] as { displays: Array<Record<string, unknown>> }
    expect(config.displays).toHaveLength(1)
    expect(config.displays[0]).not.toHaveProperty('overlay')
    expect(config.displays[0]).not.toHaveProperty('presentationSource')
    wrapper.unmount()
  })
  it('新候选项使用节点标题作为面板默认标题', () => {
    const wrapper = mount(WorkflowAppModeConfigDialog, {
      global: { plugins: [i18n] },
      props: { applicationTitle: 'Test', config: null, candidates },
    })

    const titleInputs = wrapper.findAll('.app-mode-dialog__row input[type="text"]')
    expect(titleInputs.map((input) => (input.element as HTMLInputElement).value)).toEqual(['Image Preview', 'Value Preview'])
    wrapper.unmount()
  })

  it('上下移动后按显式顺序提交显示项', async () => {
    const wrapper = mount(WorkflowAppModeConfigDialog, {
      global: { plugins: [i18n] },
      props: {
        applicationTitle: 'Test',
        candidates,
        config: {
          format_id: 'amvision.workflow-app-mode.v1',
          title: '',
          displays: candidates.map(({ node_title: _nodeTitle, output_title: _outputTitle, ...display }) => display),
        },
      },
    })

    await wrapper.findAll('.app-mode-dialog__order button')[1]?.trigger('click')
    await wrapper.get('footer .ui-button--primary').trigger('click')
    const applied = wrapper.emitted('apply')?.[0]?.[0] as { displays: Array<{ node_id: string }> }
    expect(applied.displays.map((display) => display.node_id)).toEqual(['preview-2', 'preview-1'])
    wrapper.unmount()
  })
})
