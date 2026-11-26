<template>
  <div
    ref="rootElement"
    class="ui-select"
    :class="[$attrs.class, { 'ui-select--fit-options': fitOptions, 'is-open': open, 'is-disabled': disabled }]"
    :style="$attrs.style as CSSProperties"
  >
    <span v-if="fitOptions" class="ui-select__sizer" aria-hidden="true">
      <span v-for="option in options" :key="`sizer-${optionKey(option.value)}`" class="ui-select__sizer-option">
        <span>{{ option.label }}</span>
        <small v-if="option.description">{{ option.description }}</small>
      </span>
    </span>
    <button
      ref="triggerElement"
      v-bind="controlAttrs()"
      class="ui-select__button"
      type="button"
      :disabled="disabled"
      :aria-expanded="open"
      :aria-controls="menuId"
      :aria-label="ariaLabel"
      :aria-activedescendant="open && activeIndex >= 0 ? optionId(activeIndex) : undefined"
      aria-haspopup="listbox"
      @click="toggleOpen"
      @keydown="handleTriggerKeydown"
    >
      <span class="ui-select__value" :class="{ 'is-placeholder': !selectedOption }">
        <slot name="value" :option="selectedOption">{{ selectedOption?.label ?? resolvedPlaceholder }}</slot>
      </span>
      <ChevronDown :size="16" />
    </button>
    <Teleport to="body" :disabled="!floating">
    <div v-if="open" ref="menuElement" :id="menuId" class="ui-select__menu" :class="{ 'ui-select__menu--floating': floating }" :style="floating ? menuStyle : undefined" role="listbox" :aria-label="ariaLabel" @click.prevent.stop>
      <button
        v-for="(option, index) in options"
        :key="optionKey(option.value)"
        :id="optionId(index)"
        class="ui-select__option"
        :class="{ 'is-selected': isSelected(option.value), 'is-active': activeIndex === index }"
        type="button"
        :tabindex="floating ? -1 : undefined"
        role="option"
        :aria-selected="isSelected(option.value)"
        :disabled="option.disabled"
        :aria-disabled="option.disabled || undefined"
        @pointerdown.prevent.stop="selectOption(option.value)"
        @click.prevent.stop="selectOption(option.value)"
        @mouseenter="activeIndex = index"
      >
        <span><slot name="option" :option="option">{{ option.label }}</slot></span>
        <Check v-if="floating && isSelected(option.value)" class="ui-select__check" :size="14" aria-hidden="true" />
        <small v-if="option.description">{{ option.description }}</small>
      </button>
    </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useAttrs, useId, watch, type CSSProperties } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'

type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
  disabled?: boolean
}

defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

function controlAttrs() {
  // 布局样式保留在容器；表单标识、校验和交互属性交给实际控件。
  const { class: _class, style: _style, ...control } = attrs
  return control
}

const props = withDefaults(
  defineProps<{
    modelValue: unknown
    options: SelectOption[]
    placeholder?: string
    disabled?: boolean
    fitOptions?: boolean
    floating?: boolean
    ariaLabel?: string
  }>(),
  {
    placeholder: '',
    disabled: false,
    fitOptions: false,
    floating: false,
  },
)

const { t } = useTranslation()
const emit = defineEmits<{
  'update:modelValue': [value: SelectValue]
  change: [value: SelectValue]
}>()

const rootElement = ref<HTMLElement | null>(null)
const triggerElement = ref<HTMLButtonElement | null>(null)
const menuElement = ref<HTMLElement | null>(null)
const menuStyle = ref<CSSProperties>({})
const open = ref(false)
const activeIndex = ref(-1)
const menuId = `${useId()}-listbox`

const selectedOption = computed(() => props.options.find((option) => Object.is(option.value, props.modelValue)) ?? null)
const resolvedPlaceholder = computed(() => props.placeholder || t('common.selectPlaceholder'))

function optionKey(value: SelectValue): string {
  return `${typeof value}:${String(value)}`
}

function isSelected(value: SelectValue): boolean {
  return Object.is(value, props.modelValue)
}

function toggleOpen(): void {
  if (props.disabled) return
  if (open.value) {
    close()
    return
  }
  openMenu()
}

function close(): void {
  open.value = false
  activeIndex.value = -1
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  window.removeEventListener('scroll', handleViewportChange, true)
  window.removeEventListener('resize', close)
}

function optionId(index: number): string {
  return `${menuId}-option-${index}`
}

