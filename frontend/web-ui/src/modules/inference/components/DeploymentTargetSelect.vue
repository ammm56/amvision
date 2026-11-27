<template>
  <div ref="rootElement" class="inf-deploy-select" :class="{ 'is-open': open }">
    <button
      ref="triggerElement"
      type="button"
      class="inf-deploy-select__trigger"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      aria-haspopup="listbox"
      :title="selectedDeployment ? (selectedDeployment.display_name || selectedDeployment.deployment_instance_id) : undefined"
      @click="toggleOpen"
      @keydown="handleTriggerKeydown"
    >
      <span class="inf-deploy-select__value" :class="{ 'is-placeholder': !selectedDeployment }">
        {{ selectedDeployment ? (selectedDeployment.display_name || selectedDeployment.deployment_instance_id) : placeholder }}
      </span>
      <ChevronDown :size="15" class="inf-deploy-select__chevron" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="menuElement"
        class="inf-deploy-popover"
        :style="popoverStyle"
        role="dialog"
        aria-label="选择推理部署"
        @click.stop
      >
        <div class="inf-deploy-popover__search">
          <Search :size="14" class="inf-deploy-popover__search-icon" />
          <input
            ref="searchInputElement"
            v-model="searchQuery"
            type="text"
            class="inf-deploy-popover__search-input"
            placeholder="搜索部署"
            @keydown.esc.prevent.stop="close"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="inf-deploy-popover__clear"
            aria-label="清空搜索"
            @click="searchQuery = ''"
          >
            <X :size="13" />
          </button>
        </div>

        <div class="inf-deploy-popover__list" role="listbox" :aria-label="ariaLabel">
          <div v-if="filteredDeployments.length === 0" class="inf-deploy-popover__empty">
            未找到匹配的部署
          </div>

          <button
            v-for="item in filteredDeployments"
            :key="item.deployment_instance_id"
            type="button"
            role="option"
            class="inf-deploy-option"
            :class="{ 'is-selected': item.deployment_instance_id === modelValue }"
            :aria-selected="item.deployment_instance_id === modelValue"
            @click="selectItem(item.deployment_instance_id)"
          >
            <div class="inf-deploy-option__main">
              <strong
                class="inf-deploy-option__name"
                :title="item.display_name || item.deployment_instance_id"
              >
                {{ item.display_name || item.deployment_instance_id }}
              </strong>
              <span class="inf-deploy-option__sub">{{ formatRuntimeSubline(item) }}</span>
            </div>
            <div class="inf-deploy-option__side">
              <span class="inf-deploy-option__task">{{ formatTaskLabel(item.task_type) }}</span>
              <Check
                v-if="item.deployment_instance_id === modelValue"
                :size="14"
                class="inf-deploy-option__check"
              />
            </div>
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch, type CSSProperties } from 'vue'
import { Check, ChevronDown, Search, X } from '@lucide/vue'

import {
  formatDeploymentBackend,
  formatDeploymentDeviceName,
  formatDeploymentPrecision,
} from '@/modules/deployments/deployment-presentation'
import type { TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'

const TASK_LABELS: Record<string, string> = {
  detection: '目标检测',
  classification: '图像分类',
  segmentation: '实例分割',
  pose: '姿态估计',
  obb: '旋转框检测',
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    deployments: TaskDeploymentInstance[]
    placeholder?: string
    ariaLabel?: string
  }>(),
  {
    placeholder: '请选择部署',
    ariaLabel: '部署',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const rootElement = ref<HTMLElement | null>(null)
const triggerElement = ref<HTMLButtonElement | null>(null)
const menuElement = ref<HTMLElement | null>(null)
const searchInputElement = ref<HTMLInputElement | null>(null)
const open = ref(false)
const searchQuery = ref('')
const popoverStyle = ref<CSSProperties>({})

const selectedDeployment = computed(
  () => props.deployments.find((item) => item.deployment_instance_id === props.modelValue) ?? null,
)

const filteredDeployments = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  if (!kw) return props.deployments
  return props.deployments.filter((item) => {
    const name = (item.display_name || item.deployment_instance_id).toLowerCase()
    const model = (item.model_name || item.model_version_id || '').toLowerCase()
    const taskLabel = formatTaskLabel(item.task_type).toLowerCase()
    const runtime = formatRuntimeSubline(item).toLowerCase()
    return (
      name.includes(kw) ||
      model.includes(kw) ||
      item.task_type.toLowerCase().includes(kw) ||
      taskLabel.includes(kw) ||
      runtime.includes(kw)
    )
  })
})

