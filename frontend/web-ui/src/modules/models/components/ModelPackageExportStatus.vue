<template>
  <span class="package-export-status">
    <StatusBadge v-if="part !== 'file'" :label="packageStatus(state, zh)" :tone="packagePending(state) ? 'brand' : undefined" :status="state" with-dot />
    <StatusBadge v-if="part !== 'task' && fileLabel && (part === 'file' || state !== 'expired')" tone="warning" :label="fileLabel" />
    <StatusBadge v-else-if="part === 'file' && canDownloadModelPackage(record)" tone="success" :label="zh ? '可下载' : 'Available'" />
    <span v-else-if="part === 'file'">—</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { canDownloadModelPackage, packageExportFileLabel, packageExportState, packagePending, packageStatus, type ModelPackageRecord } from '../services/model-package.service'

const props = withDefaults(defineProps<{ record: ModelPackageRecord; zh: boolean; part?: 'both' | 'task' | 'file' }>(), { part: 'both' })
const state = computed(() => packageExportState(props.record))
const fileLabel = computed(() => packageExportFileLabel(props.record, props.zh))
</script>

<style scoped>
.package-export-status { display:inline-flex; align-items:center; flex-wrap:wrap; gap:5px; }
</style>
