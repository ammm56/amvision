<template>
  <Button size="sm" variant="secondary" data-deployment-action="export" :disabled="disabled" :loading="requesting || active" @click="start">
    {{ active ? transferStateLabel(operation!.state) : tr('export') }}
  </Button>
  <Button v-if="operation?.state === 'completed' && !requesting" size="sm" variant="secondary" data-deployment-action="download" :loading="downloading" @click="download">{{ tr('download') }}</Button>
  <span v-if="active" class="deployment-export-status" role="status">{{ operation?.progress_bytes ? bytes(operation.progress_bytes) : tr('preparing') }}</span>
  <span v-if="error || operation?.error" class="deployment-export-error" role="alert">{{ error || operation?.error }}</span>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Button from '@/shared/ui/components/Button.vue'
import { translate } from '@/platform/i18n'
import { downloadTransfer, exportDeployment, transferIsActive, transferStateLabel, type DeploymentTransfer } from '../services/deployment-transfer.service'

const props = defineProps<{ projectId: string; deploymentId: string; operation?: DeploymentTransfer; disabled?: boolean }>()
const emit = defineEmits<{ updated: [item: DeploymentTransfer] }>()
const tr = (key: string) => translate(`deploymentTransfer.${key}`)
const requesting = ref(false)
const downloading = ref(false)
const error = ref('')
const active = computed(() => !!props.operation && transferIsActive(props.operation.state))
const bytes = (value: number) => `${(value / 1024 / 1024).toFixed(1)} MB`

async function start() {
  if (requesting.value || active.value || props.disabled) return
  requesting.value = true; error.value = ''
  try { emit('updated', await exportDeployment(props.projectId, props.deploymentId)) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { requesting.value = false }
}
async function download() {
  if (!props.operation || downloading.value) return
  downloading.value = true; error.value = ''
  try { await downloadTransfer(props.projectId, props.operation) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { downloading.value = false }
}
</script>

<style scoped>
.deployment-export-status { font-size: 12px; color: var(--am-text-muted); }
.deployment-export-error { flex-basis: 100%; font-size: 12px; color: var(--am-danger-text); overflow-wrap: anywhere; }
</style>
