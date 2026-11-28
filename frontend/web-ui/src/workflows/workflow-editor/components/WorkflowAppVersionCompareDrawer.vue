<template>
  <SideDrawer
    :open="open"
    title="比较"
    close-label="关闭"
    plain
    size="compact"
    :busy="loading"
    @close="emit('close')"
  >
    <div class="cmp-drawer">
      <div class="cmp-selectors">
        <div class="cmp-select-col">
          <span class="cmp-label">左侧版本</span>
          <Select
            floating
            :model-value="sourceVersionId"
            :options="sourceOptions"
            :disabled="loading || sourceOptions.length === 0"
            aria-label="选择左侧版本"
            @update:model-value="(val) => (sourceVersionId = String(val || ''))"
          />
        </div>
        <div class="cmp-arrow" aria-hidden="true">
          <ArrowLeftRight :size="16" />
        </div>
        <div class="cmp-select-col">
          <span class="cmp-label">右侧版本</span>
          <Select
            floating
            :model-value="targetVersionId"
            :options="targetOptions"
            :disabled="loading || targetOptions.length === 0"
            aria-label="选择右侧版本"
            @update:model-value="(val) => (targetVersionId = String(val || 'draft'))"
          />
        </div>
      </div>

      <InlineError :message="errorMessage" />

      <div v-if="loading" class="cmp-loading">正在比较版本差异...</div>

      <template v-else-if="comparison">
        <div class="cmp-summary-bar">
          <span class="cmp-summary-title">接口变更</span>
          <div class="cmp-counts">
            <span class="cmp-count is-add">
              <PlusCircle :size="14" />
              新增 {{ counts.added }}
            </span>
            <span class="cmp-count is-chg">
              <Pencil :size="14" />
              修改 {{ counts.changed }}
            </span>
            <span class="cmp-count is-rem">
              <MinusCircle :size="14" />
              删除 {{ counts.removed }}
            </span>
          </div>
        </div>

        <div v-if="diffRows.length === 0" class="cmp-empty">
          <strong>无接口变化</strong>
          <p>所选两个版本的输入输出定义完全一致。</p>
        </div>

        <section v-else class="cmp-section">
          <h4>接口变化</h4>
          <div class="cmp-table-wrap">
            <table class="cmp-table">
              <thead>
                <tr>
                  <th>类型</th>
                  <th>字段</th>
                  <th>左侧</th>
                  <th>右侧</th>
                  <th>变更类型</th>
                  <th>兼容性</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in diffRows" :key="row.key">
                  <td>{{ row.direction === 'inputs' ? '输入' : '输出' }}</td>
                  <td class="cmp-mono">{{ row.bindingId }}</td>
                  <td class="cmp-muted">{{ row.leftValue }}</td>
                  <td class="cmp-muted">{{ row.rightValue }}</td>
                  <td>
                    <span class="cmp-kind-pill" :class="`is-${row.kind}`">
                      {{ row.kindLabel }}
                    </span>
                  </td>
                  <td>
                    <span class="cmp-compat-pill" :class="row.breaking ? 'is-bad' : 'is-ok'">
                      {{ row.breaking ? '不兼容' : '兼容' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>

    <template #footer>
      <Button variant="secondary" @click="emit('close')">关闭</Button>
      <Button
        v-if="viewableVersionId"
        variant="primary"
        @click="emit('view-version', viewableVersionId)"
      >
        查看版本
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { ArrowLeftRight, MinusCircle, Pencil, PlusCircle } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  compareWorkflowAppVersionToDraft,
  getWorkflowAppVersion,
} from '../services/workflow-application.service'
import type {
  WorkflowAppVersion,
  WorkflowAppVersionComparison,
  WorkflowJsonObject,
} from '../types'

interface DiffRow {
  key: string
  direction: 'inputs' | 'outputs'
  bindingId: string
  leftValue: string
  rightValue: string
  kind: 'added' | 'removed' | 'changed' | 'required'
  kindLabel: string
  breaking: boolean
}

const props = defineProps<{
  open: boolean
  projectId: string
  applicationId: string
  versions: WorkflowAppVersion[]
  initialSourceVersionId: string | null
  initialTargetVersionId?: string | null
}>()

const emit = defineEmits<{
  close: []
  'view-version': [workflowAppVersionId: string]
}>()

const sourceVersionId = ref('')
const targetVersionId = ref('draft')
const loading = ref(false)
const errorMessage = ref('')
const comparison = ref<WorkflowAppVersionComparison | null>(null)

const sourceOptions = computed(() =>
  props.versions.map((ver) => ({
    value: ver.workflow_app_version_id,
    label: `${ver.display_version}${ver.state === 'archived' ? ' (已归档)' : ''}`,
  })),
)

const targetOptions = computed(() => [
  { value: 'draft', label: '当前草稿' },
  ...props.versions.map((ver) => ({
    value: ver.workflow_app_version_id,
    label: `${ver.display_version}${ver.state === 'archived' ? ' (已归档)' : ''}`,
  })),
])

const viewableVersionId = computed(() => {
  if (targetVersionId.value && targetVersionId.value !== 'draft') {
    return targetVersionId.value
  }
  return sourceVersionId.value || null
})

function indexContractItems(items: unknown): Record<string, WorkflowJsonObject> {
  if (!Array.isArray(items)) return {}
  const map: Record<string, WorkflowJsonObject> = {}
  for (const item of items) {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      const obj = item as WorkflowJsonObject
      const bindingId = obj.binding_id
      if (typeof bindingId === 'string' && bindingId) {
        map[bindingId] = obj
      }
    }
  }
  return map
}

function stableEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

function computeLocalContractDiff(
  sourceContract: WorkflowJsonObject,
  targetContract: WorkflowJsonObject,
  sourceFingerprint: string,
  targetFingerprint: string,
): WorkflowAppVersionComparison {
  const changes: WorkflowJsonObject[] = []
  const breakingChanges: WorkflowJsonObject[] = []

  for (const direction of ['inputs', 'outputs'] as const) {
    const sourceItems = indexContractItems(sourceContract[direction])
    const targetItems = indexContractItems(targetContract[direction])
    const sourceKeys = Object.keys(sourceItems).sort()
    const targetKeys = Object.keys(targetItems).sort()

    for (const key of sourceKeys) {
      if (!(key in targetItems)) {
        const src = sourceItems[key]
        breakingChanges.push({
          kind: 'removed',
          direction,
          binding_id: key,
          from: src.payload_type_id ?? null,
          to: null,
        })
      }
    }
    for (const key of targetKeys) {
      if (!(key in sourceItems)) {
        const item = targetItems[key]
        const change: WorkflowJsonObject = {
          kind: 'added',
          direction,
          binding_id: key,
          from: null,
          to: item.payload_type_id ?? null,
        }
        if (direction === 'inputs' && item.required !== false) {
          breakingChanges.push(change)
        } else {
          changes.push(change)
        }
      }
    }
    const compareFields = [
      'payload_type_id',
      'binding_kind',
      'template_port_id',
      'config',
      ...(direction === 'inputs'
        ? [
            'payload_schema',
            'request_schema',
            'allowed_media_types',
            'max_inline_bytes',
            'max_file_bytes',
            'max_files',
            'transports',
            'charset',
          ]
        : ['json_schema']),
    ]
    for (const key of sourceKeys) {
      if (!(key in targetItems)) continue
      const src = sourceItems[key]
      const tgt = targetItems[key]
      for (const field of compareFields) {
        if (!stableEqual(src[field], tgt[field])) {
          breakingChanges.push({
            kind: 'changed',
            direction,
            binding_id: key,
            field,
            from: src[field] ?? null,
            to: tgt[field] ?? null,
          })
        }
      }
      const srcRequired = src.required !== false
      const tgtRequired = tgt.required !== false
      if (srcRequired !== tgtRequired) {
        if (direction === 'inputs' && !srcRequired && tgtRequired) {
          breakingChanges.push({
            kind: 'required',
            direction,
            binding_id: key,
            from: src.payload_type_id ?? '可选',
            to: tgt.payload_type_id ?? '必填',
          })
        } else if (direction === 'outputs') {
          breakingChanges.push({
            kind: 'changed',
            direction,
            binding_id: key,
            field: 'required',
            from: srcRequired ? '必填' : '可选',
            to: tgtRequired ? '必填' : '可选',
          })
        } else {
          changes.push({
            kind: 'changed',
            direction,
            binding_id: key,
            field: 'required',
            from: srcRequired ? '必填' : '可选',
            to: tgtRequired ? '必填' : '可选',
          })
        }
      }
    }
  }

  return {
    compatible: breakingChanges.length === 0,
    changes,
    breaking_changes: breakingChanges,
    source_contract_fingerprint: sourceFingerprint,
    target_contract_fingerprint: targetFingerprint,
  }
}

async function runCompare() {
  if (!props.open || !sourceVersionId.value || !props.projectId || !props.applicationId) {
    comparison.value = null
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    if (targetVersionId.value === 'draft' || !targetVersionId.value) {
      comparison.value = await compareWorkflowAppVersionToDraft(
        props.projectId,
        props.applicationId,
        sourceVersionId.value,
      )
    } else if (targetVersionId.value === sourceVersionId.value) {
      comparison.value = {
        compatible: true,
        changes: [],
        breaking_changes: [],
        source_contract_fingerprint: '',
        target_contract_fingerprint: '',
      }
    } else {
      const [sourceDetail, targetDetail] = await Promise.all([
        getWorkflowAppVersion(props.projectId, props.applicationId, sourceVersionId.value),
        getWorkflowAppVersion(props.projectId, props.applicationId, targetVersionId.value),
      ])
      comparison.value = computeLocalContractDiff(
        sourceDetail.contract,
        targetDetail.contract,
        sourceDetail.contract_fingerprint,
        targetDetail.contract_fingerprint,
      )
    }
  } catch (error) {
    comparison.value = null
    errorMessage.value = error instanceof Error ? error.message : '加载版本对比结果失败。'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.initialSourceVersionId, props.initialTargetVersionId] as const,
  ([isOpen, initSource, initTarget]) => {
    if (!isOpen) return
    sourceVersionId.value = initSource || props.versions[0]?.workflow_app_version_id || ''
    targetVersionId.value = initTarget || 'draft'
    void runCompare()
  },
  { immediate: true },
)

