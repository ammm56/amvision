<template>
  <ConfirmDialog size="wide" :title="t('workflowEditor.appMode.configTitle')" :confirm-label="t('workflowEditor.appMode.apply')" :cancel-label="t('common.cancel')" :confirm-disabled="!canApply" confirm-variant="primary" initial-focus="first-field" @cancel="emit('close')" @confirm="apply">
    <div class="app-mode-dialog">
      <label class="app-mode-dialog__title">
        <span>{{ t('workflowEditor.appMode.pageTitle') }}</span>
        <input v-model="title" data-dialog-initial-focus type="text" maxlength="128" :placeholder="applicationTitle" />
      </label>

      <div class="app-mode-dialog__outputs">
        <strong>{{ pt('standalone') }}</strong>
        <p v-if="rows.length === 0">{{ t('workflowEditor.appMode.noPreviewOutputs') }}</p>
        <TransitionGroup name="app-mode-display-list" tag="div" class="app-mode-dialog__row-list">
          <div
            v-for="row in rows"
            :key="identity(row)"
            class="app-mode-dialog__row"
            :class="{ 'app-mode-dialog__row--invalid': row.invalid }"
          >
            <span class="app-mode-dialog__identity">
              <strong>{{ row.node_title }}</strong>
              <small v-if="row.invalid">{{ t('workflowEditor.appMode.invalidReference') }}</small>
            </span>
            <label class="app-mode-dialog__selection">
              <input v-model="row.selected" type="checkbox" :aria-label="`${panelLabel(row)} · ${row.node_title} · ${row.node_id}`" />
              <span>{{ panelLabel(row) }}</span>
            </label>
            <div class="app-mode-dialog__panel-controls">
              <label class="app-mode-dialog__control">
                <span>{{ pt('panelTitle') }}</span>
                <input v-model="row.title" class="app-mode-dialog__display-title" type="text" maxlength="128" :placeholder="row.node_title" :aria-label="`${row.node_title} · ${row.node_id} · ${pt('panelTitle')}`" :disabled="!row.selected" />
              </label>
              <label class="app-mode-dialog__control">
                <span>{{ pt('panelSize') }}</span>
                <Select v-model="row.size" :options="sizeOptions" :disabled="!row.selected" :aria-label="`${row.node_title} · ${row.node_id} · ${pt('panelSize')}`" fit-options />
              </label>
              <span class="app-mode-dialog__order">
                <button type="button" :aria-label="t('workflowEditor.appMode.moveUp')" :disabled="!row.selected || isFirstSelected(row)" @click="moveSelected(row, -1)">↑</button>
                <button type="button" :aria-label="t('workflowEditor.appMode.moveDown')" :disabled="!row.selected || isLastSelected(row)" @click="moveSelected(row, 1)">↓</button>
              </span>
            </div>
            <div v-if="row.node_type_id === 'core.io.image-preview'" class="app-mode-dialog__usage">
              <span>{{ pt('presentation') }}</span>
              <template v-if="row.presentationSource">
                <strong>{{ row.presentationSource.title }}</strong>
                <span v-if="!row.presentationSource.enabled" class="app-mode-dialog__warning">{{ pt('disabled') }}</span>
                <button type="button" :aria-label="`${pt('locate')} · ${row.presentationSource.title} · ${row.presentationSource.nodeId}`" @click="emit('locate', row.presentationSource.nodeId)">{{ pt('locate') }}</button>
              </template>
              <span v-else>{{ pt('imageOnly') }}</span>
            </div>
            <div v-if="row.node_type_id === 'core.io.value-display'" class="app-mode-dialog__usage-list" aria-live="polite">
              <div v-for="target in imageUses(row)" :key="target.nodeId" class="app-mode-dialog__usage">
                <span>{{ pt(target.visible ? 'shownWith' : 'connectedHidden') }}</span>
                <strong>{{ target.title }}</strong>
                <span v-if="!target.enabled" class="app-mode-dialog__warning">{{ pt('disabled') }}</span>
                <button type="button" :aria-label="`${pt('locate')} · ${target.title} · ${target.nodeId}`" @click="emit('locate', target.nodeId)">{{ pt('locate') }}</button>
              </div>
              <span v-if="!row.selected && !imageUses(row).some(target => target.visible)">{{ pt('notOnPage') }}</span>
            </div>
          </div>
        </TransitionGroup>
      </div>

    </div>
    <template v-if="config" #leading-actions><Button variant="danger" @click="emit('remove')">{{ t('workflowEditor.appMode.remove') }}</Button></template>
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import { presentationMessages } from '../app-mode/presentation-messages'
import type {
  WorkflowAppModeConfig,
  WorkflowAppModeDisplayCandidate,
  WorkflowAppModeDisplaySize,
} from '../app-mode/workflow-app-mode'

