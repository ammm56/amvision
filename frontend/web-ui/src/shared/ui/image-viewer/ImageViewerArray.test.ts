import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/platform/i18n'
import ImageViewer from '../components/ImageViewer.vue'
import ImageGeometryEditorOverlay from './ImageGeometryEditorOverlay.vue'

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })

describe('ImageViewer array tools', () => {
  it('selects row and column independently and applies edited polygon coordinates', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const image = {
      title: 'Grid', nodeId: 'grid', src: 'data:image/png;base64,AA==', width: 800, height: 600,
      overlays: [{ kind: 'polygon', pickable: false, id: 'second', label: 'second', pointsXy: [[100, 20], [140, 20], [140, 50]], bboxXyxy: null, lineXyxy: null, circle: null, targetParameters: [], parameters: {} }],
      interaction: { mode: 'parameter-pick', coordinateSpace: 'image-pixels', tools: [
        { tool: 'polygon', label: 'First ROI Polygon', targetParameters: ['polygon_xy'], initialPointsXy: [[10, 20], [40, 20], [40, 50]], applyParameters: { roi_kind: 'polygon' } },
        { tool: 'line', label: 'Column Step', targetParameters: ['column_step_xy'], initialPointsXy: [[10, 20], [110, 18]] },
        { tool: 'line', label: 'Row Step', targetParameters: ['row_step_xy'], initialPointsXy: [[10, 20], [12, 220]] },
      ] },
    } as InstanceType<typeof ImageViewer>['$props']['image']
    wrapper = mount(ImageViewer, { props: { open: false, image }, global: { plugins: [i18n], stubs: { Teleport: true } } })
    await wrapper.setProps({ open: true })
    const button = (text: string) => wrapper!.findAll('button').find(b => b.text() === text)!
    await button('列步距').trigger('click')
    await wrapper.find(`button[title="${i18n.global.t('imageViewer.toolbar.applyParams')}"]`).trigger('click')
    expect(wrapper.emitted('applyInteraction')?.at(-1)?.[0]).toMatchObject({ targetParameters: ['column_step_xy'], lineXyxy: [10, 20, 110, 18] })
    await button('行步距').trigger('click')
    await wrapper.find(`button[title="${i18n.global.t('imageViewer.toolbar.applyParams')}"]`).trigger('click')
    expect(wrapper.emitted('applyInteraction')?.at(-1)?.[0]).toMatchObject({ targetParameters: ['row_step_xy'], lineXyxy: [10, 20, 12, 220] })
    await button('首槽多边形').trigger('click')
    await wrapper.find(`button[title="${i18n.global.t('imageViewer.toolbar.pickOnImage')}"]`).trigger('click')
    const eventCount = wrapper.emitted('applyInteraction')?.length
    await wrapper.find('.image-viewer__overlay > polygon').trigger('mousedown', { button: 0 })
    expect(wrapper.emitted('applyInteraction')?.length).toBe(eventCount)
    const editor = wrapper.findComponent(ImageGeometryEditorOverlay)
    expect(editor.props('polygons')).toEqual([[[10, 20], [40, 20], [40, 50]]])
    expect(wrapper.find('.image-viewer__overlay > polygon.image-viewer__overlay-shape--draft').exists()).toBe(false)
    expect(wrapper.find('.image-viewer__overlay-point').exists()).toBe(false)
    editor.vm.$emit('update:polygons', [[[11, 21], [41, 21], [41, 51]]])
    await wrapper.vm.$nextTick()
    await wrapper.find(`button[title="${i18n.global.t('imageViewer.toolbar.applyParams')}"]`).trigger('click')
    expect(wrapper.emitted('applyInteraction')?.at(-1)?.[0]).toMatchObject({ targetParameters: ['polygon_xy'], pointsXy: [[11, 21], [41, 21], [41, 51]], parameters: { roi_kind: 'polygon' } })
  })
})
