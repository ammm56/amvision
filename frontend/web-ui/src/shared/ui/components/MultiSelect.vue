<template>
  <div ref="rootElement" class="ui-multi-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      class="ui-multi-select__button"
      type="button"
      :disabled="disabled"
      :aria-expanded="open"
      :aria-controls="menuId"
      aria-haspopup="listbox"
      @click="toggleOpen"
      @keydown="handleTriggerKeydown"
    >
      <span v-if="selectedOptions.length === 0" class="ui-multi-select__placeholder">{{ resolvedPlaceholder }}</span>
      <span v-else class="ui-multi-select__chips">
        <span v-for="option in selectedOptions" :key="optionKey(option.value)" class="ui-multi-select__chip">
          {{ option.label }}
        </span>
      </span>
      <ChevronDown :size="16" />
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        :id="menuId"
        ref="menuElement"
        class="ui-multi-select__menu"
        :style="menuStyle"
        role="listbox"
        aria-multiselectable="true"
      >
        <button
          v-for="(option, index) in options"
          :key="optionKey(option.value)"
          :id="optionId(index)"
          class="ui-multi-select__option"
          :class="{ 'is-selected': isSelected(option.value), 'is-active': activeIndex === index }"
          type="button"
          role="option"
          :aria-selected="isSelected(option.value)"
          @click.prevent.stop="toggleOption(option.value)"
          @mouseenter="activeIndex = index"
        >
          <span class="ui-multi-select__option-check">
            <Check v-if="isSelected(option.value)" :size="14" />
          </span>
          <span class="ui-multi-select__option-text">
            <span>{{ option.label }}</span>
            <small v-if="option.description">{{ option.description }}</small>
          </span>
        </button>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, type CSSProperties } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'

type MultiSelectValue = string

interface MultiSelectOption {
  label: string
  value: MultiSelectValue
  description?: string
}

const props = withDefaults(
  defineProps<{
    modelValue: MultiSelectValue[]
    options: MultiSelectOption[]
    placeholder?: string
    disabled?: boolean
  }>(),
  {
    placeholder: '',
    disabled: false,
  },
)

const { t } = useTranslation()
const emit = defineEmits<{
  'update:modelValue': [value: MultiSelectValue[]]
  change: [value: MultiSelectValue[]]
}>()

const rootElement = ref<HTMLElement | null>(null)
const menuElement = ref<HTMLElement | null>(null)
const open = ref(false)
const activeIndex = ref(-1)
const menuStyle = ref<CSSProperties>({})
const menuId = `${useId()}-listbox`
const menuGap = 4
const menuMaxHeight = 220
const viewportMargin = 8

const selectedOptions = computed(() => props.options.filter((option) => props.modelValue.includes(option.value)))
const resolvedPlaceholder = computed(() => props.placeholder || t('common.selectPlaceholder'))

function optionKey(value: MultiSelectValue): string {
  return `string:${value}`
}

function isSelected(value: MultiSelectValue): boolean {
  return props.modelValue.includes(value)
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
  menuStyle.value = {}
}

function optionId(index: number): string {
  return `${menuId}-option-${index}`
}

function openMenu(direction: 1 | -1 = 1): void {
  if (props.options.length === 0) return
  open.value = true
  const selectedIndex = props.options.findIndex((option) => isSelected(option.value))
  activeIndex.value = selectedIndex >= 0 ? selectedIndex : direction > 0 ? 0 : props.options.length - 1
  void nextTick(updateMenuPosition)
}

function updateMenuPosition(): void {
  if (!open.value || !rootElement.value) return
  const triggerRect = rootElement.value.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const spaceBelow = viewportHeight - triggerRect.bottom - viewportMargin - menuGap
  const spaceAbove = triggerRect.top - viewportMargin - menuGap
  const openAbove = spaceBelow < menuMaxHeight && spaceAbove > spaceBelow
  const availableHeight = Math.max(96, Math.min(menuMaxHeight, openAbove ? spaceAbove : spaceBelow))
  const menuWidth = Math.min(triggerRect.width, viewportWidth - viewportMargin * 2)
  const menuLeft = Math.min(
    Math.max(viewportMargin, triggerRect.left),
    Math.max(viewportMargin, viewportWidth - menuWidth - viewportMargin),
  )

  menuStyle.value = {
    top: openAbove ? 'auto' : `${triggerRect.bottom + menuGap}px`,
    bottom: openAbove ? `${viewportHeight - triggerRect.top + menuGap}px` : 'auto',
    left: `${menuLeft}px`,
    width: `${menuWidth}px`,
    maxHeight: `${availableHeight}px`,
  }
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
    if (open.value) {
      event.preventDefault()
      event.stopPropagation()
    }
    close()
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    moveActiveOption(event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if ((event.key === 'Enter' || event.key === ' ') && open.value && activeIndex.value >= 0) {
    event.preventDefault()
    const option = props.options[activeIndex.value]
    if (option) toggleOption(option.value)
  }
}

function toggleOption(value: MultiSelectValue): void {
  const nextValue = isSelected(value)
    ? props.modelValue.filter((item) => item !== value)
    : [...props.modelValue, value]
  emit('update:modelValue', nextValue)
  emit('change', nextValue)
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!open.value) return
  const target = event.target
  if (!(target instanceof Node)) return
  if (rootElement.value?.contains(target)) return
  if (menuElement.value?.contains(target)) return
  close()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  window.addEventListener('resize', updateMenuPosition)
  window.addEventListener('scroll', updateMenuPosition, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  window.removeEventListener('resize', updateMenuPosition)
  window.removeEventListener('scroll', updateMenuPosition, true)
})
</script>
