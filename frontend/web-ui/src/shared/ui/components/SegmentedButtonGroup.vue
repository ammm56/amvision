<template>
  <div role="radiogroup" class="ui-segments" :aria-label="label">
    <label v-for="option in options" :key="option.value" class="ui-segment">
      <input v-model="selection" type="radio" :name="groupName" :value="option.value" />
      <span>{{ option.label }}</span>
    </label>
  </div>
</template>

<script setup lang="ts">
import { useId } from 'vue'

defineProps<{ label: string; options: { value: string; label: string }[] }>()
const groupName = useId()
const selection = defineModel<string>({ required: true })
</script>

<style scoped>
.ui-segments {
  display: inline-flex;
  width: fit-content;
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
}
.ui-segment {
  position: relative;
  flex: 1 0 auto;
  display: grid;
  place-items: center;
  min-height: 34px;
  padding: 4px 20px;
  border: 1px solid var(--am-border);
  border-radius: 0;
  background: transparent;
  color: var(--am-text);
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
}
.ui-segment:first-child { border-radius: var(--am-radius-sm) 0 0 var(--am-radius-sm); }
.ui-segment:last-child { border-radius: 0 var(--am-radius-sm) var(--am-radius-sm) 0; }
.ui-segment + .ui-segment { margin-inline-start: -1px; }
.ui-segment:hover { background: var(--am-hover-surface); }
.ui-segment input {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  cursor: pointer;
}
.ui-segment:has(:checked) {
  z-index: 1;
  border-color: var(--am-brand-primary);
  background: var(--am-row-selected);
  color: var(--am-brand-primary);
  font-weight: 600;
}
.ui-segment:has(:focus-visible) { z-index: 2; outline: 2px solid var(--am-text-muted); outline-offset: 2px; }
</style>
