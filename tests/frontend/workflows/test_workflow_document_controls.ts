import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowDocumentFileInput from '@/workflows/workflow-editor/components/WorkflowDocumentFileInput.vue'
import WorkflowGraphContextMenu from '@/workflows/workflow-editor/components/WorkflowGraphContextMenu.vue'
import WorkflowGraphToolbar from '@/workflows/workflow-editor/components/WorkflowGraphToolbar.vue'

beforeEach(() => setI18nLocale('zh-CN'))
const global = { plugins: [i18n] }
const context = { x: 80, y: 90, worldX: 0, worldY: 0, nodeId: null, edgeId: null, port: null }
function mountMenu(extra = {}) {
  return mount(WorkflowGraphContextMenu, { global, props: {
    contextMenu: { ...context, ...extra }, menuStyle: {}, minimapVisible: true, saveDisabled: false,
    previewDisabled: false, addNodeLabel: '添加节点', saveLabel: '保存', previewLabel: '预览', previewNodeLabel: '预览节点',
  } })
}

describe('workflow document controls', () => {
  it('节点菜单第二项复制，端口菜单不插入复制', async () => {
    const wrapper = mountMenu({ nodeId: 'n' })
    expect(wrapper.findAll('button')[1]!.text()).toBe('复制Ctrl+C')
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(wrapper.emitted('copy-node')).toHaveLength(1)
    await wrapper.setProps({ documentDisabled: true })
    expect(wrapper.findAll('button')[1]!.attributes('disabled')).toBeDefined()
    await wrapper.setProps({ contextMenu: { ...context, nodeId: 'n', port: { nodeId: 'n', portName: 'value', direction: 'input' } } })
    expect(wrapper.text()).not.toContain('Ctrl+C')
    wrapper.unmount()
  })
  it('places export and import last on the blank canvas menu and emits mouse selections', async () => {
    const wrapper = mountMenu()
    const buttons = wrapper.findAll('button')
    expect(buttons.slice(0, 3).map(button => button.text())).toEqual(['添加节点', '添加说明', '预览'])
    expect(buttons[3]!.text()).toBe('粘贴Ctrl+V')
    expect(buttons[3]!.attributes('disabled')).toBeDefined()
    await wrapper.setProps({ canPasteNode: true })
    await buttons[3]!.trigger('click')
    expect(wrapper.emitted('paste-node')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('隐藏小地图')
    expect(buttons.slice(-2).map(button => button.text())).toEqual(['导出工作流', '导入工作流'])
    await buttons.at(-2)!.trigger('click')
    await buttons.at(-1)!.trigger('click')
    expect(wrapper.emitted('export-document')).toHaveLength(1)
    expect(wrapper.emitted('import-document')).toHaveLength(1)
    await wrapper.setProps({ documentDisabled: true })
    expect(buttons.at(-2)!.attributes('disabled')).toBeDefined()
    expect(buttons.at(-1)!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it.each([{ nodeId: 'node' }, { edgeId: 'edge' }, { noteId: 'note' }, { boundaryKind: 'entry' }, { bindingId: 'binding' }, { port: { nodeId: 'node', portName: 'value', direction: 'input' } }])('does not offer document replacement for an object context %j', extra => {
    const wrapper = mountMenu(extra)
    expect(wrapper.text()).not.toContain('Workflow JSON')
    wrapper.unmount()
  })
  it('opens the persistent file input and allows repeat selection without emitting on cancellation', async () => {
    const wrapper = mount(WorkflowDocumentFileInput, { global })
    const input = wrapper.get('input')
    const click = vi.spyOn(input.element, 'click')
    wrapper.vm.open()
    expect(click).toHaveBeenCalledTimes(1)
    await input.trigger('change')
    expect(wrapper.emitted('import')).toBeUndefined()
    const file = new File(['{}'], 'workflow.json', { type: 'application/json' })
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await input.trigger('change')
    expect(wrapper.emitted('import')).toEqual([[file], [file]])
    expect(input.element.value).toBe('')
    await wrapper.setProps({ disabled: true })
    wrapper.vm.open()
    expect(click).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('orders preview, save, publish together and puts history last without file or note buttons', async () => {
    const wrapper = mount(WorkflowGraphToolbar, { global, props: {
      editorTitle: '验收', titleDraft: '验收', titleEditing: false, titleSaving: false, titleEditable: false,
      runtimeState: null, statusMessage: null, loading: false, previewDisabled: false, previewing: false,
      publishDisabled: false, publishing: false, saveDisabled: false, saving: false, groupCreateMode: false, inspectorCollapsed: true,
    } })
    const buttons = wrapper.findAll('button')
    const labels = buttons.map(button => button.text().trim() || button.attributes('aria-label'))
    const statusRow = wrapper.get('.workflow-graph-toolbar__meta').element
    await wrapper.setProps({ documentState: '已保存' })
    await wrapper.setProps({ documentState: '', loading: true })
    expect(wrapper.get('.workflow-graph-toolbar__meta').element).toBe(statusRow)
    await wrapper.setProps({ loading: false })
    expect(labels).toEqual(['节点组', '刷新', '应用模式', '预览', '保存', '发布', '属性面板', '版本'])
    for (const [label, event] of [['保存', 'save'], ['发布', 'publish'], ['版本', 'history']]) {
      await buttons[labels.indexOf(label)]!.trigger('click')
      expect(wrapper.emitted(event!)).toHaveLength(1)
    }
    wrapper.unmount()
  })
})
