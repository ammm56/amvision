import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import ImageGeometryEditorOverlay from './ImageGeometryEditorOverlay.vue'

const mountedWrappers: VueWrapper[] = []

function mountOverlay(
  overrides: Partial<InstanceType<typeof ImageGeometryEditorOverlay>['$props']> = {},
) {
  const props = {
    editable: false,
    activeTool: 'bbox',
    canvasWidth: 200,
    canvasHeight: 100,
    bboxes: [[10, 10, 40, 40]],
    polygons: [[[60, 10], [90, 10], [80, 40]]],
    positivePoints: [[110, 20]],
    negativePoints: [[130, 30]],
    ...overrides,
  }
  const host = defineComponent({
    components: { ImageGeometryEditorOverlay },
    setup: () => ({ props }),
    template: '<svg><ImageGeometryEditorOverlay v-bind="props" /></svg>',
  })
  const hostWrapper = mount(host, { attachTo: document.body })
  mountedWrappers.push(hostWrapper)
  const svg = hostWrapper.find('svg').element as unknown as SVGSVGElement
  Object.defineProperty(svg, 'getScreenCTM', {
    value: () => ({ inverse: () => ({}) }),
  })
  Object.defineProperty(svg, 'createSVGPoint', {
    value: () => ({
      x: 0,
      y: 0,
      matrixTransform() {
        return { x: this.x, y: this.y }
      },
    }),
  })
  return hostWrapper.findComponent(ImageGeometryEditorOverlay)
}

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) {
    wrapper.unmount()
  }
})

describe('ImageGeometryEditorOverlay', () => {
  it('always redraws saved geometry while keeping edit controls disabled', () => {
    const wrapper = mountOverlay()

    expect(wrapper.findAll('.image-geometry-editor__shape')).toHaveLength(2)
    expect(wrapper.findAll('.image-geometry-editor__point')).toHaveLength(2)
    expect(wrapper.findAll('.image-geometry-editor__handle')).toHaveLength(0)
    expect(wrapper.findAll('.image-geometry-editor__delete')).toHaveLength(0)
  })

  it('selects and moves an existing point without creating a new point', async () => {
    const wrapper = mountOverlay({
      editable: true,
      activeTool: 'positive-point',
    })
    const point = wrapper.find('.image-geometry-editor__point--positive')

    await point.trigger('mousedown', { clientX: 110, clientY: 20, button: 0 })
    expect(wrapper.find('.image-geometry-editor__point-item--selected').exists()).toBe(true)

    document.dispatchEvent(new MouseEvent('mousemove', { clientX: 125, clientY: 35 }))
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 125, clientY: 35 }))

    expect(wrapper.emitted('update:positivePoints')?.at(-1)?.[0]).toEqual([[125, 35]])
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('moves and resizes a selected bbox with eight handles', async () => {
    const wrapper = mountOverlay({
      editable: true,
      activeTool: 'bbox',
    })
    const bbox = wrapper.find('.image-geometry-editor__shape')

    await bbox.trigger('mousedown', { clientX: 20, clientY: 20, button: 0 })
    expect(wrapper.find('.image-geometry-editor__item--selected').exists()).toBe(true)
    expect(wrapper.findAll('.image-geometry-editor__handle')).toHaveLength(8)

    document.dispatchEvent(new MouseEvent('mousemove', { clientX: 30, clientY: 25 }))
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 30, clientY: 25 }))
    expect(wrapper.emitted('update:bboxes')?.at(-1)?.[0]).toEqual([[20, 15, 50, 45]])
  })

  it('moves a polygon and edits an individual vertex', async () => {
    const moveWrapper = mountOverlay({
      editable: true,
      activeTool: 'polygon',
    })
    const polygon = moveWrapper.find('polygon.image-geometry-editor__shape')

    await polygon.trigger('mousedown', { clientX: 70, clientY: 20, button: 0 })
    expect(moveWrapper.findAll('.image-geometry-editor__handle')).toHaveLength(8)
    expect(moveWrapper.findAll('.image-geometry-editor__vertex')).toHaveLength(3)
    document.dispatchEvent(new MouseEvent('mousemove', { clientX: 80, clientY: 30 }))
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 80, clientY: 30 }))
    expect(moveWrapper.emitted('update:polygons')?.at(-1)?.[0]).toEqual([[
      [70, 20],
      [100, 20],
      [90, 50],
    ]])

    const vertexWrapper = mountOverlay({
      editable: true,
      activeTool: 'polygon',
    })
    const firstVertex = vertexWrapper.find('.image-geometry-editor__vertex')
    await firstVertex.trigger('mousedown', { clientX: 60, clientY: 10, button: 0 })
    document.dispatchEvent(new MouseEvent('mousemove', { clientX: 55, clientY: 18 }))
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 55, clientY: 18 }))
    expect(vertexWrapper.emitted('update:polygons')?.at(-1)?.[0]).toEqual([[
      [55, 18],
      [90, 10],
      [80, 40],
    ]])
  })

  it('deletes only the selected point', async () => {
    const wrapper = mountOverlay({
      editable: true,
      activeTool: 'positive-point',
      positivePoints: [[20, 20], [40, 40]],
    })
    const points = wrapper.findAll('.image-geometry-editor__point--positive')

    await points[1].trigger('mousedown', { clientX: 40, clientY: 40, button: 0 })
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 40, clientY: 40 }))
    await wrapper.findAll('.image-geometry-editor__delete')[1].trigger('click')

    expect(wrapper.emitted('update:positivePoints')?.at(-1)?.[0]).toEqual([[20, 20]])
  })
})
