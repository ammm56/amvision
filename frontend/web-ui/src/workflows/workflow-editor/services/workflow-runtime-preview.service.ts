import { apiRequest } from '@/shared/api/http-client'
import type { WorkflowAppContract, WorkflowAppModeConfig } from '../app-mode/workflow-app-mode'
import type { FlowApplication, NodeDefinition, WorkflowGraphTemplate } from '../types'

export interface RuntimePreviewNodeDefinitionWarning {
  node_type_id: string
  reason: 'definition_missing' | 'definition_changed'
}

export interface RuntimePreviewSnapshot {
  workflow_runtime_id: string
  workflow_runtime_revision_id: string
  workflow_app_version_id: string
  runtime_generation: number
  worker_instance_id: string | null
  snapshot_fingerprint: string
  project_id: string
  application_id: string
  observed_state: string
  active: boolean
  display_name: string
  application: FlowApplication
  contract: WorkflowAppContract
  app_mode: WorkflowAppModeConfig | null
  template: WorkflowGraphTemplate
  node_definitions?: NodeDefinition[]
  node_definition_warnings?: RuntimePreviewNodeDefinitionWarning[]
}

export async function getWorkflowRuntimePreviewSnapshot(
  workflowRuntimeId: string,
): Promise<RuntimePreviewSnapshot> {
  return apiRequest<RuntimePreviewSnapshot>(
    `/workflows/app-runtimes/${encodeURIComponent(workflowRuntimeId)}/preview-snapshot`,
  )
}