function openMenu(direction: 1 | -1 = 1): void {
  if (props.options.length === 0) return
  if (props.floating && triggerElement.value) {
    // 弹窗中的菜单独立定位；只在打开期间监听滚动，避免长期布局计算。
    const rect = triggerElement.value.getBoundingClientRect()
    const below = window.innerHeight - rect.bottom - 12
    const above = rect.top - 12
    const upwards = below < Math.min(280, props.options.length * 40 + 14) && above > below
    const minWidth = Math.min(rect.width, window.innerWidth - 16)
    menuStyle.value = {
      left: `${Math.max(8, Math.min(rect.left, window.innerWidth - minWidth - 8))}px`,
      minWidth: `${minWidth}px`,
      width: 'max-content',
      maxWidth: `${Math.min(360, window.innerWidth - 16)}px`,
      maxHeight: `${Math.max(40, Math.min(280, upwards ? above : below))}px`,
      top: upwards ? 'auto' : `${rect.bottom + 4}px`,
      bottom: upwards ? `${window.innerHeight - rect.top + 4}px` : 'auto',
    }
    void nextTick(() => {
      if (!open.value || !menuElement.value || !triggerElement.value) return
      const triggerRect = triggerElement.value.getBoundingClientRect()
      const menuRect = menuElement.value.getBoundingClientRect()
      menuStyle.value = {
        ...menuStyle.value,
        left: `${Math.max(8, Math.min(triggerRect.left, window.innerWidth - menuRect.width - 8))}px`,
      }
    })
    window.addEventListener('scroll', handleViewportChange, true)
    window.addEventListener('resize', close)
  }
  open.value = true
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  const selectedIndex = props.options.findIndex((option) => isSelected(option.value))
  activeIndex.value = selectedIndex >= 0 && !props.options[selectedIndex]?.disabled
    ? selectedIndex : enabledIndex(direction > 0 ? -1 : 0, direction)
  scrollActiveOption()
}

function enabledIndex(start: number, direction: 1 | -1): number {
  for (let step = 1; step <= props.options.length; step++) {
    const index = (start + direction * step + props.options.length) % props.options.length
    if (!props.options[index]?.disabled) return index
  }
  return -1
}

function scrollActiveOption(): void {
  void nextTick(() => {
    if (!open.value || activeIndex.value < 0) return
    const menu = menuElement.value
    const option = document.getElementById(optionId(activeIndex.value))
    if (!menu || !option) return
    const menuBounds = menu.getBoundingClientRect()
    const optionBounds = option.getBoundingClientRect()
    if (optionBounds.top < menuBounds.top) menu.scrollTop -= menuBounds.top - optionBounds.top
    else if (optionBounds.bottom > menuBounds.bottom) menu.scrollTop += optionBounds.bottom - menuBounds.bottom
  })
}

function moveActiveOption(direction: 1 | -1): void {
  if (!open.value) {
    openMenu(direction)
    return
  }
  const optionCount = props.options.length
  if (optionCount === 0) return
  activeIndex.value = enabledIndex(activeIndex.value, direction)
  scrollActiveOption()
}

function handleTriggerKeydown(event: KeyboardEvent): void {
  if (props.disabled) return
  if (event.key === 'Escape') {
    if (open.value) { event.preventDefault(); event.stopPropagation() }
    close()
    return
  }
  if (event.key === 'Tab') { close(); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    moveActiveOption(event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if ((event.key === 'Enter' || event.key === ' ') && open.value && activeIndex.value >= 0) {
    event.preventDefault()
    const option = props.options[activeIndex.value]
    if (option) selectOption(option.value)
  }
}

function selectOption(value: SelectValue): void {
  if (!open.value || props.disabled || !props.options.some(option => Object.is(option.value, value) && !option.disabled)) return
  emit('update:modelValue', value)
  emit('change', value)
  close()
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!open.value) return
  const target = event.target
  if (!(target instanceof Node)) return
  if (rootElement.value?.contains(target)) return
  if (menuElement.value?.contains(target)) return
  // 若控件被 label 包裹，点击 label 文案会触发原生合成 click，放行避免关闭后立刻重开。
  const ancestorLabel = rootElement.value?.closest('label')
  if (ancestorLabel && ancestorLabel.contains(target) && ancestorLabel.control === triggerElement.value) return
  close()
}

function handleViewportChange(event: Event): void {
  // 菜单自身滚动或与当前控件无关的容器滚动保持打开；父弹窗或页面滚动时关闭，避免菜单脱离控件。
  const target = event.target
  if (target instanceof Node) {
    if (menuElement.value?.contains(target)) return
    if (
      target !== document
      && target !== document.documentElement
      && rootElement.value
      && !target.contains(rootElement.value)
    ) return
  }
  close()
}

onBeforeUnmount(close)

const optionsSignature = computed(() =>
  props.options
    .map(option => `${optionKey(option.value)}\u0000${option.label}\u0000${option.description ?? ''}\u0000${option.disabled ? '1' : '0'}`)
    .join('\u0001'),
)

// 方法或任务切换后不能继续选择已经失效的菜单项，但轮询返回相同选项时不关闭下拉。
watch(() => props.disabled, disabled => { if (disabled) close() })
watch(optionsSignature, (next, previous) => {
  if (open.value && next !== previous) close()
})
</script>

<style scoped>
.ui-select { min-width: 0; max-width: 100%; }
.ui-select__button { min-width: 0; width: 100%; }
.ui-select__value { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ui-select__option:disabled { opacity: .5; cursor: not-allowed; }
.ui-select__menu--floating { position: fixed; right: auto; box-sizing: border-box; z-index: calc(var(--am-z-modal) + 1); font-family: var(--am-font-sans); font-size: 13px; }
.ui-select__menu--floating .ui-select__option { position: relative; padding-right: 30px; font: inherit; }
.ui-select__menu--floating .ui-select__option > span { white-space: nowrap; }
.ui-select__check { position: absolute; right: 8px; top: 10px; color: var(--am-action-primary); }
</style>
