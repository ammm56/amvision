<template>
  <section class="page-stack">
    <PageHeader :title="datasetExportId">
      <template #actions>
        <ButtonLink to="/datasets">
          <ArrowLeft :size="16" />
          {{ t('datasetExportDetail.actions.backToDatasets') }}
        </ButtonLink>
        <ButtonLink
          v-if="detail?.task_id"
          :to="`/tasks/${detail.task_id}`"
        >
          <Activity :size="16" />
          {{ t('datasetExportDetail.actions.taskStatus') }}
        </ButtonLink>
        <Button
          v-if="detail"
          variant="secondary"
          :disabled="packaging || !canWriteDatasets"
          :loading="packaging"
          @click="packageCurrentExport"
        >
          <PackageCheck :size="16" />
          {{ t('datasetExportDetail.actions.package') }}
        </Button>
        <Button
          v-if="detail"
          variant="secondary"
          :disabled="!detail.package_object_key || downloading"
          :loading="downloading"
          @click="downloadCurrentExport"
        >
          <Download :size="16" />
          {{ t('datasetExportDetail.actions.download') }}
        </Button>
        <Button
          v-if="detail"
          variant="danger"
          :disabled="!canDeleteCurrentExport || deleting"
          :loading="deleting"
          @click="deleteDialogOpen = true"
        >
          <Trash2 :size="16" />
          {{ t('datasetExportDetail.actions.delete') }}
        </Button>
        <Button variant="secondary" :disabled="loading" :loading="loading" @click="loadDetail">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="errorMessage" />

    <section v-if="detail" class="resource-section">
      <div class="section-heading">
        <div>
          <h2>{{ t('datasetExportDetail.summaryTitle') }}</h2>
        </div>
        <TaskStateBadge :state="detail.status" />
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('datasetExportDetail.fields.projectId') }}</span>
          <strong>{{ detail.project_id }}</strong>
        </div>
        <div>
          <span>{{ t('datasetExportDetail.fields.datasetId') }}</span>
          <strong>{{ detail.dataset_id }}</strong>
        </div>
        <div>
          <span>{{ t('datasetExportDetail.fields.datasetVersionId') }}</span>
          <strong>{{ detail.dataset_version_id }}</strong>
        </div>
        <div>
          <span>{{ t('datasetExportDetail.fields.taskType') }}</span>
          <strong>{{ detail.task_type }}</strong>
        </div>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('datasetExportDetail.fields.exportFormat') }}</span>
          <strong>{{ detail.format_id }}</strong>
        </div>
        <div>
          <span>{{ t('datasetExportDetail.fields.sampleCount') }}</span>
          <strong>{{ detail.sample_count }}</strong>
        </div>
        <div>
          <span>{{ t('datasetExportDetail.fields.includeTestSplit') }}</span>
          <strong>{{ detail.include_test_split ? t('datasetExportDetail.values.yes') : t('datasetExportDetail.values.no') }}</strong>
        </div>
        <div>
          <span>{{ t('datasetExportDetail.fields.createdAt') }}</span>
          <strong>{{ formatSystemDateTime(detail.created_at) }}</strong>
        </div>
      </div>
      <InlineError :message="detail.error_message ?? null" />
    </section>

    <section v-if="detail" class="operation-grid">
      <article class="resource-section">
        <div>
          <h2>{{ t('datasetExportDetail.packageTitle') }}</h2>
        </div>
        <div class="summary-list">
          <div>
            <span>{{ t('datasetExportDetail.fields.fileName') }}</span>
            <strong>{{ detail.package_file_name || '-' }}</strong>
          </div>
          <div>
            <span>{{ t('datasetExportDetail.fields.fileObjectKey') }}</span>
            <strong>{{ detail.package_object_key || '-' }}</strong>
          </div>
          <div>
            <span>{{ t('datasetExportDetail.fields.fileSize') }}</span>
            <strong>{{ detail.package_size ?? '-' }}</strong>
          </div>
          <div>
            <span>{{ t('datasetExportDetail.fields.packagedAt') }}</span>
            <strong>{{ detail.packaged_at ? formatSystemDateTime(detail.packaged_at) : '-' }}</strong>
          </div>
        </div>
      </article>

      <article class="resource-section">
        <div>
          <h2>{{ t('datasetExportDetail.runtimeDataTitle') }}</h2>
        </div>
        <div class="summary-list">
          <div>
            <span>{{ t('datasetExportDetail.fields.exportPath') }}</span>
            <strong>{{ detail.export_path || '-' }}</strong>
          </div>
          <div>
            <span>{{ t('datasetExportDetail.fields.manifest') }}</span>
            <strong>{{ detail.manifest_object_key || '-' }}</strong>
          </div>
          <div>
            <span>{{ t('datasetExportDetail.fields.queueTask') }}</span>
            <strong>{{ detail.queue_task_id || '-' }}</strong>
          </div>
          <div>
            <span>{{ t('datasetExportDetail.fields.task') }}</span>
            <RouterLink v-if="detail.task_id" :to="`/tasks/${detail.task_id}`">{{ detail.task_id }}</RouterLink>
            <strong v-else>-</strong>
          </div>
        </div>
      </article>

      <article class="resource-section">
        <div>
          <h2>{{ t('datasetExportDetail.splitListTitle') }}</h2>
        </div>
        <pre class="json-view">{{ splitNamesJson }}</pre>
      </article>

      <article class="resource-section">
        <div>
          <h2>{{ t('datasetExportDetail.categoryListTitle') }}</h2>
        </div>
        <pre class="json-view">{{ categoryNamesJson }}</pre>
      </article>

      <article class="resource-section">
        <div>
          <h2>{{ t('datasetExportDetail.metadataTitle') }}</h2>
        </div>
        <pre class="json-view">{{ metadataJson }}</pre>
      </article>
    </section>

    <ConfirmDialog
      v-if="detail && deleteDialogOpen"
      :title="t('datasetOps.deleteDialog.exportTitle')"
      :message="t('common.confirmDelete')"
      :details="deleteDialogDetails"
      :confirm-label="t('datasetOps.deleteDialog.exportTitle')"
      :cancel-label="t('common.cancel')"
      :busy="deleting"
      confirm-variant="danger"
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentExport"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, ArrowLeft, Download, PackageCheck, RefreshCw, Trash2 } from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  deleteDatasetExport,
  downloadDatasetExport,
  getDatasetExportDetail,
  packageDatasetExport,
  type DatasetExportDetail,
} from '../services/dataset.service'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const { t } = useI18n()