interface EditableDisplay extends WorkflowAppModeDisplayCandidate {
  selected: boolean
  invalid: boolean
}

const props = defineProps<{
  applicationTitle: string
  config: WorkflowAppModeConfig | null
  candidates: WorkflowAppModeDisplayCandidate[]
}>()

const emit = defineEmits<{
  locate: [nodeId: string]
  close: []
  remove: []
  apply: [config: WorkflowAppModeConfig]
}>()

const { t } = useI18n()
const { t: pt } = useI18n({ useScope: 'local', messages: presentationMessages })
const candidatesByIdentity = new Map(props.candidates.map((candidate) => [identity(candidate), candidate]))
const configuredIdentities = new Set((props.config?.displays ?? []).map((display) => identity(display)))
const title = ref(props.config?.title ?? '')
const rows = ref<EditableDisplay[]>([
  ...(props.config?.displays ?? []).map((display) => {
    const candidate = candidatesByIdentity.get(identity(display))
    return {
      ...(candidate ?? {
        ...display,
        node_title: display.node_id,
        output_title: display.output_port,
      }),
      selected: true,
      invalid: !candidate,
      title: display.title,
      size: display.size,
    }
  }),
  ...props.candidates
    .filter((candidate) => !configuredIdentities.has(identity(candidate)))
    .map((candidate) => ({ ...candidate, selected: false, invalid: false })),
])
const sizeOptions = computed(() => ([
  { value: 'small', label: t('workflowEditor.appMode.sizeSmall') },
  { value: 'medium', label: t('workflowEditor.appMode.sizeMedium') },
  { value: 'large', label: t('workflowEditor.appMode.sizeLarge') },
]))
const selectedDisplays = computed(() => rows.value.filter((row) => row.selected))
const hasInvalidSelection = computed(() => selectedDisplays.value.some(row => row.invalid || row.presentationSource?.enabled === false))
const canApply = computed(() => selectedDisplays.value.length > 0 && !hasInvalidSelection.value
  && title.value.trim().length <= 128
  && selectedDisplays.value.every(row => row.title.trim().length <= 128 && ['small', 'medium', 'large'].includes(row.size)))

/** 用途只由当前连线和布局推导，绝不持久化另一套显示开关。 */
function imageUses(row: EditableDisplay) {
  return (row.connectedImages ?? []).map(target => {
    const imageRow = rows.value.find(item => item.node_id === target.nodeId && item.output_port === 'body')
    return {
      ...target,
      title: imageRow?.title.trim() || target.title,
      visible: Boolean(target.enabled && imageRow?.selected && !imageRow.invalid),
    }
  })
}

function panelLabel(row: EditableDisplay): string {
  if (row.node_type_id === 'core.io.image-preview') return pt('imagePanel')
  if (row.node_type_id === 'core.io.value-display') return pt(imageUses(row).some(target => target.visible) ? 'extraPanel' : 'separatePanel')
  return pt('dataPanel')
}

function identity(display: Pick<WorkflowAppModeDisplayCandidate, 'node_id' | 'output_port'>): string {
  return `${display.node_id}\u0000${display.output_port}`
}

function apply(): void {
  if (!canApply.value) return
  emit('apply', {
    format_id: 'amvision.workflow-app-mode.v1',
    title: title.value.trim(),
    displays: selectedDisplays.value.map((row) => ({
      node_id: row.node_id,
      output_port: row.output_port,
      title: row.title.trim(),
      size: row.size as WorkflowAppModeDisplaySize,
    })),
  })
}

