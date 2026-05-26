<template>
  <div ref="rootElement" class="ui-multi-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      class="ui-multi-select__button"
      type="button"
      :disabled="disabled"
      :aria-expanded="open"
      @click="toggleOpen"
      @keydown.escape.prevent="close"
      @keydown.down.prevent="open = true"
    >
      <span v-if="selectedOptions.length === 0" class="ui-multi-select__placeholder">{{ placeholder }}</span>
      <span v-else class="ui-multi-select__chips">
        <span v-for="option in selectedOptions" :key="optionKey(option.value)" class="ui-multi-select__chip">
          {{ option.label }}
        </span>
      </span>
      <ChevronDown :size="16" />
    </button>
    <div v-if="open" class="ui-multi-select__menu" role="listbox" aria-multiselectable="true">
      <button
        v-for="option in options"
        :key="optionKey(option.value)"
        class="ui-multi-select__option"
        :class="{ 'is-selected': isSelected(option.value) }"
        type="button"
        role="option"
        :aria-selected="isSelected(option.value)"
        @click.prevent.stop="toggleOption(option.value)"
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
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'

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
    placeholder: '请选择',
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: MultiSelectValue[]]
  change: [value: MultiSelectValue[]]
}>()

const rootElement = ref<HTMLElement | null>(null)
const open = ref(false)

const selectedOptions = computed(() => props.options.filter((option) => props.modelValue.includes(option.value)))

function optionKey(value: MultiSelectValue): string {
  return `string:${value}`
}

function isSelected(value: MultiSelectValue): boolean {
  return props.modelValue.includes(value)
}

function toggleOpen(): void {
  if (props.disabled) return
  open.value = !open.value
}

function close(): void {
  open.value = false
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
  close()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>