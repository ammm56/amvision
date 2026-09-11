<template>
  <Teleport to="body">
    <ConfirmDialog
      :title="target ? t('removeTitle') : t('manage')"
      :message="target?.dataset_version_id"
      :details="target ? t('removeDetails') : undefined"
      :confirm-label="t('remove')"
      :cancel-label="target ? t('cancel') : t('close')"
      :show-confirm="!!target"
      :busy="busy"
      :confirm-disabled="!canDelete"
      size="wide"
      scroll-body
      initial-focus="first-field"
      @cancel="cancel"
      @confirm="remove"
    >
      <div ref="content" class="dataset-manager">
        <InlineError v-if="target" :message="error" />
        <template v-else>
          <label class="field">
            <input ref="searchInput" v-model="search" type="search" :aria-label="t('search')" :placeholder="t('search')" />
          </label>
          <p v-if="accepted" class="dataset-manager__status" role="status">{{ t('accepted') }}</p>
          <InlineError :message="loadError" />
          <EmptyState v-if="filteredVersions.length === 0" :title="t(currentVersions.length ? 'noResults' : 'empty')" :description="t(currentVersions.length ? 'noResultsDescription' : 'emptyDescription')" />
          <div v-else class="resource-table dataset-manager__table" :aria-busy="loading">
            <table>
              <thead><tr>
                <th scope="col">{{ t('dataset') }}</th><th scope="col">{{ t('version') }}</th>
                <th scope="col">{{ t('task') }}</th><th scope="col">{{ t('samples') }}</th>
                <th scope="col">{{ t('categories') }}</th><th scope="col">{{ t('actions') }}</th>
              </tr></thead>
              <tbody><tr v-for="version in filteredVersions" :key="version.dataset_version_id">
                <td><strong>{{ version.dataset_id }}</strong></td><td>{{ version.dataset_version_id }}</td>
                <td>{{ version.task_type }}</td><td>{{ version.sample_count }}</td><td>{{ version.category_count }}</td>
                <td><Button v-if="canDelete" variant="danger" size="sm" :disabled="loading" @click="selectTarget(version)">{{ t('remove') }}</Button></td>
              </tr></tbody>
            </table>
          </div>
        </template>
      </div>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '@/app/stores/session.store'
import { submitResourceDeletion } from '@/shared/api/resource-deletion'
import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import type { DatasetVersionRelation } from '../services/dataset.service'
import { datasetManagementMessages } from './dataset-management-messages'

const props = defineProps<{ projectId: string; versions: DatasetVersionRelation[]; loading: boolean; loadError: string | null }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const { t } = useI18n({ messages: datasetManagementMessages })
const session = useSessionStore()
const canDelete = computed(() => !!props.projectId && session.hasScopes(['datasets:write']))
const search = ref('')
const target = ref<DatasetVersionRelation | null>(null)
const error = ref<string | null>(null)
const busy = ref(false)
const accepted = ref(false)
const removedIds = ref(new Set<string>())
const searchInput = ref<HTMLInputElement | null>(null)
const content = ref<HTMLElement | null>(null)
let generation = 0
const currentVersions = computed(() => props.versions.filter(item => item.project_id === props.projectId && !removedIds.value.has(item.dataset_version_id)))
const filteredVersions = computed(() => {
  const query = search.value.trim().toLowerCase()
  return currentVersions.value.filter(item => !query || `${item.dataset_id} ${item.dataset_version_id}`.toLowerCase().includes(query))
})
async function selectTarget(version: DatasetVersionRelation) {
  target.value = version
  error.value = null
  await nextTick()
  content.value?.closest('[role="dialog"]')?.querySelector<HTMLElement>('[data-confirm-cancel]')?.focus()
}
async function cancel() {
  if (busy.value) return
  if (!target.value) { emit('close'); return }
  target.value = null
  error.value = null
  await nextTick()
  searchInput.value?.focus()
}
async function remove() {
  const selected = target.value
  if (!selected || busy.value || !canDelete.value) return
  const epoch = generation
  busy.value = true
  error.value = null
  try {
    await submitResourceDeletion('dataset-version', selected.dataset_version_id, selected.project_id)
    if (epoch !== generation) return
    removedIds.value.add(selected.dataset_version_id)
    target.value = null
    accepted.value = true
    emit('changed')
    await nextTick()
    searchInput.value?.focus()
  } catch (cause) {
    if (epoch === generation) error.value = getErrorMessage(cause)
  } finally {
    if (epoch === generation) busy.value = false
  }
}
watch(() => props.projectId, () => { generation++; emit('close') })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.dataset-manager { display: grid; gap: 16px; min-width: 0; }
.dataset-manager__status { margin: 0; color: var(--am-text-muted); font-size: 13px; }
.dataset-manager__table table { min-width: 660px; width: 100%; table-layout: fixed; }
.dataset-manager__table th, .dataset-manager__table td { padding: 12px 8px; overflow-wrap: anywhere; }
.dataset-manager__table th:nth-child(1), .dataset-manager__table th:nth-child(2) { width: 26%; }
.dataset-manager__table th:nth-child(3) { width: 15%; }
.dataset-manager__table th:last-child { width: 16%; }
.dataset-manager__table td:nth-child(4), .dataset-manager__table td:nth-child(5) { font-variant-numeric: tabular-nums; }
.dataset-manager__table .ui-button { white-space: nowrap; }
</style>
