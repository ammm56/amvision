import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useWorkflowEditorLifecycle } from './useWorkflowEditorLifecycle'

afterEach(() => vi.unstubAllGlobals())

describe('工具栏与浮层布局生命周期', () => {
  it('根据工具栏实际高度更新浮层边界，卸载时断开观察和事件', () => {
    let resized: () => void = () => undefined
    const observe = vi.fn()
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resized = callback }
      observe = observe
      disconnect = disconnect
    })
    const stage = document.createElement('div')
    const toolbar = document.createElement('div')
    Object.defineProperty(toolbar, 'offsetTop', { value: 14, configurable: true })
    Object.defineProperty(toolbar, 'offsetHeight', { value: 44, configurable: true })
    const updateStageSize = vi.fn()
    const stopNodeDrag = vi.fn()
    const wrapper = mount(defineComponent({
      setup() {
        useWorkflowEditorLifecycle({
          canvasRef: ref(stage), toolbarRef: ref({ $el: toolbar }),
          loadPage: vi.fn(), handleKeydown: vi.fn(), updateStageSize,
          stopNodeDrag, stopBoundaryDrag: vi.fn(), stopPortConnection: vi.fn(),
          stopStagePan: vi.fn(), stopMinimapNavigation: vi.fn(),
          revokePreviewImageObjectUrls: vi.fn(),
        })
        return () => null
      },
    }))
    expect(observe.mock.calls).toEqual([[stage], [toolbar]])
    expect(stage.style.getPropertyValue('--workflow-toolbar-bottom')).toBe('70px')
    Object.defineProperty(toolbar, 'offsetTop', { value: 10 })
    Object.defineProperty(toolbar, 'offsetHeight', { value: 237 })
    resized()
    expect(stage.style.getPropertyValue('--workflow-toolbar-bottom')).toBe('259px')
    window.dispatchEvent(new Event('resize'))
    expect(updateStageSize).toHaveBeenCalledTimes(3)
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalledOnce()
    expect(stopNodeDrag).toHaveBeenCalledOnce()
    expect(stage.style.getPropertyValue('--workflow-toolbar-bottom')).toBe('')
    window.dispatchEvent(new Event('resize'))
    expect(updateStageSize).toHaveBeenCalledTimes(3)
  })
})
