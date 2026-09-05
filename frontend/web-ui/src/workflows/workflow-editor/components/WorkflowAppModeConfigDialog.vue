<template>
  <div class="app-mode-dialog" role="presentation" @mousedown.self="emit('close')">
    <section role="dialog" aria-modal="true" :aria-label="t('workflowEditor.appMode.configTitle')" @mousedown.stop>
      <header>
        <h2>{{ t('workflowEditor.appMode.configTitle') }}</h2>
        <button type="button" :aria-label="t('common.close')" @click="emit('close')"><X :size="18" /></button>
      </header>

      <label class="app-mode-dialog__title">
        <span>{{ t('workflowEditor.appMode.pageTitle') }}</span>
        <input v-model="title" type="text" maxlength="128" :placeholder="applicationTitle" />
      </label>

      <div class="app-mode-dialog__outputs">
        <strong>{{ t('workflowEditor.appMode.displays') }}</strong>
        <p v-if="rows.length === 0">{{ t('workflowEditor.appMode.noPreviewOutputs') }}</p>
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
          <input v-model="row.title" type="text" maxlength="128" :placeholder="row.output_title" :disabled="!row.selected" />
          <Select v-model="row.size" :options="sizeOptions" :disabled="!row.selected" fit-options />
          <span class="app-mode-dialog__order">
            <button type="button" :aria-label="t('workflowEditor.appMode.moveUp')" :disabled="!row.selected || isFirstSelected(row)" @click="moveSelected(row, -1)">↑</button>
            <button type="button" :aria-label="t('workflowEditor.appMode.moveDown')" :disabled="!row.selected || isLastSelected(row)" @click="moveSelected(row, 1)">↓</button>
          </span>
        </div>
      </div>

      <footer>
        <Button v-if="config" variant="danger" @click="emit('remove')">{{ t('workflowEditor.appMode.remove') }}</Button>
        <span />
        <Button variant="secondary" @click="emit('close')">{{ t('common.cancel') }}</Button>
        <Button variant="primary" :disabled="selectedDisplays.length === 0 || hasInvalidSelection" @click="apply">{{ t('workflowEditor.appMode.apply') }}</Button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
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

function identity(display: Pick<WorkflowAppModeDisplayCandidate, 'node_id' | 'output_port'>): string {
  return `${display.node_id}\u0000${display.output_port}`
}

function apply(): void {
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
.app-mode-dialog { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 24px; background: rgb(18 28 23 / 35%); }
.app-mode-dialog > section { width: min(760px, 100%); max-height: min(760px, calc(100dvh - 48px)); overflow: auto; border: 1px solid var(--border-color, #d6dfd9); border-radius: 14px; background: var(--surface-primary, #fff); box-shadow: 0 20px 60px rgb(15 32 23 / 22%); }
.app-mode-dialog header, .app-mode-dialog footer { display: flex; align-items: center; gap: 10px; padding: 16px 18px; }
.app-mode-dialog header { justify-content: space-between; border-bottom: 1px solid var(--border-color, #d6dfd9); }
.app-mode-dialog h2 { margin: 0; font-size: 18px; }
.app-mode-dialog header button { display: grid; place-items: center; border: 0; background: transparent; color: inherit; cursor: pointer; }
.app-mode-dialog__title { display: grid; gap: 7px; padding: 18px; }
.app-mode-dialog__title > span, .app-mode-dialog__outputs > strong { font-size: 13px; font-weight: 700; }
.app-mode-dialog input[type='text'] { min-width: 0; height: 38px; padding: 0 10px; border: 1px solid var(--border-color, #d6dfd9); border-radius: 8px; background: var(--surface-primary, #fff); color: inherit; }
.app-mode-dialog__outputs { display: grid; gap: 10px; padding: 0 18px 18px; }
.app-mode-dialog__outputs > p { margin: 0; padding: 18px; border-radius: 8px; background: var(--surface-secondary, #f4f7f5); color: var(--text-secondary, #69776e); }
.app-mode-dialog__row { display: grid; grid-template-columns: auto minmax(170px, 1fr) minmax(150px, 1fr) auto auto; align-items: center; gap: 12px; padding: 11px; border: 1px solid var(--border-color, #d6dfd9); border-radius: 9px; }
.app-mode-dialog__row--invalid { border-color: #d89b9b; background: rgb(184 50 50 / 5%); }
.app-mode-dialog__identity { min-width: 0; }
.app-mode-dialog__identity strong, .app-mode-dialog__identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-mode-dialog__identity small { color: var(--text-secondary, #69776e); }
.app-mode-dialog__row--invalid .app-mode-dialog__identity small:last-child { color: #b83232; }
.app-mode-dialog__order { display: flex; gap: 4px; }
.app-mode-dialog__order button { width: 28px; height: 28px; border: 1px solid var(--border-color, #d6dfd9); border-radius: 6px; background: var(--surface-primary, #fff); color: inherit; cursor: pointer; }
.app-mode-dialog__order button:disabled { opacity: .35; cursor: default; }
.app-mode-dialog footer { border-top: 1px solid var(--border-color, #d6dfd9); }
.app-mode-dialog footer > span { flex: 1; }
@media (max-width: 720px) { .app-mode-dialog__row { grid-template-columns: auto 1fr auto; } .app-mode-dialog__row > input[type='text'], .app-mode-dialog__row > :nth-child(4) { grid-column: 2 / -1; width: 100%; } }
</style>
