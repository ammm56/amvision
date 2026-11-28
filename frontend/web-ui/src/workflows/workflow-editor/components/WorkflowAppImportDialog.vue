<template>
  <SideDrawer
    :open="open"
    title="导入"
    close-label="关闭"
    plain
    size="compact"
    :busy="busy"
    @close="emit('close')"
  >
    <div class="app-import-body">
      <section class="app-import-section">
        <div v-if="selectedFileName" class="app-import-file-chip">
          <div class="app-import-file-chip__left">
            <FileJson :size="16" />
            <span :title="selectedFileName">{{ selectedFileName }}</span>
          </div>
          <button type="button" class="app-import-clear" aria-label="清除文件" :disabled="busy" @click="clearFile">
            <X :size="14" />
          </button>
        </div>

        <label
          v-else
          class="app-import-drop"
          :class="{ 'is-dragover': isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="handleFileDrop"
        >
          <span class="app-import-drop__icon">
            <Upload :size="20" />
          </span>
          <strong>点击或拖入 JSON 文件</strong>
          <small>.json</small>
          <input type="file" accept=".json,application/json" hidden @change="handleFileSelect" />
        </label>
      </section>

      <section v-if="parsedApp" class="app-import-section">
        <label class="app-import-field">
          <span>应用名称 <em>*</em></span>
          <input
            v-model="draftDisplayName"
            type="text"
            maxlength="120"
            placeholder="请输入应用名称"
            :disabled="busy"
          />
        </label>
        <label class="app-import-field">
          <span>应用 ID <em>*</em></span>
          <input
            v-model="draftApplicationId"
            type="text"
            maxlength="120"
            placeholder="例如 workflow-app-imported"
            :disabled="busy"
          />
        </label>
      </section>

      <section v-if="parsedApp || parseError" class="app-import-section">
        <div v-if="checking" class="app-import-note">正在检查依赖...</div>
        <InlineError v-else-if="parseError" :message="parseError" />
        <template v-else>
          <div v-if="dependencyIssues.length > 0" class="app-import-warn">
            <AlertTriangle :size="15" />
            <span>缺少 {{ dependencyIssues.length }} 项依赖</span>
          </div>
          <div v-else class="app-import-ok">
            <CheckCircle2 :size="15" />
            <span>依赖校验通过</span>
          </div>

          <div v-if="dependencyRows.length > 0" class="app-dep-table-wrap">
            <table class="app-dep-table">
              <thead>
                <tr>
                  <th>依赖项</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="dep in dependencyRows" :key="dep.key">
                  <td>
                    <small class="app-dep-kind">{{ dep.kindLabel }}</small>
                    <strong>{{ dep.name }}</strong>
                  </td>
                  <td>
                    <span class="app-dep-status" :class="dep.ok ? 'is-ok' : 'is-bad'">
                      <i class="app-dep-dot" />
                      {{ dep.statusText }}
                    </span>
                  </td>
                  <td>
                    <RouterLink v-if="!dep.ok && dep.route" :to="dep.route" class="app-dep-link">
                      {{ dep.actionLabel }}
                    </RouterLink>
                    <span v-else class="app-dep-dash">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>

      <InlineError :message="submitError" />
    </div>

    <template #footer>
      <Button variant="secondary" :disabled="busy" @click="emit('close')">取消</Button>
      <Button
        variant="primary"
        :disabled="!canSubmit"
        :loading="busy"
        data-app-import-submit
        @click="submitImport"
      >
        导入
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { AlertTriangle, CheckCircle2, FileJson, Upload, X } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { parseWorkflowAppDocumentV1 } from '../documents/workflow-app-document'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { saveWorkflowApplication, validateWorkflowApplication } from '../services/workflow-application.service'
import type {
  FlowApplication,
  WorkflowApplicationBundleSaveDocument,
  WorkflowApplicationDocument,
  WorkflowGraphTemplate,
} from '../types'

interface DependencyRow {
  key: string
  kindLabel: string
  name: string
  ok: boolean
  statusText: string
  route?: string
  actionLabel?: string
}

const props = defineProps<{
  open: boolean
  projectId: string
}>()

