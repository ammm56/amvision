import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import WorkflowDisplayAppearance from './WorkflowDisplayAppearance.vue'
import WorkflowDisplayColor from './WorkflowDisplayColor.vue'
import WorkflowStateColors from './WorkflowStateColors.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'

describe('Display appearance editors', () => {
  it('validates custom colors and keeps presets selectable without typing tokens', async () => {
    const wrapper = mount(WorkflowDisplayColor, { props: { modelValue: 'danger', label: 'Color', presets: true } })
    expect(wrapper.get('input').attributes('placeholder')).toBe('Danger')
    await wrapper.get('input').setValue('url(x)')
    expect(wrapper.emitted('validity-change')!.at(-1)).toEqual([false])
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.get('input').setValue('#abcdef')
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual(['#ABCDEF'])
    await wrapper.get('button').trigger('click')
    await wrapper.get('[aria-label="#D50000"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual(['#D50000'])
    wrapper.unmount()
  })
  it('rejects duplicate state keys and follows reordered field data', async () => {
    const wrapper = mount(WorkflowStateColors, { props: { modelValue: { a: 'success', b: 'danger' } } })
    await wrapper.findAll('input[aria-label="State"]')[1]!.setValue('a')
    expect(wrapper.emitted('validity-change')!.at(-1)).toEqual([false])
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ modelValue: { alarm: '#FF0000' } })
    expect(wrapper.findAll('input[aria-label="State"]')).toHaveLength(1)
    expect((wrapper.get('input[aria-label="State"]').element as HTMLInputElement).value).toBe('alarm')
    wrapper.unmount()
  })
  it('keeps the state input mounted while reactive parent updates echo back', async () => {
    const wrapper = mount(defineComponent({
      components: { WorkflowStateColors },
      setup: () => ({ colors: ref({ alarm: 'danger' }) }),
      template: '<WorkflowStateColors v-model="colors" />',
    }))
    const input = wrapper.get('input[aria-label="State"]')
    await input.setValue('warning')
    await nextTick()
    expect(wrapper.get('input[aria-label="State"]').element).toBe(input.element)
    expect(wrapper.getComponent(WorkflowStateColors).props('modelValue')).toEqual({ warning: 'danger' })
    wrapper.unmount()
  })
  it('cancels without writing and resets invalid drafts before applying defaults', async () => {
    const wrapper = mount(WorkflowDisplayAppearance, { attachTo: document.body, props: { modelValue: { font_size: 24 } } })
    await wrapper.get('.appearance-summary').trigger('click')
    const change = async (label: string, value: string) => {
      const el = document.body.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!
      el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    }
    await change('Font Size', '99')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(true)
    wrapper.getComponent(ConfirmDialog).vm.$emit('cancel'); await nextTick()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.get('.appearance-summary').trigger('click')
    await change('Background Color', 'bad')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(true)
    ;[...document.body.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === '恢复默认')!.click()
    await nextTick()
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(false)
    expect(document.body.querySelector('[role="alert"]')).toBeNull()
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm'); await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[{}]])
    wrapper.unmount()
  })
})
