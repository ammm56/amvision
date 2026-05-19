<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md'
    disabled?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  {
    variant: 'secondary',
    size: 'md',
    disabled: false,
    type: 'button',
  },
)
</script>

<template>
  <button class="ui-button" :class="[`ui-button--${variant}`, `ui-button--${size}`]" :type="type" :disabled="disabled">
    <slot />
  </button>
</template>