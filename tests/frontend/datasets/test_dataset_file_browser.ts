import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent } from 'vue'
import DatasetFileBrowser from '../../../frontend/web-ui/src/modules/datasets/components/DatasetFileBrowser.vue'
const api = vi.hoisted(() => ({ getDatasetFiles: vi.fn(), getDatasetTextFile: vi.fn(), getDatasetFileImage: vi.fn() }))
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
afterEach(() => vi.resetAllMocks())
const folder = (path: string) => ({ name: path.split('/').pop(), path, directory: true, size: null })
function create() {
  return mount(DatasetFileBrowser, { props: { workspace: { dataset_id: 'd', dataset_version_id: 'v', version_number: 1 } as any }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { SideDrawer: true, Button: defineComponent({ template: '<button><slot /></button>' }), ResourceTable: defineComponent({ template: '<table><slot /></table>' }) } } })
}
it('目录按层级展开，返回已访问目录不重新加载，版本刷新清理缓存', async () => {
  api.getDatasetFiles.mockImplementation(async (_d, _v, path) => ({ items: path === '' ? [folder('images')] : path === 'images' ? [folder('images/train')] : [], next_cursor: null }))
  const w = create(); await flushPromises()
  await w.find('.dataset-tree-name[title="images"]').trigger('click'); await flushPromises()
  expect(w.find('.dataset-tree-name[title="images/train"]').exists()).toBe(true)
  await w.find('.dataset-tree-name[title="/"]').trigger('click'); await flushPromises()
  const count = api.getDatasetFiles.mock.calls.length
  await w.find('.dataset-tree-name[title="images"]').trigger('click'); await flushPromises()
  expect(api.getDatasetFiles).toHaveBeenCalledTimes(count)
  expect(w.find('.dataset-file-path').text()).toBe('images')
  await w.setProps({ workspace: { dataset_id: 'd', dataset_version_id: 'v2', version_number: 2 } as any }); await flushPromises()
  expect(w.find('.dataset-file-path').text()).toBe('/')
  expect(api.getDatasetFiles.mock.calls.at(-1)?.[1]).toBe('v2')
  w.unmount()
})
it('快速切换目录时，迟到的文件响应不能覆盖当前目录', async () => {
  let release: (value: any) => void = () => {}
  api.getDatasetFiles.mockImplementation(async (_d, _v, path, _after, _signal, onlyDirs) => {
    if (!path) return { items: [folder('images'), folder('indexes')], next_cursor: null }
    if (path === 'images' && !onlyDirs) return new Promise(resolve => { release = resolve })
    return { items: onlyDirs ? [] : [{ name: 'train.json', path: 'indexes/train.json', directory: false, size: 12 }], next_cursor: null }
  })
  const w = create(); await flushPromises()
  await w.find('.dataset-tree-name[title="images"]').trigger('click'); await flushPromises()
  await w.find('.dataset-tree-name[title="indexes"]').trigger('click'); await flushPromises()
  release({ items: [{ name: 'old.png', path: 'images/old.png', directory: false, size: 1 }], next_cursor: null }); await flushPromises()
  expect(w.find('.dataset-file-path').text()).toBe('indexes')
  // 文件树允许保留已经展开的其他目录，当前文件表不能被迟到响应覆盖。
  expect(w.find('tbody').text()).toContain('train.json'); expect(w.find('tbody').text()).not.toContain('old.png')
  w.unmount()
})

it('空目录与文件初始隐藏展开箭头，含文件的目录仍能展开', async () => {
  api.getDatasetFiles.mockResolvedValue({ items: [{ ...folder('manifests'), has_children: false }, { ...folder('images'), has_children: true }], next_cursor: null })
  const w = create(); await flushPromises()
  const rows = w.findAll('.dataset-tree-row')
  const leaf = rows.find(row => row.find('.dataset-tree-name').attributes('title') === 'manifests')!
  const branch = rows.find(row => row.find('.dataset-tree-name').attributes('title') === 'images')!
  expect(leaf.find('.dataset-tree-leaf').attributes('aria-hidden')).toBe('true')
  expect(leaf.find('.dataset-tree-leaf').attributes('disabled')).toBeDefined()
  expect(branch.find('.dataset-tree-leaf').exists()).toBe(false)
  expect(api.getDatasetFiles.mock.calls.every(call => call[2] === '')).toBe(true)
  w.unmount()
})

it('目录读取失败不在新路径下显示旧目录文件，重试可以恢复', async () => {
  api.getDatasetFiles.mockImplementation(async (_d, _v, path, _after, _signal, onlyDirs) => {
    if (!path) return { items: [folder('images')], next_cursor: null }
    if (onlyDirs) return { items: [], next_cursor: null }
    throw new Error('read failed')
  })
  const w = create(); await flushPromises()
  await w.find('.dataset-tree-name[title="images"]').trigger('click'); await flushPromises()
  expect(w.find('tbody').text()).toBe('')
  expect(w.text()).not.toContain('空文件夹')
  api.getDatasetFiles.mockResolvedValue({ items: [{ name: 'image.jpg', path: 'images/image.jpg', directory: false, size: 10 }], next_cursor: null })
  await w.findAll('button').find(b => b.text() === '重试')!.trigger('click'); await flushPromises()
  expect(w.find('tbody').text()).toContain('image.jpg')
  w.unmount()
})
