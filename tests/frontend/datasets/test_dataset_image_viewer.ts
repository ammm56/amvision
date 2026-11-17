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

it('分割预览分别控制轮廓、填充和透明度，加载时禁止修改', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  const w = mount(DatasetImageViewer, {
    props: { open: true, image: { id: 'seg-1', title: 'a.jpg', src: 'blob:seg', width: 100, height: 100 }, datasetName: '数据集', version: 'v1', split: 'train', objectCount: 1, annotations: true, busy: false, hasPrevious: false, hasNext: false, invalid: 0, task: 'segmentation', segmentationOutline: true, segmentationFill: true, segmentationOpacity: 35 },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { SelectField: { props: ['modelValue', 'disabled'], template: '<button :disabled="disabled" @click="$emit(\'update:modelValue\', \'50\')">{{ modelValue }}</button>' } } },
  })
  const controls = w.findAll('input[type="checkbox"]')
  await controls[0].setValue(false)
  await controls[1].setValue(false)
  await w.get('.dataset-image-opacity').trigger('click')
  expect(w.emitted('segmentation-outline')).toEqual([[false]])
  expect(w.emitted('segmentation-fill')).toEqual([[false]])
  expect(w.emitted('segmentation-opacity')).toEqual([[50]])
  await w.setProps({ busy: true })
  expect(controls.every(control => control.attributes('disabled') !== undefined)).toBe(true)
  expect(w.get('.dataset-image-opacity').attributes('disabled')).toBeDefined()
  w.unmount()
})

it('分类大图显示标签数量和样本信息入口', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  const w = mount(DatasetImageViewer, {
    props: { open: true, image: { id: 'class-1', title: 'a.jpg', src: 'blob:raw', width: 100, height: 100 }, datasetName: '数据集', version: 'v1', split: 'train', objectCount: 1, annotations: true, busy: false, hasPrevious: false, hasNext: false, invalid: 0, task: 'classification' },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { SelectField: true } },
  })
  expect(w.text()).toContain('1 标签')
  expect(w.text()).toContain('样本信息')
  expect(w.find('input[role="switch"]').exists()).toBe(false)
  w.unmount()
})