const detail = ref<DatasetExportDetail | null>(null)
const loading = ref(false)
const packaging = ref(false)
const downloading = ref(false)
const deleting = ref(false)
const deleteDialogOpen = ref(false)
const errorMessage = ref<string | null>(null)

const datasetExportId = computed(() => String(route.params.datasetExportId ?? ''))
const canWriteDatasets = computed(() => sessionStore.hasScopes(['datasets:write']))
const canDeleteCurrentExport = computed(() => {
  if (!detail.value || !canWriteDatasets.value) return false
  const normalized = String(detail.value.status || '').toLowerCase()
  return normalized === 'completed' || normalized === 'failed'
})
const deleteDialogDetails = computed(() => {
  if (!detail.value) return ''
  return t('datasetOps.messages.confirmDeleteExport')
    .replace('{datasetVersionId}', detail.value.dataset_version_id)
})
const splitNamesJson = computed(() => JSON.stringify(detail.value?.split_names ?? [], null, 2))
const categoryNamesJson = computed(() => JSON.stringify(detail.value?.category_names ?? [], null, 2))
const metadataJson = computed(() => JSON.stringify(detail.value?.metadata ?? {}, null, 2))

onMounted(() => {
  void loadDetail()
})

async function loadDetail(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    detail.value = await getDatasetExportDetail(datasetExportId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetExportDetail.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function packageCurrentExport(): Promise<void> {
  if (!detail.value || !canWriteDatasets.value) return

  packaging.value = true
  errorMessage.value = null
  try {
    const packageResult = await packageDatasetExport(detail.value.dataset_export_id)
    detail.value = { ...detail.value, ...packageResult }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetExportDetail.messages.packageFailed')
  } finally {
    packaging.value = false
  }
}

async function downloadCurrentExport(): Promise<void> {
  if (!detail.value?.package_object_key) return

  downloading.value = true
  errorMessage.value = null
  try {
    const blob = await downloadDatasetExport(detail.value.dataset_export_id)
    const objectUrl = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = detail.value.package_file_name || `${detail.value.dataset_export_id}.zip`
    anchor.click()
    window.URL.revokeObjectURL(objectUrl)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetExportDetail.messages.downloadFailed')
  } finally {
    downloading.value = false
  }
}

async function deleteCurrentExport(): Promise<void> {
  if (!detail.value || !canDeleteCurrentExport.value) return

  deleting.value = true
  errorMessage.value = null
  try {
    await deleteDatasetExport(detail.value.dataset_export_id)
    await router.push('/datasets')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetExportDetail.messages.deleteFailed')
  } finally {
    deleting.value = false
    deleteDialogOpen.value = false
  }
}
</script>

<style scoped>
.summary-list {
  display: grid;
  gap: 12px;
}

.summary-list > div {
  display: grid;
  gap: 4px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--am-border);
}

.summary-list span {
  color: var(--am-text-muted);
  font-weight: 700;
  font-size: 0.86rem;
}

.summary-list strong {
  overflow-wrap: anywhere;
}
</style>
