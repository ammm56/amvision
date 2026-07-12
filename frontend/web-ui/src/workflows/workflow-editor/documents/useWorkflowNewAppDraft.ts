import { computed, ref, type ComputedRef } from 'vue'

import type { WorkflowAppDocument } from '../services/workflow-app.service'
import type {
  FlowApplication,
  WorkflowApplicationDocument,
  WorkflowGraphTemplate,
  WorkflowTemplateDocument,
} from '../types'

export interface NewWorkflowAppDraftState {
  applicationId: string
  displayName: string
  graphId: string
  graphVersion: string
  description: string
}

export interface WorkflowNewAppDraftOptions {
  isNewApp: ComputedRef<boolean>
  selectedProjectId: ComputedRef<string>
  readNodeCount: () => number
}

export function useWorkflowNewAppDraft(options: WorkflowNewAppDraftOptions) {
  const newWorkflowAppDraft = ref<NewWorkflowAppDraftState>(createNewWorkflowAppDraftState())

  const newWorkflowAppSaveBlocker = computed(() => readNewWorkflowAppSaveBlocker())

  function resetNewWorkflowAppDraft(): void {
    newWorkflowAppDraft.value = createNewWorkflowAppDraftState()
  }

  function updateNewWorkflowDraftField(field: keyof NewWorkflowAppDraftState, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    newWorkflowAppDraft.value = { ...newWorkflowAppDraft.value, [field]: target.value }
  }

  function normalizeNewWorkflowApplicationId(event?: Event): void {
    const normalizedApplicationId = normalizeWorkflowIdentifier(newWorkflowAppDraft.value.applicationId, 'workflow-app')
    newWorkflowAppDraft.value.applicationId = normalizedApplicationId
    if (event?.target instanceof HTMLInputElement) event.target.value = normalizedApplicationId
  }

  function normalizeNewWorkflowGraphId(event?: Event): void {
    const normalizedGraphId = normalizeWorkflowIdentifier(newWorkflowAppDraft.value.graphId, `${newWorkflowAppDraft.value.applicationId || 'workflow'}-graph`)
    newWorkflowAppDraft.value.graphId = normalizedGraphId
    if (event?.target instanceof HTMLInputElement) event.target.value = normalizedGraphId
  }

  function normalizeNewWorkflowGraphVersion(event?: Event): void {
    const normalizedGraphVersion = newWorkflowAppDraft.value.graphVersion.trim() || '1.0.0'
    newWorkflowAppDraft.value.graphVersion = normalizedGraphVersion
    if (event?.target instanceof HTMLInputElement) event.target.value = normalizedGraphVersion
  }

  function readNewWorkflowAppSaveBlocker(): string | null {
    if (!options.isNewApp.value) return null
    const draft = newWorkflowAppDraft.value
    if (!draft.displayName.trim()) return '填写应用名称后才能保存。'
    if (!draft.applicationId.trim()) return '填写应用 id 后才能保存。'
    if (!draft.graphId.trim()) return '填写图 id 后才能保存。'
    if (!draft.graphVersion.trim()) return '填写图版本后才能保存。'
    if (options.readNodeCount() === 0) return '至少添加一个节点后才能首次保存。'
    return null
  }

  function createLocalWorkflowAppDraft(): WorkflowAppDocument {
    const template = createLocalWorkflowTemplate()
    const application = createLocalFlowApplication(template)
    const now = new Date().toISOString()
    return {
      applicationDocument: createLocalWorkflowApplicationDocument(application, template, now),
      graphDocument: createLocalWorkflowTemplateDocument(template, now),
      runtimes: [],
      primaryRuntime: null,
    }
  }

  function createLocalWorkflowTemplate(): WorkflowGraphTemplate {
    const draft = newWorkflowAppDraft.value
    return {
      format_id: 'amvision.workflow-graph-template.v1',
      template_id: draft.graphId,
      template_version: draft.graphVersion,
      display_name: `${draft.displayName || draft.graphId} 图`,
      description: draft.description.trim(),
      nodes: [],
      edges: [],
      template_inputs: [],
      template_outputs: [],
      groups: [],
      metadata: { source: 'workflow-graph-editor' },
    }
  }

  function createLocalFlowApplication(template: WorkflowGraphTemplate): FlowApplication {
    const draft = newWorkflowAppDraft.value
    return {
      format_id: 'amvision.flow-application.v1',
      application_id: draft.applicationId,
      display_name: draft.displayName,
      template_ref: {
        template_id: template.template_id,
        template_version: template.template_version,
        source_kind: 'json-file',
        source_uri: buildWorkflowTemplateSourceUri(options.selectedProjectId.value, template.template_id, template.template_version),
        metadata: {},
      },
      runtime_mode: 'python-json-workflow',
      description: draft.description.trim(),
      bindings: [],
      metadata: { source: 'workflow-graph-editor' },
    }
  }

  function createLocalWorkflowTemplateDocument(template: WorkflowGraphTemplate, now: string): WorkflowTemplateDocument {
    return {
      valid: false,
      template_id: template.template_id,
      template_version: template.template_version,
      node_count: template.nodes.length,
      edge_count: template.edges.length,
      template_input_ids: template.template_inputs.map((input) => input.input_id),
      template_output_ids: template.template_outputs.map((output) => output.output_id),
      referenced_node_type_ids: template.nodes.map((node) => node.node_type_id),
      project_id: options.selectedProjectId.value,
      object_key: '',
      created_at: now,
      updated_at: now,
      created_by: null,
      updated_by: null,
      template,
    }
  }

  function createLocalWorkflowApplicationDocument(application: FlowApplication, template: WorkflowGraphTemplate, now: string): WorkflowApplicationDocument {
    const inputBindingIds = application.bindings.filter((binding) => binding.direction === 'input').map((binding) => binding.binding_id)
    const outputBindingIds = application.bindings.filter((binding) => binding.direction === 'output').map((binding) => binding.binding_id)
    return {
      valid: false,
      application_id: application.application_id,
      template_id: template.template_id,
      template_version: template.template_version,
      binding_count: application.bindings.length,
      input_binding_ids: inputBindingIds,
      output_binding_ids: outputBindingIds,
      project_id: options.selectedProjectId.value,
      object_key: '',
      created_at: now,
      updated_at: now,
      created_by: null,
      updated_by: null,
      template_summary: null,
      application,
    }
  }

  function applyNewWorkflowTemplateSettings(template: WorkflowGraphTemplate): WorkflowGraphTemplate {
    if (!options.isNewApp.value) return template
    const draft = newWorkflowAppDraft.value
    return {
      ...template,
      template_id: draft.graphId.trim(),
      template_version: draft.graphVersion.trim(),
      display_name: `${draft.displayName.trim() || draft.graphId.trim()} 图`,
      description: draft.description.trim(),
      metadata: { ...template.metadata, source: template.metadata.source ?? 'workflow-graph-editor' },
    }
  }

  function buildNewWorkflowApplicationPatch(sourceApplication: FlowApplication, template: WorkflowGraphTemplate): FlowApplication {
    if (!options.isNewApp.value) {
      return {
        ...sourceApplication,
        template_ref: {
          ...sourceApplication.template_ref,
          template_id: template.template_id,
          template_version: template.template_version,
        },
      }
    }
    const draft = newWorkflowAppDraft.value
    return {
      ...sourceApplication,
      application_id: draft.applicationId.trim(),
      display_name: draft.displayName.trim(),
      template_ref: {
        ...sourceApplication.template_ref,
        template_id: template.template_id,
        template_version: template.template_version,
        source_kind: 'json-file',
        source_uri: buildWorkflowTemplateSourceUri(options.selectedProjectId.value, template.template_id, template.template_version),
      },
      description: draft.description.trim(),
    }
  }

  return {
    newWorkflowAppDraft,
    newWorkflowAppSaveBlocker,
    resetNewWorkflowAppDraft,
    updateNewWorkflowDraftField,
    normalizeNewWorkflowApplicationId,
    normalizeNewWorkflowGraphId,
    normalizeNewWorkflowGraphVersion,
    readNewWorkflowAppSaveBlocker,
    createLocalWorkflowAppDraft,
    applyNewWorkflowTemplateSettings,
    buildNewWorkflowApplicationPatch,
  }
}

function createNewWorkflowAppDraftState(): NewWorkflowAppDraftState {
  const suffix = new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14)
  return {
    applicationId: `workflow-app-${suffix}`,
    displayName: '新建应用',
    graphId: `workflow-graph-${suffix}`,
    graphVersion: '1.0.0',
    description: '',
  }
}

function buildWorkflowTemplateSourceUri(projectId: string, templateId: string, templateVersion: string): string {
  return `workflows/projects/${projectId}/templates/${templateId}/versions/${templateVersion}/template.json`
}

function normalizeWorkflowIdentifier(value: string, fallback: string): string {
  const normalized = value.trim().replace(/[\\/]+/g, '_').replace(/\.{2,}/g, '_').replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^[_ .-]+|[_ .-]+$/g, '')
  return normalized || fallback
}
