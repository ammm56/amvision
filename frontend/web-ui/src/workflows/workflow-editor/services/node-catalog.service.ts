import { apiRequest } from '@/shared/api/http-client'
import type { WorkflowNodeCatalogResponse } from '../types'

export interface WorkflowNodeCatalogQuery {
  category?: string
  nodePackId?: string
  payloadTypeId?: string
  keyword?: string
}

export async function getWorkflowNodeCatalog(query: WorkflowNodeCatalogQuery = {}): Promise<WorkflowNodeCatalogResponse> {
  return apiRequest<WorkflowNodeCatalogResponse>('/workflows/node-catalog', {
    query: {
      category: query.category,
      node_pack_id: query.nodePackId,
      payload_type_id: query.payloadTypeId,
      q: query.keyword,
    },
  })
}
