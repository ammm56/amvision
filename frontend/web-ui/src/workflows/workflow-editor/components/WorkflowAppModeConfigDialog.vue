<template>
  <ConfirmDialog size="wide" :title="t('workflowEditor.appMode.configTitle')" :confirm-label="t('workflowEditor.appMode.apply')" :cancel-label="t('common.cancel')" :confirm-disabled="!canApply" confirm-variant="primary" initial-focus="first-field" @cancel="emit('close')" @confirm="apply">
    <div class="app-mode-dialog">
      <label class="app-mode-dialog__title">
        <span>{{ t('workflowEditor.appMode.pageTitle') }}</span>
        <input v-model="title" data-dialog-initial-focus type="text" maxlength="128" :placeholder="applicationTitle" />
      </label>

      <div class="app-mode-dialog__outputs">
        <strong>{{ t('workflowEditor.appMode.displays') }}</strong>
        <p v-if="rows.length === 0">{{ t('workflowEditor.appMode.noPreviewOutputs') }}</p>
        <TransitionGroup name="app-mode-display-list" tag="div" class="app-mode-dialog__row-list">
          <div
            v-for="row in rows"
            :key="identity(row)"
            class="app-mode-dialog__row"
            :class="{ 'app-mode-dialog__row--invalid': row.invalid }"
          >
            <input v-model="row.selected" type="checkbox" :aria-label="row.node_title" />
            <span class="app-mode-dialog__identity">
              <strong>{{ row.node_title }}</strong>
              <small>{{ row.node_id }} · {{ row.output_title }}</small>
              <small v-if="row.invalid">{{ t('workflowEditor.appMode.invalidReference') }}</small>
            </span>
            <input v-model="row.title" class="app-mode-dialog__display-title" type="text" maxlength="128" placeholder="Node" :aria-label="`${row.node_title} ${t('workflowEditor.history.versionName')}`" :disabled="!row.selected" />
            <Select v-model="row.size" :options="sizeOptions" :disabled="!row.selected" fit-options />
            <span class="app-mode-dialog__order">
              <button type="button" :aria-label="t('workflowEditor.appMode.moveUp')" :disabled="!row.selected || isFirstSelected(row)" @click="moveSelected(row, -1)">↑</button>
              <button type="button" :aria-label="t('workflowEditor.appMode.moveDown')" :disabled="!row.selected || isLastSelected(row)" @click="moveSelected(row, 1)">↓</button>
            </span>
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
  close: []
  remove: []
  apply: [config: WorkflowAppModeConfig]
}>()

const { t } = useI18n()
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
const hasInvalidSelection = computed(() => selectedDisplays.value.some((row) => row.invalid))
const canApply = computed(() => selectedDisplays.value.length > 0 && !hasInvalidSelection.value
  && title.value.trim().length <= 128
  && selectedDisplays.value.every(row => row.title.trim().length <= 128 && ['small', 'medium', 'large'].includes(row.size)))

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
.app-mode-dialog { display: grid; gap: 16px; min-width: 0; color: var(--am-text); }
.app-mode-dialog__title { display: grid; gap: 8px; }
.app-mode-dialog__title > span, .app-mode-dialog__outputs > strong { font-size: 13px; font-weight: 700; }
.app-mode-dialog input[type='text'] { min-width: 0; width: 100%; height: 38px; padding: 0 10px; border: 1px solid var(--am-border-strong); border-radius: var(--am-radius-md); background: var(--am-input); color: var(--am-text); }
.app-mode-dialog__outputs, .app-mode-dialog__row-list { display: grid; gap: 12px; min-width: 0; }
.app-mode-dialog__outputs > p { margin: 0; padding: 12px; border-radius: var(--am-radius-md); background: var(--am-surface-muted); color: var(--am-text-muted); }
.app-mode-dialog__row { display: grid; grid-template-columns: auto minmax(170px, 1fr) minmax(150px, 1fr) auto auto; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); background: var(--am-surface); }
.app-mode-dialog__row--invalid { border-color: var(--am-danger-border); background: var(--am-danger-surface); }
.app-mode-dialog__identity { min-width: 0; }
.app-mode-dialog__identity strong, .app-mode-dialog__identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-mode-dialog__identity small { color: var(--am-text-muted); }
.app-mode-dialog__row--invalid .app-mode-dialog__identity small:last-child { color: var(--am-danger-text); }
.app-mode-dialog__row > :nth-child(4) { min-width: 0; }
.app-mode-dialog__order { display: flex; justify-content: flex-end; gap: 4px; }
.app-mode-dialog__order button { width: 28px; height: 28px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); background: var(--am-surface); color: var(--am-text); cursor: pointer; }
.app-mode-dialog__order button:hover:not(:disabled) { border-color: var(--am-action-primary); background: var(--am-row-hover); }
.app-mode-dialog__order button:disabled { opacity: .35; cursor: default; }
.app-mode-display-list-move { transition: transform 180ms cubic-bezier(0.2, 0.8, 0.2, 1); }
@media (max-width: 720px) {
  .app-mode-dialog__row { grid-template-columns: 20px minmax(0, 1fr) 70px; }
  .app-mode-dialog__identity { grid-column: 2; grid-row: 1; }
  .app-mode-dialog__display-title { grid-column: 1 / 3; grid-row: 2; }
  .app-mode-dialog__row > :nth-child(4) { grid-column: 3; grid-row: 2; }
  .app-mode-dialog__order { grid-column: 3; grid-row: 1; }
}
@media (prefers-reduced-motion: reduce) { .app-mode-display-list-move { transition: none; } }
</style>