function selectedIndex(row: EditableDisplay): number {
  return selectedDisplays.value.indexOf(row)
}

function isFirstSelected(row: EditableDisplay): boolean {
  return selectedIndex(row) <= 0
}

function isLastSelected(row: EditableDisplay): boolean {
  return selectedIndex(row) === selectedDisplays.value.length - 1
}

function moveSelected(row: EditableDisplay, direction: -1 | 1): void {
  const selected = selectedDisplays.value
  const currentSelectedIndex = selected.indexOf(row)
  const target = selected[currentSelectedIndex + direction]
  if (!target) return
  const currentIndex = rows.value.indexOf(row)
  const targetIndex = rows.value.indexOf(target)
  rows.value.splice(currentIndex, 1, target)
  rows.value.splice(targetIndex, 1, row)
}
</script>

<style scoped>
.app-mode-dialog__usage, .app-mode-dialog__usage-list { grid-column: 1 / -1; min-width: 0; font-size: 13px; }
.app-mode-dialog__usage { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; }
.app-mode-dialog__usage-list { display: grid; gap: 8px; }
.app-mode-dialog__usage strong { overflow-wrap: anywhere; }
.app-mode-dialog__usage button { border: 0; border-radius: var(--am-radius-sm); background: transparent; color: var(--am-action-primary); cursor: pointer; padding: 4px 6px; }
.app-mode-dialog__usage button:focus-visible { outline: 2px solid var(--am-action-primary); outline-offset: 2px; }
.app-mode-dialog__warning { color: var(--am-danger-text); }
.app-mode-dialog__selection { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; }
.app-mode-dialog__panel-controls { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(0, 1fr) 100px auto; align-items: end; gap: 12px; }
.app-mode-dialog__panel-controls :deep(.ui-select__button) { min-height: 38px; }
.app-mode-dialog__control { display: grid; gap: 6px; min-width: 0; font-size: 12px; color: var(--am-text-muted); }
.app-mode-dialog { display: grid; gap: 16px; min-width: 0; color: var(--am-text); }
.app-mode-dialog__title { display: grid; gap: 8px; }
.app-mode-dialog__title > span, .app-mode-dialog__outputs > strong { font-size: 13px; font-weight: 700; }
.app-mode-dialog input[type='text'] { min-width: 0; width: 100%; height: 38px; padding: 0 10px; border: 1px solid var(--am-border-strong); border-radius: var(--am-radius-md); background: var(--am-input); color: var(--am-text); }
.app-mode-dialog__outputs, .app-mode-dialog__row-list { display: grid; gap: 12px; min-width: 0; }
.app-mode-dialog__outputs > p { margin: 0; padding: 12px; border-radius: var(--am-radius-md); background: var(--am-surface-muted); color: var(--am-text-muted); }
.app-mode-dialog__row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); background: var(--am-surface); }
.app-mode-dialog__row--invalid { border-color: var(--am-danger-border); background: var(--am-danger-surface); }
.app-mode-dialog__identity { min-width: 0; }
.app-mode-dialog__identity strong, .app-mode-dialog__identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-mode-dialog__identity small { color: var(--am-text-muted); }
.app-mode-dialog__row--invalid .app-mode-dialog__identity small:last-child { color: var(--am-danger-text); }
.app-mode-dialog__order { display: flex; justify-content: flex-end; gap: 4px; }
.app-mode-dialog__order button { width: 28px; height: 28px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); background: var(--am-surface); color: var(--am-text); cursor: pointer; }
.app-mode-dialog__order button:hover:not(:disabled) { border-color: var(--am-action-primary); background: var(--am-row-hover); }
.app-mode-dialog__order button:disabled { opacity: .35; cursor: default; }
.app-mode-display-list-move { transition: transform 180ms cubic-bezier(0.2, 0.8, 0.2, 1); }
@media (max-width: 720px) {
  .app-mode-dialog__row { grid-template-columns: minmax(0, 1fr); }
  .app-mode-dialog__panel-controls { grid-template-columns: minmax(0, 1fr) 80px; }
  .app-mode-dialog__order { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) { .app-mode-display-list-move { transition: none; } }
</style>
