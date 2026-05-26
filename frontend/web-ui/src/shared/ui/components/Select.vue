<template>
  <div ref="rootElement" class="ui-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      class="ui-select__button"
      type="button"
      :disabled="disabled"
      :aria-expanded="open"
      @click="toggleOpen"
      @keydown.escape.prevent="close"
      @keydown.down.prevent="open = true"
    >
      <span class="ui-select__value" :class="{ 'is-placeholder': !selectedOption }">
        {{ selectedOption?.label ?? placeholder }}
      </span>
      <ChevronDown :size="16" />
    </button>
    <div v-if="open" class="ui-select__menu" role="listbox">
      <button
        v-for="option in options"
        :key="optionKey(option.value)"
        class="ui-select__option"
        :class="{ 'is-selected': isSelected(option.value) }"
        type="button"
        role="option"
        :aria-selected="isSelected(option.value)"
        @pointerdown.prevent.stop="selectOption(option.value)"
        @click.prevent.stop="selectOption(option.value)"
      >
        <span>{{ option.label }}</span>
        <small v-if="option.description">{{ option.description }}</small>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChevronDown } from '@lucide/vue'

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
    placeholder: '请选择',
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: SelectValue]
  change: [value: SelectValue]
}>()

const rootElement = ref<HTMLElement | null>(null)
const open = ref(false)

const selectedOption = computed(() => props.options.find((option) => Object.is(option.value, props.modelValue)) ?? null)

function optionKey(value: SelectValue): string {
  return `${typeof value}:${String(value)}`
}

function isSelected(value: SelectValue): boolean {
  return Object.is(value, props.modelValue)
}

function toggleOpen(): void {
  if (props.disabled) return
  open.value = !open.value
}

function close(): void {
  open.value = false
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