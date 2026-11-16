import { flushPromises, type VueWrapper } from '@vue/test-utils'
import Select from '@/shared/ui/components/Select.vue'

export function selectControl(wrapper: VueWrapper, value?: unknown) {
  const controls = wrapper.findAllComponents(Select)
  const control = value === undefined ? controls[0] : controls.find(c => Object.is(c.props('modelValue'), value))
  if (!control) throw new Error(`Select not found: ${String(value)}`)
  return control
}

export function selectWithOption(wrapper: VueWrapper, value: unknown) {
  const control = wrapper.findAllComponents(Select).find(c => c.props('options').some(o => Object.is(o.value, value)))
  if (!control) throw new Error(`Select option not found: ${String(value)}`)
  return control
}

export async function chooseSelect(control: ReturnType<typeof selectControl>, value: unknown) {
  const options = control.props('options') as { value: unknown }[]
  const index = options.findIndex(o => Object.is(o.value, value))
  if (index < 0) throw new Error(`Option not found: ${String(value)}`)
  const trigger = control.get('.ui-select__button')
  await trigger.trigger('click')
  const menu = document.getElementById(trigger.attributes('aria-controls')!) ?? control.find('[role=listbox]').element
  const option = menu.querySelectorAll<HTMLButtonElement>('[role=option]')[index]!
  if (option.disabled) throw new Error(`Option disabled: ${String(value)}`)
  option.click()
  await flushPromises()
}

export async function chooseLabel(trigger: Element, label: string) {
  ;(trigger as HTMLButtonElement).click()
  await flushPromises()
  const menu = document.getElementById(trigger.getAttribute('aria-controls')!)!
  const option = [...menu.querySelectorAll<HTMLButtonElement>('[role=option]')].find(o => o.textContent?.trim() === label)
  if (!option || option.disabled) throw new Error(`Enabled option not found: ${label}`)
  option.click()
  await flushPromises()
}
