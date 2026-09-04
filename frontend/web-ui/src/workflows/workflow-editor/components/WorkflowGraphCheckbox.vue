<template>
  <span class="workflow-graph-checkbox">
    <input
      class="workflow-graph-checkbox__input"
      type="checkbox"
      :checked="checked"
      :disabled="disabled"
      :aria-label="ariaLabel"
      @change="emit('change', $event)"
    >
    <span class="workflow-graph-checkbox__control" aria-hidden="true">
      <Check v-if="checked" :size="13" :stroke-width="3" />
    </span>
  </span>
</template>

<script setup lang="ts">
import { Check } from '@lucide/vue'

withDefaults(defineProps<{
  checked?: boolean
  disabled?: boolean
  ariaLabel?: string
}>(), {
  checked: false,
  disabled: false,
  ariaLabel: undefined,
})

const emit = defineEmits<{
  change: [event: Event]
}>()
</script>