const emit = defineEmits<{
  close: []
  imported: [doc: WorkflowApplicationDocument | WorkflowApplicationBundleSaveDocument]
}>()

const selectedFileName = ref('')
const isDragging = ref(false)
const parsedApp = ref<FlowApplication | null>(null)
const parsedTemplate = ref<WorkflowGraphTemplate | null>(null)
const draftDisplayName = ref('')
const draftApplicationId = ref('')
const checking = ref(false)
const busy = ref(false)
const parseError = ref<string | null>(null)
const submitError = ref<string | null>(null)
const dependencyRows = ref<DependencyRow[]>([])

const dependencyIssues = computed(() => dependencyRows.value.filter((row) => !row.ok))
const canSubmit = computed(
  () =>
    Boolean(
      parsedApp.value &&
        draftDisplayName.value.trim() &&
        draftApplicationId.value.trim() &&
        !checking.value &&
        !parseError.value &&
        dependencyIssues.value.length === 0 &&
        !busy.value,
    ),
)

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) clearFile()
  },
)

function clearFile(): void {
  selectedFileName.value = ''
  isDragging.value = false
  parsedApp.value = null
  parsedTemplate.value = null
  draftDisplayName.value = ''
  draftApplicationId.value = ''
  parseError.value = null
  submitError.value = null
  dependencyRows.value = []
}

async function processFile(file: File): Promise<void> {
  selectedFileName.value = file.name
  isDragging.value = false
  parseError.value = null
  submitError.value = null
  dependencyRows.value = []

  try {
    const raw = JSON.parse(await file.text()) as Record<string, unknown>
    let appCandidate: FlowApplication | null = null
    let templateCandidate: WorkflowGraphTemplate | null = null
    try {
      const parsedDoc = parseWorkflowAppDocumentV1(raw)
      appCandidate = parsedDoc.application
      templateCandidate = parsedDoc.template
    } catch {
      appCandidate = (raw.application ?? (raw.format_id === 'amvision.flow-application.v1' ? raw : null)) as
        | FlowApplication
        | null
      templateCandidate = (raw.template ?? raw.saved_template ?? null) as WorkflowGraphTemplate | null
    }
    if (!appCandidate || typeof appCandidate !== 'object' || !appCandidate.application_id) {
      parseError.value = '无效的应用 JSON 文件'
      return
    }
    parsedApp.value = appCandidate
    parsedTemplate.value = templateCandidate
    draftDisplayName.value = appCandidate.display_name || appCandidate.application_id
    draftApplicationId.value = appCandidate.application_id
    await checkDependencies(appCandidate, templateCandidate)
  } catch (err) {
    parseError.value = err instanceof Error ? `JSON 解析失败: ${err.message}` : '无法读取文件'
  }
}

async function handleFileSelect(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file) return
  await processFile(file)
}

async function handleFileDrop(event: DragEvent): Promise<void> {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  await processFile(file)
}

async function checkDependencies(
  application: FlowApplication,
  template: WorkflowGraphTemplate | null,
): Promise<void> {
  checking.value = true
  const rows: DependencyRow[] = []
  try {
    const [catalog, validation] = await Promise.all([
      getWorkflowNodeCatalog().catch(() => null),
      validateWorkflowApplication(props.projectId, application, template),
    ])
    if (catalog && template?.nodes) {
      const availableNodeTypes = new Set(catalog.node_definitions.map((item) => item.node_type_id))
      const missingTypes = Array.from(
        new Set(template.nodes.map((node) => node.node_type_id).filter((id) => !availableNodeTypes.has(id))),
      )
      for (const nodeTypeId of missingTypes) {
        rows.push({
          key: `node-${nodeTypeId}`,
          kindLabel: '节点包',
          name: nodeTypeId,
          ok: false,
          statusText: '缺少',
          route: '/custom-nodes',
          actionLabel: '查看节点包',
        })
      }
      if (missingTypes.length === 0) {
        rows.push({
          key: 'node-catalog-ok',
          kindLabel: '节点依赖',
          name: `${template.nodes.length} 个节点`,
          ok: true,
          statusText: '可用',
        })
      }
    }
    rows.push({
      key: 'contract-valid',
      kindLabel: '接口校验',
      name: `${validation.input_binding_ids.length} 输入 / ${validation.output_binding_ids.length} 输出`,
      ok: validation.valid,
      statusText: validation.valid ? '通过' : '未通过',
    })
    dependencyRows.value = rows
  } catch (err) {
    parseError.value = getErrorMessage(err)
  } finally {
    checking.value = false
  }
}

