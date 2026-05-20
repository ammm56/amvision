export type WorkflowJsonObject = Record<string, unknown>

export interface WorkflowPayloadContract {
  format_id: string
  payload_type_id: string
  display_name: string
  transport_kind: string
  json_schema: WorkflowJsonObject
  artifact_kinds: string[]
  metadata: WorkflowJsonObject
}

export interface WorkflowNodePackManifest {
  pack_id?: string
  node_pack_id?: string
  name?: string
  display_name?: string
  version?: string
  capabilities?: string[]
  metadata?: WorkflowJsonObject
  [key: string]: unknown
}

export interface NodePortDefinition {
  name: string
  display_name: string
  payload_type_id: string
  description: string
  required: boolean
  multiple: boolean
  metadata: WorkflowJsonObject
}

export interface NodeParameterUiGroup {
  group_id: string
  display_name: string
  description: string
  order: number
}

export interface NodeParameterUiEnumOption {
  value: unknown
  label: string
}

export interface NodeParameterUiField {
  parameter_name: string
  display_name: string
  description: string
  group_id: string
  order: number
  required: boolean
  hidden: boolean
  readonly: boolean
  default_value: unknown
  enum_options: NodeParameterUiEnumOption[]
  json_schema: WorkflowJsonObject
}

export interface NodeParameterUiSchema {
  groups: NodeParameterUiGroup[]
  fields: NodeParameterUiField[]
}

export interface NodeDefinition {
  format_id: string
  node_type_id: string
  display_name: string
  category: string
  description: string
  implementation_kind: 'core-node' | 'custom-node'
  runtime_kind: 'python-callable' | 'worker-task' | 'service-call'
  input_ports: NodePortDefinition[]
  output_ports: NodePortDefinition[]
  parameter_schema: WorkflowJsonObject
  parameter_ui_schema: NodeParameterUiSchema | null
  capability_tags: string[]
  runtime_requirements: WorkflowJsonObject
  node_pack_id?: string | null
  node_pack_version?: string | null
  metadata: WorkflowJsonObject
}

export interface WorkflowNodePaletteGroup {
  category: string
  display_name: string
  item_count: number
  node_definitions: NodeDefinition[]
}

export interface WorkflowNodeCatalogResponse {
  node_pack_manifests: WorkflowNodePackManifest[]
  payload_contracts: WorkflowPayloadContract[]
  node_definitions: NodeDefinition[]
  palette_groups: WorkflowNodePaletteGroup[]
}

export interface WorkflowGraphNode {
  node_id: string
  node_type_id: string
  parameters: WorkflowJsonObject
  ui_state: WorkflowJsonObject
  metadata: WorkflowJsonObject
}

export interface WorkflowGraphEdge {
  edge_id: string
  source_node_id: string
  source_port: string
  target_node_id: string
  target_port: string
  metadata: WorkflowJsonObject
}

export interface WorkflowGraphInput {
  input_id: string
  display_name: string
  payload_type_id: string
  target_node_id: string
  target_port: string
  required: boolean
  metadata: WorkflowJsonObject
}

export interface WorkflowGraphOutput {
  output_id: string
  display_name: string
  payload_type_id: string
  source_node_id: string
  source_port: string
  metadata: WorkflowJsonObject
}

export interface WorkflowGraphTemplate {
  format_id: 'amvision.workflow-graph-template.v1'
  template_id: string
  template_version: string
  display_name: string
  description: string
  nodes: WorkflowGraphNode[]
  edges: WorkflowGraphEdge[]
  template_inputs: WorkflowGraphInput[]
  template_outputs: WorkflowGraphOutput[]
  metadata: WorkflowJsonObject
}

export interface FlowTemplateReference {
  template_id: string
  template_version: string
  source_kind: 'json-file' | 'registry' | 'embedded'
  source_uri?: string | null
  metadata: WorkflowJsonObject
}

export interface FlowApplicationBinding {
  binding_id: string
  direction: 'input' | 'output'
  template_port_id: string
  binding_kind: string
  required: boolean
  config: WorkflowJsonObject
  metadata: WorkflowJsonObject
}

export interface FlowApplication {
  format_id: 'amvision.flow-application.v1'
  application_id: string
  display_name: string
  template_ref: FlowTemplateReference
  runtime_mode: 'python-json-workflow'
  description: string
  bindings: FlowApplicationBinding[]
  metadata: WorkflowJsonObject
}

export interface WorkflowTemplateValidationResponse {
  valid: boolean
  template_id: string
  template_version: string
  node_count: number
  edge_count: number
  template_input_ids: string[]
  template_output_ids: string[]
  referenced_node_type_ids: string[]
}

export interface WorkflowTemplateSummary {
  project_id: string
  template_id: string
  display_name: string
  description: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
  latest_template_version: string
  version_count: number
  versions: string[]
}

export interface WorkflowTemplateVersionSummary extends WorkflowTemplateValidationResponse {
  project_id: string
  object_key: string
  display_name: string
  description: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
}

export interface WorkflowTemplateDocument extends WorkflowTemplateValidationResponse {
  project_id: string
  object_key: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
  template: WorkflowGraphTemplate
}

