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
  permission_scopes: string[]
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