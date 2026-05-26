import { apiRequest } from '@/shared/api/http-client'

export interface SystemDiagnosticsResponse {
  generated_at: string
  request_id: string
  about: Record<string, unknown>
  system: Record<string, unknown>
  python_runtime: Record<string, unknown>
  devices: Record<string, unknown>
  services: Record<string, unknown>
}

export async function getSystemDiagnostics(): Promise<SystemDiagnosticsResponse> {
  return apiRequest<SystemDiagnosticsResponse>('/system/diagnostics')
}