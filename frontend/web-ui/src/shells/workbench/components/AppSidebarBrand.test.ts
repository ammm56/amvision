import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AppSidebarBrand from './AppSidebarBrand.vue'

// 生命周期测试隔离动画帧；真实 Motion 进出场在浏览器中验证。
vi.mock('motion-v', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    AnimatePresence: defineComponent({
      props: ['mode', 'initial'],
      setup: (_, { slots }) => () => slots.default?.(),
    }),
    Motion: defineComponent({
      props: ['as', 'initial', 'animate', 'exit', 'transition', 'layout'],
      setup: (props, { slots }) => () => h(props.as || 'span', slots.default?.()),
    }),
  }
})

let wrapper: VueWrapper | undefined
let hidden = false
let reduced = false
let motionChanged: (() => void) | undefined
const removeMotionListener = vi.fn()

function mountBrand() {
  wrapper = mount(AppSidebarBrand, {
    global: { stubs: { RouterLink: { template: '<a href="/"><slot /></a>' } } },
  })
  return wrapper
}
function visibleWord() { return wrapper!.get('.sidebar-brand__word').text() }

beforeEach(() => {
  vi.useFakeTimers()
  hidden = false
  reduced = false
  motionChanged = undefined
  removeMotionListener.mockClear()
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  vi.spyOn(window, 'matchMedia').mockImplementation(() => ({
    get matches() { return reduced },
    addEventListener: (_: string, listener: () => void) => { motionChanged = listener },
    removeEventListener: removeMotionListener,
  }) as unknown as MediaQueryList)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('AppSidebarBrand', () => {
  it('按固定顺序轮换全部词缀并循环，保持根路径和可访问名称稳定', async () => {
    const brand = mountBrand()
    expect(visibleWord()).toBe('Vision')
    for (const word of ['Workflow', 'DeepLearn', 'Connect', 'Identify', 'Control', 'Motion', 'Label', 'Agent', 'Vision']) {
      await vi.advanceTimersByTimeAsync(2000)
      expect(visibleWord()).toBe(word)
      expect(brand.attributes('aria-label')).toBe('AMVAR Vision')
      expect(brand.attributes('href')).toBe('/')
    }
  })

  it('悬停和键盘聚焦独立暂停，全部解除后重新等待完整间隔', async () => {
    const brand = mountBrand()
    await brand.trigger('mouseenter')
    await brand.trigger('focusin')
    expect(vi.getTimerCount()).toBe(0)
    await brand.trigger('mouseleave')
    await vi.advanceTimersByTimeAsync(12000)
    expect(visibleWord()).toBe('Vision')
    await brand.trigger('focusout')
    await vi.advanceTimersByTimeAsync(1999)
    expect(visibleWord()).toBe('Vision')
    await vi.advanceTimersByTimeAsync(1)
    expect(visibleWord()).toBe('Workflow')
  })

  it('后台停止计时，返回前台不补播，卸载移除计时器和监听', async () => {
    const removeVisibility = vi.spyOn(document, 'removeEventListener')
    const brand = mountBrand()
    await vi.advanceTimersByTimeAsync(2000)
    hidden = true
    document.dispatchEvent(new Event('visibilitychange'))
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(60000)
    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))
    expect(visibleWord()).toBe('Workflow')
    await vi.advanceTimersByTimeAsync(2000)
    expect(visibleWord()).toBe('DeepLearn')
    brand.unmount()
    wrapper = undefined
    expect(vi.getTimerCount()).toBe(0)
    expect(removeVisibility).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
    expect(removeMotionListener).toHaveBeenCalledWith('change', expect.any(Function))
  })

  it('减少动态效果时静态显示 Vision，并响应偏好实时变化', async () => {
    reduced = true
    mountBrand()
    expect(vi.getTimerCount()).toBe(0)
    expect(visibleWord()).toBe('Vision')
    reduced = false
    motionChanged!()
    await vi.advanceTimersByTimeAsync(2000)
    expect(visibleWord()).toBe('Workflow')
    reduced = true
    motionChanged!()
    await nextTick()
    expect(visibleWord()).toBe('Vision')
    expect(vi.getTimerCount()).toBe(0)
  })
})
