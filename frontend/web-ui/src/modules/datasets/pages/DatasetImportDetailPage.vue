<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('datasetImportDetail.kicker') }}</p>
        <h1>{{ datasetImportId }}</h1>
        <p class="page-description">{{ t('datasetImportDetail.description') }}</p>
      </div>
      <div class="page-actions">
        <ButtonLink to="/datasets">
          <ArrowLeft :size="16" />
          {{ t('datasetImportDetail.actions.backToDatasets') }}
        </ButtonLink>
        <ButtonLink
          v-if="detail?.task_id"
          :to="`/tasks/${detail.task_id}`"
        >
          <Activity :size="16" />
          任务状态
        </ButtonLink>
        <Button
          v-if="detail"
          variant="danger"
          :disabled="!canDeleteCurrentImport || deleting"
          @click="deleteDialogOpen = true"
        >
          <Trash2 :size="16" />
          {{ t('datasetImportDetail.actions.delete') }}
        </Button>
        <Button variant="secondary" :disabled="loading" @click="loadDetail">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section v-if="detail" class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('datasetImportDetail.summaryKicker') }}</p>
          <h2>{{ t('datasetImportDetail.summaryTitle') }}</h2>
        </div>
        <StatusBadge :tone="statusTone(detail.processing_state || detail.status)">{{ detail.processing_state || detail.status }}</StatusBadge>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('datasetImportDetail.fields.projectId') }}</span>
          <strong>{{ detail.project_id }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.datasetId') }}</span>
          <strong>{{ detail.dataset_id }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.datasetVersionId') }}</span>
          <strong>{{ detail.dataset_version_id || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.validationStatus') }}</span>
          <strong>{{ detail.validation_status || '-' }}</strong>
        </div>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('datasetImportDetail.fields.formatType') }}</span>
          <strong>{{ detail.format_type || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.splitStrategy') }}</span>
          <strong>{{ detail.split_strategy || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.packageSize') }}</span>
          <strong>{{ detail.package_size ?? '-' }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.createdAt') }}</span>
          <strong>{{ formatSystemDateTime(detail.created_at) }}</strong>
        </div>
      </div>
      <InlineError :message="detail.error_message ?? null" />
    </section>

    <section v-if="detail" class="operation-grid">
      <article class="resource-section">
        <div>
          <p class="page-kicker">{{ t('datasetImportDetail.validationKicker') }}</p>
          <h2>{{ t('datasetImportDetail.validationTitle') }}</h2>
        </div>
        <pre class="json-view">{{ validationReportJson }}</pre>
      </article>
      <article class="resource-section">
        <div>
          <p class="page-kicker">{{ t('datasetImportDetail.detectedKicker') }}</p>
          <h2>{{ t('datasetImportDetail.detectedTitle') }}</h2>
        </div>
        <pre class="json-view">{{ detectedProfileJson }}</pre>
      </article>
      <article class="resource-section">
        <div>
          <p class="page-kicker">{{ t('datasetImportDetail.classMapKicker') }}</p>
          <h2>{{ t('datasetImportDetail.classMapTitle') }}</h2>
        </div>
        <pre class="json-view">{{ classMapJson }}</pre>
      </article>
      <article class="resource-section">
        <div>
          <p class="page-kicker">{{ t('datasetImportDetail.metadataKicker') }}</p>
          <h2>{{ t('datasetImportDetail.metadataTitle') }}</h2>
        </div>
        <pre class="json-view">{{ metadataJson }}</pre>
      </article>
    </section>

    <section v-if="detail?.dataset_version" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('datasetImportDetail.versionKicker') }}</p>
        <h2>{{ t('datasetImportDetail.versionTitle') }}</h2>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('datasetImportDetail.fields.taskType') }}</span>
          <strong>{{ detail.dataset_version.task_type }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.sampleCount') }}</span>
          <strong>{{ detail.dataset_version.sample_count }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.categoryCount') }}</span>
          <strong>{{ detail.dataset_version.category_count }}</strong>
        </div>
        <div>
          <span>{{ t('datasetImportDetail.fields.splits') }}</span>
          <strong>{{ detail.dataset_version.split_names.join(', ') || '-' }}</strong>
        </div>
      </div>
    </section>

    <ConfirmDialog
      v-if="detail && deleteDialogOpen"
      :kicker="t('datasetImportDetail.deleteDialog.kicker')"
      :title="t('datasetImportDetail.deleteDialog.title')"
      :message="deleteDialogMessage"
      :confirm-label="t('datasetImportDetail.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="deleting"
      confirm-variant="danger"
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentImport"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, ArrowLeft, RefreshCw, Trash2 } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { deleteDatasetImport, getDatasetImportDetail, type DatasetImportDetail } from '../services/dataset.service'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const { t } = useI18n()

const detail = ref<DatasetImportDetail | null>(null)
const loading = ref(false)
const deleting = ref(false)
const deleteDialogOpen = ref(false)
const errorMessage = ref<string | null>(null)

const datasetImportId = computed(() => String(route.params.datasetImportId ?? ''))
const canWriteDatasets = computed(() => sessionStore.hasScopes(['datasets:write']))
const canDeleteCurrentImport = computed(() => {
  if (!detail.value || !canWriteDatasets.value) return false
  const normalized = String(detail.value.processing_state || detail.value.status || '').toLowerCase()
  return normalized === 'completed' || normalized === 'failed'
})
const deleteDialogMessage = computed(() => {
  if (!detail.value) return ''
  return t('datasetImportDetail.messages.confirmDelete')
    .replace('{datasetImportId}', detail.value.dataset_import_id)
    .replace('{datasetVersionId}', detail.value.dataset_version_id || '-')
})
const validationReportJson = computed(() => JSON.stringify(detail.value?.validation_report ?? {}, null, 2))
const detectedProfileJson = computed(() => JSON.stringify(detail.value?.detected_profile ?? {}, null, 2))
const classMapJson = computed(() => JSON.stringify(detail.value?.class_map ?? {}, null, 2))
const metadataJson = computed(() => JSON.stringify(detail.value?.metadata ?? {}, null, 2))

onMounted(() => {
  void loadDetail()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('received') || normalized.includes('pending')) return 'warning'
  if (normalized.includes('valid') || normalized.includes('process')) return 'info'
  return 'neutral'
}

async function loadDetail(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    detail.value = await getDatasetImportDetail(datasetImportId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetImportDetail.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function deleteCurrentImport(): Promise<void> {
  if (!detail.value || !canDeleteCurrentImport.value) return

  deleting.value = true
  errorMessage.value = null
  try {
    await deleteDatasetImport(detail.value.dataset_import_id)
    await router.push('/datasets')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetImportDetail.messages.deleteFailed')
  } finally {
    deleting.value = false
    deleteDialogOpen.value = false
  }
}
</script>
