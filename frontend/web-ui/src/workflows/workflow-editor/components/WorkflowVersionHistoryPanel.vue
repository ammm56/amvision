<template>
  <aside v-if="open" class="workflow-graph-floating-panel workflow-history-panel" :aria-label="t('workflowEditor.history.title')" @mousedown.stop @contextmenu.stop @keydown.esc.stop="emit('close')">
    <div class="workflow-graph-panel__header">
      <h2>{{ t('workflowEditor.history.title') }}</h2>
      <div class="workflow-graph-panel__tools">
        <button type="button" class="workflow-graph-panel__icon-button" :disabled="loading || blocked" :aria-label="t('common.refresh')" :title="t('common.refresh')" @click="emit('refresh')"><RefreshCw :size="15" /></button>
        <button type="button" class="workflow-graph-panel__icon-button" :aria-label="t('common.close')" :title="t('common.close')" @click="emit('close')"><X :size="17" /></button>
      </div>
    </div>
    <div class="workflow-history__content">
      <InlineError v-if="error" :message="error" />
      <ol class="workflow-history__timeline">
        <li class="workflow-history__row workflow-history__draft">
          <span class="workflow-history__dot" aria-hidden="true" />
          <strong>{{ t('workflowEditor.history.currentDraft') }}</strong>
          <span class="workflow-history__meta">{{ documentState }}</span>
        </li>
        <li v-for="version in versions" :key="version.workflow_app_version_id" class="workflow-history__row">
          <span class="workflow-history__dot" aria-hidden="true" />
          <div class="workflow-history__heading">
            <button class="workflow-history__load" type="button" :disabled="loading || blocked" :aria-label="versionLabel(version)" @click="emit('select', version)">
              <strong>V{{ version.version_number }}</strong><span v-if="hasCustomVersionName(version)">{{ version.display_version }}</span>
            </button>
            <span v-if="version.workflow_app_version_id === latestVersionId" class="workflow-history__badge">{{ t('workflowEditor.history.latestBadge') }}</span>
            <span v-if="version.state === 'archived'" class="workflow-history__archived">{{ t('workflowEditor.history.archived') }}</span>
            <DropdownMenuRoot>
              <DropdownMenuTrigger as-child><button type="button" class="workflow-history__menu-trigger" :disabled="loading || blocked" :aria-label="t('workflowEditor.history.actions', { version: version.display_version })"><Ellipsis :size="18" /></button></DropdownMenuTrigger>
              <DropdownMenuPortal><DropdownMenuContent class="workflow-history-menu" align="end" :side-offset="4" @close-auto-focus="event => { if (edit?.kind === 'rename') event.preventDefault() }">
                <DropdownMenuItem as="button" type="button" @select="emit('select', version)">{{ t('workflowEditor.history.load', { version: version.display_version }) }}</DropdownMenuItem>
                <DropdownMenuItem as="button" type="button" @select="startRename(version)">{{ t('workflowEditor.history.rename') }}</DropdownMenuItem>
                <DropdownMenuItem as="button" type="button" @select="emit('export', version)">{{ t('workflowEditor.history.export') }}</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem as="button" type="button" class="workflow-history__danger" @select="edit = { kind: 'delete', version }; name = ''">{{ t('workflowEditor.history.delete') }}</DropdownMenuItem>
              </DropdownMenuContent></DropdownMenuPortal>
            </DropdownMenuRoot>
          </div>
          <span class="workflow-history__meta" :title="version.created_by || undefined">{{ formatSystemDateTime(version.completed_at || version.created_at) }}</span>
          <p v-if="version.release_notes" class="workflow-history__notes">{{ version.release_notes }}</p>
          <div v-if="edit?.version.workflow_app_version_id === version.workflow_app_version_id && edit.kind === 'delete'" class="workflow-history__edit">
            <p>{{ t('workflowEditor.history.deleteHint', { version: version.display_version }) }}</p>
            <div><Button variant="danger" :disabled="loading || blocked" @click="emit('delete', version)">{{ t('workflowEditor.history.delete') }}</Button><Button variant="secondary" :disabled="loading || blocked" @click="edit = null">{{ t('common.cancel') }}</Button></div>
          </div>
        </li>
      </ol>
      <p v-if="loading" role="status" class="workflow-history__status">{{ t('workflowEditor.history.loading') }}</p>
      <p v-else-if="!versions.length && !error" class="workflow-history__status">{{ t('workflowEditor.history.empty') }}</p>
      <Button v-if="hasMore" variant="secondary" :disabled="loading || blocked" @click="emit('more')">{{ t('workflowEditor.history.more') }}</Button>
    </div>
  </aside>
  <Teleport to="body">
    <ConfirmDialog v-if="open && edit?.kind === 'rename'" :title="t('workflowEditor.history.title')" :confirm-label="t('workflowEditor.actions.saveWorkflowApp')" :cancel-label="t('common.cancel')" :busy="loading || blocked" :confirm-disabled="!name.trim()" confirm-variant="primary" initial-focus="first-field" @cancel="edit = null" @confirm="emit('rename', edit.version, name, releaseNotes)">
      <label class="field"><span>{{ t('workflowEditor.history.versionName') }}</span><input v-model="name" data-dialog-initial-focus maxlength="128" :disabled="loading || blocked" /></label>
      <label class="field"><span>{{ t('workflowEditor.publishDialog.releaseNotes') }}</span><textarea v-model="releaseNotes" rows="5" maxlength="4096" :disabled="loading || blocked" /></label>
      <InlineError v-if="error" :message="error" />
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Ellipsis, RefreshCw, X } from '@lucide/vue'
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from 'reka-ui'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import type { WorkflowAppVersion } from '../types'
const props = defineProps<{ open: boolean; blocked?: boolean; versions: WorkflowAppVersion[]; loading: boolean; selectedId: string | null; error: string | null; hasMore: boolean; latestVersionId?: string; documentState?: string }>()
const emit = defineEmits<{ close: []; refresh: []; more: []; select: [version: WorkflowAppVersion]; rename: [version: WorkflowAppVersion, name: string, releaseNotes: string]; export: [version: WorkflowAppVersion]; delete: [version: WorkflowAppVersion] }>()
const { t } = useI18n()
const edit = ref<{ kind: 'rename' | 'delete'; version: WorkflowAppVersion } | null>(null)
const name = ref('')
const releaseNotes = ref('')
function hasCustomVersionName(version: WorkflowAppVersion): boolean {
  return version.display_version.toLowerCase() !== `v${version.version_number}`
}
function versionLabel(version: WorkflowAppVersion): string {
  return `V${version.version_number}${hasCustomVersionName(version) ? ` ${version.display_version}` : ''}`
}
function startRename(version: WorkflowAppVersion): void {
  name.value = version.display_version
  releaseNotes.value = version.release_notes || ''
  edit.value = { kind: 'rename', version }
}
watch(() => props.open, () => { edit.value = null })
watch(() => props.loading, (loading, wasLoading) => { if (wasLoading && !loading && !props.error) edit.value = null })
</script>
<style scoped>
.workflow-history-panel { box-sizing: border-box; padding: 0; top: var(--workflow-toolbar-bottom, 104px); right: 14px; bottom: 64px; width: 320px; max-width: calc(100% - 20px); grid-template-rows: auto minmax(0, 1fr); align-content: stretch; gap: 0; overflow: hidden; }
.workflow-history-panel > .workflow-graph-panel__header { min-height: 52px; padding: 10px 14px; }
.workflow-history-panel h2 { margin: 0; font-size: 18px; color: var(--graph-text-strong); }
@media (max-width: 720px) { .workflow-history-panel { right: 10px; bottom: 60px; } }
.workflow-history__content { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 4px 8px 16px; scrollbar-width: thin; }
.workflow-history__timeline { display: flex; flex-direction: column; gap: 8px; list-style: none; padding: 0; margin: 0; }
.workflow-history__row { position: relative; padding: 16px 10px 16px 42px; min-height: 64px; border-radius: 10px; color: var(--graph-text); transition: background-color 160ms ease; }
.workflow-history__row:not(:last-child)::after { content: ''; position: absolute; z-index: 1; left: 23px; top: 32px; bottom: -31px; width: 2px; background: var(--graph-line); pointer-events: none; }
.workflow-history__dot { position: absolute; z-index: 2; top: 23px; left: 18px; width: 12px; height: 12px; border: 3px solid var(--graph-muted); border-radius: 50%; box-sizing: border-box; background: var(--graph-panel); }
.workflow-history__draft { background: color-mix(in srgb, var(--am-action-primary) 12%, transparent); color: var(--am-action-primary); }
.workflow-history__draft .workflow-history__dot { border-color: var(--am-action-primary); }
.workflow-history__row:hover, .workflow-history__row:focus-within { background: var(--graph-hover); }
.workflow-history__draft:hover { background: color-mix(in srgb, var(--am-action-primary) 12%, transparent); }
.workflow-history__heading { display: flex; align-items: center; gap: 6px; min-height: 24px; }
.workflow-history__load { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px; min-width: 0; padding: 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; font-size: 14px; overflow-wrap: anywhere; }
.workflow-history__load strong { white-space: nowrap; }
.workflow-history__menu-trigger { display: grid; place-items: center; width: 28px; height: 28px; padding: 0; flex-shrink: 0; margin-left: auto; border: 0; border-radius: 6px; color: var(--graph-muted); background: transparent; cursor: pointer; }
.workflow-history__menu-trigger:hover, .workflow-history__menu-trigger[data-state=open] { background: var(--graph-hover); color: var(--graph-text-strong); }
.workflow-history__load:disabled, .workflow-history__menu-trigger:disabled { cursor: not-allowed; }
.workflow-history__meta { display: block; margin-top: 6px; font-size: 12px; color: var(--graph-muted); }
.workflow-history__notes { margin: 6px 0 0; font-size: 12px; color: var(--graph-muted); white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-history__badge { padding: 2px 5px; border: 1px solid var(--am-action-primary); color: var(--am-action-primary); border-radius: 5px; font-size: 11px; white-space: nowrap; }
.workflow-history__archived { font-size: 11px; white-space: nowrap; color: var(--graph-muted); }
.workflow-history__status { padding: 12px; color: var(--graph-muted); font-size: 13px; }
.workflow-history__edit { display: grid; gap: 8px; padding-top: 12px; font-size: 13px; }
.workflow-history__edit input { min-width: 0; width: 100%; box-sizing: border-box; border: 1px solid var(--am-border); border-radius: 5px; padding: 8px; color: var(--am-text); background: var(--am-surface); }
.workflow-history__edit p { margin: 0; }
.workflow-history__edit > div { display: flex; gap: 8px; }
.workflow-history__load:focus-visible, .workflow-history__menu-trigger:focus-visible { outline: 2px solid var(--am-action-primary); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { .workflow-history__row { transition: none; } }
</style>
<style>
/* Reka 将 scoped 属性放在 Popper 包装层上；传送到 body 的菜单内容使用专属全局类。 */
.workflow-history-menu { z-index: 200; min-width: 180px; max-width: 320px; padding: 5px; background: var(--am-surface); color: var(--am-text-strong); border: 1px solid var(--am-border); border-radius: 10px; box-shadow: 0 8px 24px #0003; }
.workflow-history-menu [role=menuitem] { display: block; width: 100%; border: 0; text-align: left; background: transparent; color: inherit; padding: 9px 12px; border-radius: 6px; outline: none; font-size: 13px; cursor: pointer; overflow-wrap: anywhere; }
.workflow-history-menu [data-highlighted] { background: var(--am-graph-hover); }
.workflow-history-menu [role=separator] { height: 1px; background: var(--am-border); margin: 4px 0; }
.workflow-history-menu .workflow-history__danger { color: var(--am-danger, #dc4b4b); }
</style>
