<template>
  <div
    ref="rootElement"
    class="ui-select"
    :class="{ 'ui-select--fit-options': fitOptions, 'is-open': open, 'is-disabled': disabled }"
  >
    <span v-if="fitOptions" class="ui-select__sizer" aria-hidden="true">
      <span v-for="option in options" :key="`sizer-${optionKey(option.value)}`" class="ui-select__sizer-option">
        <span>{{ option.label }}</span>
        <small v-if="option.description">{{ option.description }}</small>
      </span>
    </span>
    <button
      ref="triggerElement"
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
        {{ selectedOption?.label ?? resolvedPlaceholder }}
      </span>
      <ChevronDown :size="16" />
    </button>
    <Teleport to="body" :disabled="!floating">
    <div v-if="open" ref="menuElement" :id="menuId" class="ui-select__menu" :class="{ 'ui-select__menu--floating': floating }" :style="floating ? menuStyle : undefined" role="listbox" :aria-label="ariaLabel">
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
        @pointerdown.prevent.stop="selectOption(option.value)"
        @click.prevent.stop="selectOption(option.value)"
        @mouseenter="activeIndex = index"
      >
        <span>{{ option.label }}</span>
        <Check v-if="floating && isSelected(option.value)" class="ui-select__check" :size="14" aria-hidden="true" />
        <small v-if="option.description">{{ option.description }}</small>
      </button>
    </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, type CSSProperties } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'

type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

const props = withDefaults(
  defineProps<{
    modelValue: SelectValue
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
    const width = Math.min(rect.width, window.innerWidth - 16)
    menuStyle.value = {
      left: `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`,
      width: `${width}px`, maxHeight: `${Math.max(40, Math.min(280, upwards ? above : below))}px`,
      top: upwards ? 'auto' : `${rect.bottom + 4}px`,
      bottom: upwards ? `${window.innerHeight - rect.top + 4}px` : 'auto',
    }
    window.addEventListener('scroll', handleViewportChange, true)
    window.addEventListener('resize', close)
  }
  open.value = true
  const selectedIndex = props.options.findIndex((option) => isSelected(option.value))
  activeIndex.value = selectedIndex >= 0 ? selectedIndex : direction > 0 ? 0 : props.options.length - 1
}

function moveActiveOption(direction: 1 | -1): void {
  if (!open.value) {
    openMenu(direction)
    return
  }
  const optionCount = props.options.length
  if (optionCount === 0) return
  activeIndex.value = (activeIndex.value + direction + optionCount) % optionCount
}

function handleTriggerKeydown(event: KeyboardEvent): void {
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
  close()
}

function handleViewportChange(event: Event): void {
  // 菜单自身滚动保持打开；父弹窗或页面滚动时关闭，避免菜单脱离控件。
  if (event.target instanceof Node && menuElement.value?.contains(event.target)) return
  close()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
})

onBeforeUnmount(() => {
  close()
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>

<style scoped>
.ui-select__menu--floating { position: fixed; right: auto; box-sizing: border-box; z-index: calc(var(--am-z-modal) + 1); font-family: var(--am-font-sans); font-size: 13px; }
.ui-select__menu--floating .ui-select__option { position: relative; padding-right: 30px; font: inherit; }
.ui-select__check { position: absolute; right: 8px; top: 10px; color: var(--am-action-primary); }
</style>
