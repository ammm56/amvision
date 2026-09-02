import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import { i18n } from '@/platform/i18n'
import WorkflowParameterColorMap from './WorkflowParameterColorMap.vue'

let wrapper: VueWrapper | null = null

function mountColorMap(modelValue: unknown = {
  slot_empty: '#00C853',
  slot_full: '#FFB300',
}): VueWrapper {
  wrapper = mount(WorkflowParameterColorMap, {
    attachTo: document.body,
    global: { plugins: [i18n] },
    props: {
      modelValue,
      label: 'Class Colors',
      keyLabel: 'Class Name',
      valueLabel: 'Color',
    },
  })
  return wrapper
}

function requireElement<T extends Element>(selector: string): T {
  const element = document.body.querySelector<T>(selector)
  if (!element) throw new Error(`element not found: ${selector}`)
  return element
}

function updateInput(element: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  element.value = value
  element.dispatchEvent(new Event('input', { bubbles: true }))
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('WorkflowParameterColorMap', () => {
  it('用紧凑摘要显示现有映射，并在编辑器中按键名恢复配置', async () => {
    const mounted = mountColorMap()

    expect(mounted.get('[data-color-map-open]').text()).toContain('已配置 2 项')
    expect(mounted.findAll('.workflow-color-map-summary__swatch')).toHaveLength(2)

    await mounted.get('[data-color-map-open]').trigger('click')
    await nextTick()

    const names = [...document.body.querySelectorAll<HTMLInputElement>('[data-color-map-name]')]
    const colors = [...document.body.querySelectorAll<HTMLInputElement>('[data-color-map-hex]')]
    expect(names.map((input) => input.value)).toEqual(['slot_empty', 'slot_full'])
    expect(colors.map((input) => input.value)).toEqual(['#00C853', '#FFB300'])
  })

  it('仅在应用时原子提交，并规范化键名和颜色', async () => {
    const mounted = mountColorMap({})
    await mounted.get('[data-color-map-open]').trigger('click')
    requireElement<HTMLButtonElement>('[data-color-map-add]').click()
    await nextTick()

    updateInput(requireElement<HTMLInputElement>('[data-color-map-name]'), ' slot_empty ')
    updateInput(requireElement<HTMLInputElement>('[data-color-map-hex]'), '#00c853')
    requireElement<HTMLButtonElement>('.confirm-dialog__actions .ui-button--primary').click()
    await nextTick()

    expect(mounted.emitted('update:modelValue')).toEqual([[{ slot_empty: '#00C853' }]])
    expect(document.body.querySelector('.confirm-dialog')).toBeNull()
  })

  it('拒绝表单重复键，不静默覆盖已有颜色', async () => {
    const mounted = mountColorMap()
    await mounted.get('[data-color-map-open]').trigger('click')
    requireElement<HTMLButtonElement>('[data-color-map-add]').click()
    await nextTick()

    const names = [...document.body.querySelectorAll<HTMLInputElement>('[data-color-map-name]')]
    updateInput(names[2]!, 'slot_empty')
    requireElement<HTMLButtonElement>('.confirm-dialog__actions .ui-button--primary').click()
    await nextTick()

    expect(requireElement<HTMLElement>('[role="alert"]').textContent).toContain('键名重复')
    expect(mounted.emitted('update:modelValue')).toBeUndefined()
  })

  it('高级 JSON 同样拒绝重复键和非字符串值', async () => {
    const mounted = mountColorMap()
    await mounted.get('[data-color-map-open]').trigger('click')
    requireElement<HTMLButtonElement>('[data-color-map-advanced]').click()
    await nextTick()

    const jsonEditor = requireElement<HTMLTextAreaElement>('[data-color-map-json]')
    updateInput(jsonEditor, '{"slot_empty":"#00C853","slot_empty":"#D50000"}')
    requireElement<HTMLButtonElement>('.confirm-dialog__actions .ui-button--primary').click()
    await nextTick()
    expect(requireElement<HTMLElement>('[role="alert"]').textContent).toContain('键名重复')

    updateInput(jsonEditor, '{"slot_empty":123}')
    requireElement<HTMLButtonElement>('.confirm-dialog__actions .ui-button--primary').click()
    await nextTick()
    expect(requireElement<HTMLElement>('[role="alert"]').textContent).toContain('必须是字符串')
    expect(mounted.emitted('update:modelValue')).toBeUndefined()
  })

  it('取消关闭编辑器且不会提交草稿', async () => {
    const mounted = mountColorMap()
    await mounted.get('[data-color-map-open]').trigger('click')
    const firstName = requireElement<HTMLInputElement>('[data-color-map-name]')
    updateInput(firstName, 'changed')
    requireElement<HTMLButtonElement>('[data-confirm-cancel]').click()
    await nextTick()

    expect(mounted.emitted('update:modelValue')).toBeUndefined()
    expect(document.body.querySelector('.confirm-dialog')).toBeNull()
  })
})
