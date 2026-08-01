<template>
  <div ref="rootElement" class="ui-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      class="ui-select__button"
      type="button"
      :disabled="disabled"
      :aria-expanded="open"
      :aria-controls="menuId"
      aria-haspopup="listbox"
      @click="toggleOpen"
      @keydown="handleTriggerKeydown"
    >
      <span class="ui-select__value" :class="{ 'is-placeholder': !selectedOption }">
        {{ selectedOption?.label ?? resolvedPlaceholder }}
      </span>
      <ChevronDown :size="16" />
    </button>
    <div v-if="open" :id="menuId" class="ui-select__menu" role="listbox">
      <button
        v-for="(option, index) in options"
        :key="optionKey(option.value)"
        :id="optionId(index)"
        class="ui-select__option"
        :class="{ 'is-selected': isSelected(option.value), 'is-active': activeIndex === index }"
        type="button"
        role="option"
        :aria-selected="isSelected(option.value)"
        @pointerdown.prevent.stop="selectOption(option.value)"
        @click.prevent.stop="selectOption(option.value)"
        @mouseenter="activeIndex = index"
      >
        <span>{{ option.label }}</span>
        <small v-if="option.description">{{ option.description }}</small>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { ChevronDown } from '@lucide/vue'
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
  }>(),
  {
    placeholder: '',
    disabled: false,
  },
)

const { t } = useTranslation()
const emit = defineEmits<{
  'update:modelValue': [value: SelectValue]
  change: [value: SelectValue]
}>()

const rootElement = ref<HTMLElement | null>(null)
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
}

function optionId(index: number): string {
  return `${menuId}-option-${index}`
}

function openMenu(direction: 1 | -1 = 1): void {
  if (props.options.length === 0) return
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
    if (open.value) event.preventDefault()
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
  close()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>