watch(
  () => [sourceVersionId.value, targetVersionId.value] as const,
  () => {
    if (props.open) {
      void runCompare()
    }
  },
)

function formatCompactValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value).replace(/\.v\d+$/, '')
  }
  const serialized = JSON.stringify(value)
  return serialized.length > 26 ? `${serialized.slice(0, 23)}...` : serialized
}

function buildRow(item: WorkflowJsonObject, breaking: boolean, index: number): DiffRow {
  const direction = item.direction === 'outputs' ? 'outputs' : 'inputs'
  const bindingId = typeof item.binding_id === 'string' ? item.binding_id : '—'
  const rawKind = typeof item.kind === 'string' ? item.kind : 'changed'
  const kind: DiffRow['kind'] =
    rawKind === 'added' || rawKind === 'removed' || rawKind === 'required' ? rawKind : 'changed'

  let leftValue = '—'
  let rightValue = '—'
  let kindLabel = '修改'

  if (kind === 'added') {
    kindLabel = '新增'
    rightValue = item.to !== undefined ? formatCompactValue(item.to) : '新增'
  } else if (kind === 'removed') {
    kindLabel = '删除'
    leftValue = item.from !== undefined ? formatCompactValue(item.from) : '已定义'
  } else if (kind === 'required') {
    kindLabel = '可选改必填'
    leftValue = item.from !== undefined ? formatCompactValue(item.from) : '可选'
    rightValue = item.to !== undefined ? formatCompactValue(item.to) : '必填'
  } else {
    leftValue = formatCompactValue(item.from)
    rightValue = formatCompactValue(item.to)
  }

  return {
    key: `${breaking ? 'b' : 'c'}-${index}-${direction}-${bindingId}-${kind}`,
    direction,
    bindingId,
    leftValue,
    rightValue,
    kind,
    kindLabel,
    breaking,
  }
}

const diffRows = computed<DiffRow[]>(() => {
  if (!comparison.value) return []
  const breaking = (comparison.value.breaking_changes || []).map((item, idx) =>
    buildRow(item, true, idx),
  )
  const compatible = (comparison.value.changes || []).map((item, idx) =>
    buildRow(item, false, idx),
  )
  return [...breaking, ...compatible]
})

const counts = computed(() => {
  let added = 0
  let changed = 0
  let removed = 0
  for (const row of diffRows.value) {
    if (row.kind === 'added') added += 1
    else if (row.kind === 'removed') removed += 1
    else changed += 1
  }
  return { added, changed, removed }
})
</script>

<style scoped>
.cmp-drawer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cmp-selectors {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: end;
  gap: 10px;
}

.cmp-select-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.cmp-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--am-text-muted);
}

.cmp-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  color: var(--am-text-muted);
}

.cmp-loading {
  padding: 28px 16px;
  text-align: center;
  font-size: 13px;
  color: var(--am-text-muted);
}

.cmp-summary-bar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 16px;
  padding: 12px 14px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
}

.cmp-summary-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.cmp-counts {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 13px;
  font-weight: 600;
}

.cmp-count {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.cmp-count.is-add {
  color: var(--am-action-primary);
}

.cmp-count.is-chg {
  color: #d97706;
}

.cmp-count.is-rem {
  color: #dc2626;
}

.cmp-empty {
  padding: 28px 16px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface-soft);
  text-align: center;
}

.cmp-empty strong {
  display: block;
  font-size: 14px;
  color: var(--am-text-strong);
  margin-bottom: 4px;
}

.cmp-empty p {
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

.cmp-section {
  display: grid;
  gap: 10px;
}

.cmp-section h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.cmp-table-wrap {
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow-x: auto;
  background: var(--am-surface);
}

.cmp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.cmp-table th {
  text-align: left;
  padding: 10px 10px;
  font-weight: 600;
  color: var(--am-text);
  background: var(--am-table-header, var(--am-surface));
  border-bottom: 1px solid var(--am-border);
  white-space: nowrap;
}

.cmp-table td {
  padding: 10px 10px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
  vertical-align: middle;
}

.cmp-table tr:last-child td {
  border-bottom: none;
}

.cmp-mono {
  font-family: var(--am-font-mono, ui-monospace, monospace);
  word-break: break-all;
}

.cmp-muted {
  color: var(--am-text-muted);
}

.cmp-kind-pill,
.cmp-compat-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.cmp-kind-pill.is-added,
.cmp-compat-pill.is-ok {
  background: var(--am-row-selected);
  color: var(--am-action-primary);
}

.cmp-kind-pill.is-changed,
.cmp-kind-pill.is-required {
  background: rgba(245, 158, 11, 0.14);
  color: #d97706;
}

.cmp-kind-pill.is-removed,
.cmp-compat-pill.is-bad {
  background: rgba(220, 38, 38, 0.12);
  color: #dc2626;
}
</style>