async function submitImport(): Promise<void> {
  if (!parsedApp.value || !canSubmit.value) return
  busy.value = true
  submitError.value = null
  try {
    const applicationPayload: FlowApplication = {
      ...parsedApp.value,
      application_id: draftApplicationId.value.trim(),
      display_name: draftDisplayName.value.trim(),
      ...(parsedTemplate.value
        ? {
            template_ref: {
              ...parsedApp.value.template_ref,
              template_id: parsedTemplate.value.template_id,
              template_version: parsedTemplate.value.template_version,
            },
          }
        : {}),
    }
    const saved = parsedTemplate.value
      ? await saveWorkflowApplication(props.projectId, applicationPayload, parsedTemplate.value)
      : await saveWorkflowApplication(props.projectId, applicationPayload)
    emit('imported', saved)
  } catch (err) {
    submitError.value = getErrorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.app-import-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.app-import-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.app-import-drop {
  display: grid;
  justify-items: center;
  gap: 6px;
  padding: 26px 16px;
  border: 1.5px dashed var(--am-border-strong);
  border-radius: var(--am-radius-md);
  background: var(--am-surface-soft);
  color: var(--am-text);
  cursor: pointer;
  transition: border-color 140ms ease, background-color 140ms ease;
}

.app-import-drop:hover,
.app-import-drop.is-dragover {
  border-color: var(--am-action-primary);
  background: var(--am-action-soft);
}

.app-import-drop__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  color: var(--am-text-muted);
}

.app-import-drop.is-dragover .app-import-drop__icon {
  color: var(--am-action-primary);
  border-color: var(--am-action-primary);
}

.app-import-drop strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-import-drop small {
  font-size: 12px;
  color: var(--am-text-muted);
}

.app-import-file-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  font-size: 13px;
}

.app-import-file-chip__left {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: var(--am-text-strong);
}

.app-import-file-chip__left span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-import-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  padding: 4px;
}

.app-import-clear:hover:not(:disabled) {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.app-import-note {
  margin: 0;
  font-size: 13px;
  color: var(--am-text-muted);
}

.app-import-field {
  display: grid;
  gap: 6px;
}

.app-import-field > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
}

.app-import-field > span em {
  color: #dc2626;
  font-style: normal;
}

.app-import-field input {
  width: 100%;
  box-sizing: border-box;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 13px;
}

.app-import-warn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--am-radius-sm);
  background: color-mix(in srgb, #f59e0b 14%, var(--am-surface));
  color: #b45309;
  font-size: 13px;
  font-weight: 500;
}

:root[data-theme='dark'] .app-import-warn {
  color: #fbbf24;
}

.app-import-ok {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--am-radius-sm);
  background: var(--am-action-soft);
  color: var(--am-action-primary);
  font-size: 13px;
  font-weight: 500;
}

.app-dep-table-wrap {
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  overflow: hidden;
}

.app-dep-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.app-dep-table th {
  padding: 10px 12px;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
  background: var(--am-table-header, var(--am-surface));
  border-bottom: 1px solid var(--am-border);
}

.app-dep-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
}

.app-dep-table tbody tr:last-child td {
  border-bottom: none;
}

.app-dep-kind {
  margin-right: 6px;
  color: var(--am-text-muted);
  font-size: 12px;
}

.app-dep-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.app-dep-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.app-dep-status.is-ok .app-dep-dot {
  background: var(--am-action-primary);
}

.app-dep-status.is-bad .app-dep-dot {
  background: #dc2626;
}

.app-dep-link {
  color: var(--am-action-primary);
  font-weight: 500;
  text-decoration: none;
}

.app-dep-dash {
  color: var(--am-text-muted);
}
</style>
