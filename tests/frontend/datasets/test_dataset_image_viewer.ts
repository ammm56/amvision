import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetImageViewer from '../../../frontend/web-ui/src/modules/datasets/components/DatasetImageViewer.vue'
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('大图复用缩放状态，标注开关不重置缩放；上一张边界禁止调用，对象信息通过抽屉事件打开', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 800, height: 600, left: 0, top: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON() {} })
  const w = mount(DatasetImageViewer, {
    props: { open: true, image: { id: 'sample-1', title: 'a.jpg', src: 'blob:raw', width: 1000, height: 800 }, datasetName: '数据集', version: 'v1', split: 'train', objectCount: 2, annotations: true, busy: false, hasPrevious: false, hasNext: true, invalid: 0 },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { SelectField: { props: ['modelValue'], template: '<span data-zoom>{{modelValue}}</span>' } } },
  })
  await flushPromises()
  await w.get('img').trigger('load')
  await w.get('button[aria-label="放大"]').trigger('click')
  const scale = w.get('[data-zoom]').text()
  await w.setProps({ annotations: false, image: { id: 'sample-1', title: 'a.jpg', src: 'blob:other', width: 1000, height: 800 } })
  await flushPromises()
  await w.get('img').trigger('load')
  expect(scale).toBe('94')
  expect(w.get('[data-zoom]').text()).toBe(scale)
  await w.findAll('button').find(b => b.text() === '上一张')!.trigger('click')
  expect(w.emitted('previous')).toBeUndefined()
  await w.findAll('button').find(b => b.text() === '对象信息')!.trigger('click')
  expect(w.emitted('info')).toHaveLength(1)
  const originalTransform = w.get('.dataset-image-frame').attributes('style')
  await w.setProps({ infoOpen: true, focusedBounds: [700, 600, 100, 100] })
  expect(w.get('[data-zoom]').text()).toBe(scale)
  await w.get('.dataset-image-canvas').trigger('keydown', { key: 'Escape' })
  expect(w.emitted('close-info')).toHaveLength(1)
  expect(w.emitted('close')).toBeUndefined()
  expect(w.get('.dataset-image-frame').attributes('style')).not.toBe(originalTransform)
  await w.setProps({ infoOpen: false })
  expect(w.get('.dataset-image-frame').attributes('style')).toBe(originalTransform)
  expect(w.find('.image-viewer__results').exists()).toBe(false)
  await w.setProps({ image: { id: 'sample-2', title: 'a.jpg', src: 'blob:next', width: 1000, height: 800 } })
  await flushPromises()
  expect(w.get('[data-zoom]').text()).toBe('75')
  w.unmount()
})
