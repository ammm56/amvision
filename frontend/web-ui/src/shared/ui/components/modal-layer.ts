import { nextTick, onBeforeUnmount, ref, type Ref } from 'vue'

// 所有模态容器共用滚动锁和层级，避免关闭内层确认时提前解锁背景。
interface Layer { element: Ref<HTMLElement | null>; opener: HTMLElement | null; order: Ref<number>; covered: Ref<boolean> }
const layers: Layer[] = []
const inertBefore = new Map<HTMLElement, boolean>()
let bodyOverflow = ''

function updateBackground(): void {
  layers.forEach((layer, index) => { layer.covered.value = index < layers.length - 1 })
  for (const [element, inert] of inertBefore) element.inert = inert
  inertBefore.clear()
  const active = layers.at(-1)?.element.value
  if (!active) return
  // 从容器逐级保护同层背景；兼容既有未 Teleport 的确认对话框。
  let branch: HTMLElement = active
  while (branch.parentElement) {
    for (const child of branch.parentElement.children) {
      if (!(child instanceof HTMLElement) || child === branch || /^(SCRIPT|STYLE)$/.test(child.tagName)) continue
      if (child.hasAttribute('data-reka-popper-content-wrapper')) continue
      inertBefore.set(child, child.inert)
      child.inert = true
    }
    if (branch.parentElement === document.body) break
    branch = branch.parentElement
  }
}

export function useModalLayer(element: Ref<HTMLElement | null>) {
  const order = ref(90)
  const covered = ref(false)
  const layer: Layer = { element, opener: null, order, covered }
  const isTop = () => layers.at(-1) === layer

  async function activate(initialFocus?: () => HTMLElement | null | undefined): Promise<void> {
    if (layers.includes(layer)) return
    layer.opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const menuTrigger = layer.opener?.closest('[role="menu"]')?.getAttribute('aria-labelledby')
    if (menuTrigger) layer.opener = document.getElementById(menuTrigger) ?? layer.opener
    if (!layers.length) {
      bodyOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    }
    layers.push(layer)
    order.value = 90 + (layers.length - 1) * 2
    await nextTick()
    if (!isTop()) return
    updateBackground()
    ;(initialFocus?.() ?? element.value)?.focus({ preventScroll: true })
  }

  function deactivate(): void {
    const index = layers.indexOf(layer)
    if (index < 0) return
    const wasTop = isTop()
    layers.splice(index, 1)
    updateBackground()
    if (!layers.length) document.body.style.overflow = bodyOverflow
    if (wasTop) {
      const target = layer.opener?.isConnected && !layer.opener.closest('[inert]')
        ? layer.opener : layers.at(-1)?.element.value
      target?.focus({ preventScroll: true })
    }
  }

  function trapFocus(event: KeyboardEvent): void {
    if (!isTop() || event.defaultPrevented || !element.value) return
    const focusable = [...element.value.querySelectorAll<HTMLElement>(
      ':is(button, [href], input, select, textarea, [tabindex]):not(:disabled):not([tabindex="-1"])',
    )].filter(item => !item.closest('[inert], [hidden]') && getComputedStyle(item).display !== 'none')
    const first = focusable[0]
    const last = focusable.at(-1)
    if (!first || (event.shiftKey && (document.activeElement === first || document.activeElement === element.value))) {
      event.preventDefault()
      ;(last ?? element.value).focus()
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === element.value)) {
      event.preventDefault()
      first.focus()
    }
  }

  onBeforeUnmount(deactivate)
  return { activate, deactivate, trapFocus, isTop, order, covered }
}
