<template>
  <InlineError :message="error" />
  <section v-if="operations.length" class="resource-cleanup" aria-live="polite">
    <h2>{{ t('pending') }}</h2>
    <div v-for="operation in operations" :key="operation.operation_id" class="resource-cleanup__row">
      <div><strong>{{ operation.resource_id }}</strong><p>{{ operation.error ? t('failed') : operation.state === 'prepared' ? t('prepared') : t('running') }}</p><InlineError :message="operation.error" /></div>
      <Button v-if="operation.state === 'committed'" size="sm" :loading="retrying === operation.operation_id" :disabled="!!retrying" @click="retry(operation.operation_id)">{{ t('retry') }}</Button>
    </div>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { deletionRevision, listResourceDeletions, retryResourceDeletion, type DeletionStatus } from '@/shared/api/resource-deletion'
import { getErrorMessage } from '@/shared/api/error'
import Button from './Button.vue'
import InlineError from '../feedback/InlineError.vue'
import { resourceDeletionMessages } from './resource-deletion-messages'
const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ settled: [] }>()
const { t } = useI18n({ messages: resourceDeletionMessages })
const operations = ref<DeletionStatus[]>([])
const error = ref<string | null>(null)
const retrying = ref<string | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
let disposed = false
let epoch = 0
let projectGeneration = 0
async function load() {
  const currentEpoch = ++epoch
  clearTimeout(timer)
  controller?.abort()
  controller = new AbortController()
  if (!props.projectId || disposed) { operations.value = []; return }
  try {
    const next = await listResourceDeletions(props.projectId, controller.signal)
    if (currentEpoch !== epoch || disposed) return
    const previousIds = new Set(operations.value.map(item => item.operation_id))
    operations.value = next
    error.value = null
    if ([...previousIds].some(id => !next.some(item => item.operation_id === id))) emit('settled')
  } catch (cause) {
    if (currentEpoch === epoch && !controller.signal.aborted && !disposed) error.value = getErrorMessage(cause)
  } finally {
    if (currentEpoch === epoch && !disposed) timer = setTimeout(() => { void load() }, 2500)
  }
}
async function retry(id: string) {
  if (retrying.value) return
  const current = projectGeneration
  const isCurrent = () => current === projectGeneration && !disposed
  retrying.value = id
  try { await retryResourceDeletion(id); if (isCurrent()) await load() }
  catch (cause) { if (isCurrent()) error.value = getErrorMessage(cause) }
  finally { if (isCurrent()) retrying.value = null }
}
watch(() => props.projectId, () => { projectGeneration++; retrying.value = null; operations.value = []; error.value = null; void load() }, { immediate: true })
watch(deletionRevision, () => { void load() })
onBeforeUnmount(() => { disposed = true; epoch++; controller?.abort(); clearTimeout(timer) })
</script>
<style scoped>
.resource-cleanup { padding: 16px; border: 1px solid var(--am-border); border-radius: 12px; }
.resource-cleanup h2 { margin: 0 0 12px; font-size: 15px; }
.resource-cleanup__row { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 10px 0; }
.resource-cleanup__row > div { min-width: 0; overflow-wrap: anywhere; }
.resource-cleanup__row p { margin: 5px 0; font-size: 13px; color: var(--am-text-muted); }
</style>