function formatTaskLabel(taskType: string): string {
  return TASK_LABELS[taskType] || taskType
}

function formatRuntimeSubline(item: TaskDeploymentInstance): string {
  const backend = formatDeploymentBackend(item.runtime_backend)
  const precision = formatDeploymentPrecision(item.runtime_precision)
  const device = formatDeploymentDeviceName(item.device_name)
  return [`${backend}${precision ? ` ${precision}` : ''}`, device].filter(Boolean).join(' · ')
}

function updatePosition(): void {
  if (!triggerElement.value) return
  const rect = triggerElement.value.getBoundingClientRect()
  const width = Math.min(460, Math.max(rect.width, 320), window.innerWidth - 24)
  const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))
  popoverStyle.value = {
    position: 'fixed',
    top: `${rect.bottom + 4}px`,
    left: `${left}px`,
    width: `${width}px`,
  }
}

function toggleOpen(): void {
  if (open.value) {
    close()
    return
  }
  openMenu()
}

function openMenu(): void {
  if (props.deployments.length === 0) return
  searchQuery.value = ''
  updatePosition()
  open.value = true
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  window.addEventListener('resize', close)
  window.addEventListener('scroll', handleViewportScroll, true)
  void nextTick(() => {
    searchInputElement.value?.focus()
  })
}

function close(): void {
  open.value = false
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  window.removeEventListener('resize', close)
  window.removeEventListener('scroll', handleViewportScroll, true)
}

function selectItem(id: string): void {
  emit('update:modelValue', id)
  close()
}

function handleTriggerKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    close()
  }
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!open.value) return
  const target = event.target
  if (!(target instanceof Node)) return
  if (rootElement.value?.contains(target) || menuElement.value?.contains(target)) return
  close()
}

function handleViewportScroll(event: Event): void {
  const target = event.target
  if (target instanceof Node && menuElement.value?.contains(target)) return
  close()
}

watch(
  () => props.deployments.length,
  (len) => {
    if (len === 0 && open.value) close()
  },
)

onBeforeUnmount(close)
</script>

<style scoped>
.inf-deploy-select {
  position: relative;
  min-width: 240px;
  max-width: 340px;
}

.inf-deploy-select__trigger {
  width: 100%;
  height: 36px;
  padding: 0 10px 0 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.inf-deploy-select__trigger:hover {
  border-color: var(--am-border-strong);
}

.inf-deploy-select.is-open .inf-deploy-select__trigger {
  border-color: var(--am-action-primary);
}

.inf-deploy-select__value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.inf-deploy-select__value.is-placeholder {
  color: var(--am-text-muted);
}

.inf-deploy-select__chevron {
  flex: none;
  color: var(--am-text-muted);
}

.inf-deploy-popover {
  z-index: calc(var(--am-z-modal) + 2);
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  box-shadow: var(--am-shadow-floating);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.inf-deploy-popover__search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-deploy-popover__search:focus-within {
  border-bottom-color: var(--am-input-focus-ring);
}

.inf-deploy-popover__search-icon {
  color: var(--am-text-muted);
  flex: none;
}

.inf-deploy-popover__search-input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  outline: none;
}

.inf-deploy-popover__search-input:not([type='hidden']):focus-visible {
  border-color: transparent;
  outline: none;
  box-shadow: none;
}

.inf-deploy-popover__clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.inf-deploy-popover__list {
  max-height: 300px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.inf-deploy-popover__empty {
  padding: 20px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-deploy-option {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 120ms ease;
}

.inf-deploy-option:hover:not(.is-selected) {
  background: var(--am-row-hover);
}

.inf-deploy-option.is-selected {
  background: var(--am-row-selected);
}

.inf-deploy-option__main {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.inf-deploy-option__name {
  font-size: 13px;
  font-weight: 500;
  color: var(--am-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-deploy-option.is-selected .inf-deploy-option__name {
  color: var(--am-action-primary);
  font-weight: 600;
}

.inf-deploy-option__sub {
  font-size: 12px;
  color: var(--am-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-deploy-option__side {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  flex: none;
}

.inf-deploy-option__task {
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-deploy-option__check {
  color: var(--am-action-primary);
}
</style>
