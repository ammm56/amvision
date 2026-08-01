<template>
  <div ref="tabListRef" class="local-tabs" role="tablist" :aria-label="label">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      class="local-tabs__tab"
      :class="{ 'is-active': modelValue === tab.id }"
      type="button"
      role="tab"
      :aria-selected="modelValue === tab.id"
      :disabled="tab.disabled"
      :tabindex="modelValue === tab.id ? 0 : -1"
      :data-tab-id="tab.id"
      @click="selectTab(tab)"
      @keydown="handleKeydown"
    >
      <component :is="tab.icon" v-if="tab.icon" :size="15" aria-hidden="true" />
      <span>{{ tab.label }}</span>
      <strong v-if="tab.count !== undefined" class="local-tabs__count">{{ tab.count }}</strong>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, type Component } from 'vue'

export interface TabListItem {
  id: string
  label: string
  count?: number
  icon?: Component
  disabled?: boolean
}

const props = defineProps<{
  modelValue: string
  tabs: readonly TabListItem[]
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const tabListRef = ref<HTMLElement | null>(null)

function selectTab(tab: TabListItem): void {
  if (!tab.disabled) emit('update:modelValue', tab.id)
}

function handleKeydown(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return

  const enabledTabs = Array.from(tabListRef.value?.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)') ?? [])
  if (enabledTabs.length === 0) return

  const currentIndex = enabledTabs.indexOf(event.currentTarget as HTMLButtonElement)
  let nextIndex = currentIndex
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = enabledTabs.length - 1
  if (event.key === 'ArrowLeft') nextIndex = (Math.max(currentIndex, 0) - 1 + enabledTabs.length) % enabledTabs.length
  if (event.key === 'ArrowRight') nextIndex = (Math.max(currentIndex, -1) + 1) % enabledTabs.length

  event.preventDefault()
  const nextTab = enabledTabs[nextIndex]
  const nextId = nextTab?.dataset.tabId
  if (!nextTab || !nextId || !props.tabs.some((tab) => tab.id === nextId && !tab.disabled)) return
  emit('update:modelValue', nextId)
  nextTab.focus()
}
</script>
