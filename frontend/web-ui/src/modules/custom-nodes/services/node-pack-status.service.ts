import { apiRequest } from '@/shared/api/http-client'
import type { WorkflowNodePackManifest } from '@/workflows/workflow-editor/types'

export interface NodePackStatusIssue {
  severity: string
  code: string
  message: string
  details: Record<string, unknown>
}

export interface NodePackStatusLog {
  level: string
  message: string
  created_at: string
  details: Record<string, unknown>
}

export interface NodePackDependencyStatus {
  node_pack_id: string
  version_range: string | null
  installed: boolean
  enabled: boolean
  version: string | null
  satisfied: boolean
}

export interface NodePackStatusItem {
  node_pack_id: string
  display_name: string
  version: string | null
  state: 'loaded' | 'disabled' | 'failed' | string
  enabled: boolean
  source_dir: string
  manifest_path: string | null
  custom_node_catalog_path: string | null
  loaded_at: string | null
  node_count: number
  capabilities: string[]
  dependencies: NodePackDependencyStatus[]
  issues: NodePackStatusIssue[]
  logs: NodePackStatusLog[]
  manifest: WorkflowNodePackManifest | null
}

export interface NodePackStatusResponse {
  generated_at: string
  custom_nodes_root_dir: string
  items: NodePackStatusItem[]
  logs: NodePackStatusLog[]
}

export interface NodePackVersion {
  node_pack_id: string
  version: string
  content_sha256: string
  directory_name: string
  installed_at: string
  installed_by: string
  source_file_name: string | null
  active: boolean
}

export interface NodePackAuditRecord {
  event_id: string
  action: string
  status: 'succeeded' | 'failed' | string
  created_at: string
  actor_id: string
  node_pack_id: string | null
  from_version: string | null
  to_version: string | null
  content_sha256: string | null
  source_file_name: string | null
  details: Record<string, unknown>
}

export interface NodePackLifecycleResponse {
  node_pack_id: string
  version: string
  active_directory: string
  versions: NodePackVersion[]
  audit: NodePackAuditRecord
  status: NodePackStatusResponse
}

export async function getNodePackStatus(): Promise<NodePackStatusResponse> {
  return apiRequest<NodePackStatusResponse>('/workflows/node-pack-status')
}

export async function reloadNodePacks(): Promise<NodePackStatusResponse> {
  return apiRequest<NodePackStatusResponse>('/workflows/node-packs/reload', { method: 'POST' })
}

export async function validateNodePack(nodePackId: string): Promise<NodePackStatusResponse> {
  return apiRequest<NodePackStatusResponse>(`/workflows/node-packs/${encodeURIComponent(nodePackId)}/validate`, { method: 'POST' })
}

export async function enableNodePack(nodePackId: string): Promise<NodePackStatusResponse> {
  return apiRequest<NodePackStatusResponse>(`/workflows/node-packs/${encodeURIComponent(nodePackId)}/enable`, { method: 'POST' })
}

export async function disableNodePack(nodePackId: string): Promise<NodePackStatusResponse> {
  return apiRequest<NodePackStatusResponse>(`/workflows/node-packs/${encodeURIComponent(nodePackId)}/disable`, { method: 'POST' })
}

export async function getNodePackLogs(nodePackId: string): Promise<NodePackStatusLog[]> {
  return apiRequest<NodePackStatusLog[]>(`/workflows/node-packs/${encodeURIComponent(nodePackId)}/logs`)
}

export async function installNodePack(packageFile: File, enabled = true): Promise<NodePackLifecycleResponse> {
  const body = new FormData()
  body.set('package', packageFile)
  body.set('enabled', String(enabled))
  return apiRequest<NodePackLifecycleResponse>('/workflows/node-packs/install', {
    method: 'POST',
    body,
  })
}

export async function getNodePackVersions(nodePackId: string): Promise<NodePackVersion[]> {
  return apiRequest<NodePackVersion[]>(`/workflows/node-packs/${encodeURIComponent(nodePackId)}/versions`)
}

export async function rollbackNodePack(nodePackId: string, targetVersion: string): Promise<NodePackLifecycleResponse> {
  return apiRequest<NodePackLifecycleResponse>(
    `/workflows/node-packs/${encodeURIComponent(nodePackId)}/rollback/${encodeURIComponent(targetVersion)}`,
    { method: 'POST' },
  )
}

export async function getNodePackAudit(nodePackId?: string): Promise<NodePackAuditRecord[]> {
  return apiRequest<NodePackAuditRecord[]>('/workflows/node-packs/audit', {
    query: { node_pack_id: nodePackId, limit: 200 },
  })
}