export interface WorkflowTemplateReferenceSummary {
  project_id: string
  template_id: string
  template_version: string
  display_name: string
  description: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
}

export interface WorkflowApplicationValidationResponse {
  valid: boolean
  application_id: string
  template_id: string
  template_version: string
  binding_count: number
  input_binding_ids: string[]
  output_binding_ids: string[]
}

export interface WorkflowApplicationSummary {
  project_id: string
  object_key: string
  application_id: string
  display_name: string
  description: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
  template_id: string
  template_version: string
  template_summary: WorkflowTemplateReferenceSummary | null
  binding_count: number
  input_binding_ids: string[]
  output_binding_ids: string[]
}

export interface WorkflowApplicationReferenceSummary {
  project_id: string
  application_id: string
  display_name: string
  description: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
  template_id: string
  template_version: string
}

export interface WorkflowApplicationDocument extends WorkflowApplicationValidationResponse {
  project_id: string
  object_key: string
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
  template_summary: WorkflowTemplateReferenceSummary | null
  application: FlowApplication
}

export type WorkflowRunState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timeout' | string
export type WorkflowAppRuntimeState = 'created' | 'starting' | 'running' | 'stopping' | 'stopped' | 'failed' | string

export interface WorkflowPreviewDisplayOutput {
  node_id: string
  node_type_id: string
  output_name: string
  payload: WorkflowJsonObject
}

export interface WorkflowPreviewRun {
  format_id: string
  preview_run_id: string
  project_id: string
  application_id: string
  source_kind: string
  application_snapshot_object_key: string
  template_snapshot_object_key: string
  state: WorkflowRunState
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  created_by?: string | null
  timeout_seconds: number
  outputs: WorkflowJsonObject
  template_outputs: WorkflowJsonObject
  node_records: WorkflowJsonObject[]
  preview_display_outputs: WorkflowPreviewDisplayOutput[]
  error_message?: string | null
  retention_until?: string | null
  metadata: WorkflowJsonObject
}

export interface WorkflowPreviewRunSummary {
  format_id: string
  preview_run_id: string
  project_id: string
  application_id: string
  source_kind: string
  state: WorkflowRunState
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  created_by?: string | null
  timeout_seconds: number
  error_message?: string | null
  retention_until?: string | null
}

export interface WorkflowRuntimeEvent {
  format_id: string
  sequence: number
  event_type: string
  created_at: string
  message: string
  payload: WorkflowJsonObject
}

export interface WorkflowPreviewRunEvent extends WorkflowRuntimeEvent {
  preview_run_id: string
}

export interface WorkflowAppRuntimeEvent extends WorkflowRuntimeEvent {
  workflow_runtime_id: string
}

export interface WorkflowRunEvent extends WorkflowRuntimeEvent {
  workflow_run_id: string
}

export interface WorkflowAppRuntime {
  format_id: string
  workflow_runtime_id: string
  project_id: string
  application_id: string
  display_name: string
  application_snapshot_object_key: string
  template_snapshot_object_key: string
  execution_policy_snapshot_object_key?: string | null
  desired_state: WorkflowAppRuntimeState
  observed_state: WorkflowAppRuntimeState
  request_timeout_seconds: number
  heartbeat_interval_seconds: number
  heartbeat_timeout_seconds: number
  created_at: string
  updated_at: string
  created_by?: string | null
  updated_by?: string | null
  application_summary?: WorkflowApplicationReferenceSummary | null
  template_summary?: WorkflowTemplateReferenceSummary | null
  last_started_at?: string | null
  last_stopped_at?: string | null
  heartbeat_at?: string | null
  worker_process_id?: number | null
  loaded_snapshot_fingerprint?: string | null
  last_error?: string | null
  health_summary: WorkflowJsonObject
  metadata: WorkflowJsonObject
}

export interface WorkflowAppRuntimeInstance {
  format_id: string
  instance_id: string
  workflow_runtime_id: string
  state: WorkflowAppRuntimeState
  process_id?: number | null
  current_run_id?: string | null
  started_at?: string | null
  heartbeat_at?: string | null
  loaded_snapshot_fingerprint?: string | null
  last_error?: string | null
  health_summary: WorkflowJsonObject
}

export interface WorkflowRun {
  format_id: string
  workflow_run_id: string
  workflow_runtime_id: string
  project_id: string
  application_id: string
  state: WorkflowRunState
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  created_by?: string | null
  requested_timeout_seconds: number
  assigned_process_id?: number | null
  input_payload: WorkflowJsonObject
  outputs: WorkflowJsonObject
  template_outputs: WorkflowJsonObject
  node_records: WorkflowJsonObject[]
  error_message?: string | null
  metadata: WorkflowJsonObject
}

export interface WorkflowExecutionPolicy {
  format_id: string
  execution_policy_id: string
  project_id: string
  display_name: string
  policy_kind: string
  default_timeout_seconds: number
  max_run_timeout_seconds: number
  trace_level: string
  retain_node_records_enabled: boolean
  retain_trace_enabled: boolean
  created_at: string
  updated_at: string
  created_by?: string | null
  metadata: WorkflowJsonObject
}
