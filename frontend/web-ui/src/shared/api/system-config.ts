import { apiRequest } from './http-client'

export interface SystemConfigResponse {
  format_id: string
  config: Record<string, unknown>
  metadata: Record<string, unknown>
}

export async function getSystemConfig(): Promise<SystemConfigResponse> {
  return apiRequest<SystemConfigResponse>('/system/config')
}
