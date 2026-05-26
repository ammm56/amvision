import { apiRequest } from './http-client'
import type { ProjectFileMetadata } from '@/shared/contracts'

export async function getProjectFileMetadata(projectId: string, objectKey: string): Promise<ProjectFileMetadata> {
  return apiRequest<ProjectFileMetadata>(`/projects/${encodeURIComponent(projectId)}/files/metadata`, {
    query: { object_key: objectKey },
  })
}

export async function fetchProjectFileBlob(projectId: string, objectKey: string, download = false): Promise<Blob> {
  return apiRequest<Blob>(`/projects/${encodeURIComponent(projectId)}/files/content`, {
    responseType: 'blob',
    query: { object_key: objectKey, download },
  })
}

export async function createProjectFileObjectUrl(projectId: string, objectKey: string): Promise<string> {
  const blob = await fetchProjectFileBlob(projectId, objectKey)
  return URL.createObjectURL(blob)
}