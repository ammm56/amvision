import type { PaginatedResult, PaginationMeta } from '@/shared/api/pagination'
import {
  getWorkflowApplication,
  listWorkflowApplications,
  listWorkflowAppVersions,
  saveWorkflowApplication,
  type WorkflowApplicationListQuery,
} from './workflow-application.service'
import { getWorkflowTemplate } from './workflow-template.service'
import { listWorkflowAppRuntimes } from './workflow-runtime.service'
import type {
  FlowApplication,
  WorkflowApplicationDocument,
  WorkflowApplicationSummary,
  WorkflowAppRuntime,
  WorkflowAppVersion,
  WorkflowGraphTemplate,
  WorkflowTemplateDocument,
} from '../types'

export interface WorkflowAppSummary {
  application: WorkflowApplicationSummary
  runtimes: WorkflowAppRuntime[]
  primaryRuntime: WorkflowAppRuntime | null
}

export interface WorkflowAppDocument {
  applicationDocument: WorkflowApplicationDocument
  graphDocument: WorkflowTemplateDocument
  runtimes: WorkflowAppRuntime[]
  primaryRuntime: WorkflowAppRuntime | null
  versions: WorkflowAppVersion[]
  versionPagination: PaginationMeta
  latestVersion: WorkflowAppVersion | null
}

export interface WorkflowAppListResult extends PaginatedResult<WorkflowAppSummary> {
  runtimes: WorkflowAppRuntime[]
}

export interface WorkflowAppSaveInput {
  projectId: string
  application: FlowApplication
  template: WorkflowGraphTemplate
}

export interface WorkflowAppSaveResult {
  applicationDocument: WorkflowApplicationDocument
  graphDocument: WorkflowTemplateDocument
}

function pickPrimaryRuntime(runtimes: WorkflowAppRuntime[]): WorkflowAppRuntime | null {
  return runtimes.find((runtime) => runtime.observed_state === 'running') ?? runtimes[0] ?? null
}

function groupRuntimesByApplication(runtimes: WorkflowAppRuntime[]): Map<string, WorkflowAppRuntime[]> {
  const groupedRuntimes = new Map<string, WorkflowAppRuntime[]>()
  for (const runtime of runtimes) {
    const applicationRuntimes = groupedRuntimes.get(runtime.application_id) ?? []
    applicationRuntimes.push(runtime)
    groupedRuntimes.set(runtime.application_id, applicationRuntimes)
  }
  return groupedRuntimes
}

export async function resolveLatestPublishedVersion(
  projectId: string,
  applicationId: string,
  initialPage: PaginatedResult<WorkflowAppVersion>,
): Promise<WorkflowAppVersion | null> {
  let currentPage = initialPage
  const visitedOffsets = new Set<number>([initialPage.pagination.offset])
  while (true) {
    const publishedVersion = currentPage.items.find((version) => version.state === 'published')
    if (publishedVersion) return publishedVersion
    const nextOffset = currentPage.pagination.nextOffset
    if (!currentPage.pagination.hasMore || nextOffset === null || visitedOffsets.has(nextOffset)) return null
    visitedOffsets.add(nextOffset)
    currentPage = await listWorkflowAppVersions(projectId, applicationId, {
      offset: nextOffset,
      limit: currentPage.pagination.limit,
    })
  }
}

async function listAllApplicationRuntimes(
  projectId: string,
  applicationId: string,
): Promise<WorkflowAppRuntime[]> {
  const runtimes: WorkflowAppRuntime[] = []
  const visitedOffsets = new Set<number>()
  let offset = 0
  const limit = 100
  while (!visitedOffsets.has(offset)) {
    visitedOffsets.add(offset)
    const page = await listWorkflowAppRuntimes({ projectId, applicationId, offset, limit })
    runtimes.push(...page.items)
    const nextOffset = page.pagination.nextOffset
    if (!page.pagination.hasMore || nextOffset === null || visitedOffsets.has(nextOffset)) break
    offset = nextOffset
  }
  return runtimes
}

async function listAllApplicationSetRuntimes(
  projectId: string,
  applicationIds: string[],
): Promise<WorkflowAppRuntime[]> {
  if (applicationIds.length === 0) return []
  const runtimes: WorkflowAppRuntime[] = []
  const visitedOffsets = new Set<number>()
  let offset = 0
  const limit = 100
  while (!visitedOffsets.has(offset)) {
    visitedOffsets.add(offset)
    const page = await listWorkflowAppRuntimes({ projectId, applicationIds, offset, limit })
    runtimes.push(...page.items)
    const nextOffset = page.pagination.nextOffset
    if (!page.pagination.hasMore || nextOffset === null || visitedOffsets.has(nextOffset)) break
    offset = nextOffset
  }
  return runtimes
}

export async function listWorkflowApps(projectId: string, query: WorkflowApplicationListQuery = {}): Promise<WorkflowAppListResult> {
  const applicationResponse = await listWorkflowApplications(projectId, query)
  const runtimes = await listAllApplicationSetRuntimes(
    projectId,
    applicationResponse.items.map((application) => application.application_id),
  )
  const runtimesByApplication = groupRuntimesByApplication(runtimes)
  return {
    items: applicationResponse.items.map((application) => {
      const runtimes = runtimesByApplication.get(application.application_id) ?? []
      return {
        application,
        runtimes,
        primaryRuntime: pickPrimaryRuntime(runtimes),
      }
    }),
    pagination: applicationResponse.pagination,
    runtimes,
  }
}

export async function getWorkflowApp(projectId: string, applicationId: string): Promise<WorkflowAppDocument> {
  const [applicationDocument, applicationRuntimes, versionResponse] = await Promise.all([
    getWorkflowApplication(projectId, applicationId),
    listAllApplicationRuntimes(projectId, applicationId),
    listWorkflowAppVersions(projectId, applicationId, { limit: 25 }),
  ])
  const graphDocument = await getWorkflowTemplate(
    projectId,
    applicationDocument.application.template_ref.template_id,
    applicationDocument.application.template_ref.template_version,
  )
  const runtimes = applicationRuntimes.filter((runtime) => runtime.application_id === applicationId)
  const latestVersion = await resolveLatestPublishedVersion(projectId, applicationId, versionResponse)
  const versions = latestVersion && !versionResponse.items.some((version) => version.workflow_app_version_id === latestVersion.workflow_app_version_id)
    ? [...versionResponse.items, latestVersion].sort((left, right) => right.version_number - left.version_number)
    : versionResponse.items
  return {
    applicationDocument,
    graphDocument,
    runtimes,
    primaryRuntime: pickPrimaryRuntime(runtimes),
    versions,
    versionPagination: versionResponse.pagination,
    latestVersion,
  }
}

export async function saveWorkflowApp(input: WorkflowAppSaveInput): Promise<WorkflowAppSaveResult> {
  const applicationDocument = await saveWorkflowApplication(
    input.projectId,
    {
      ...input.application,
      template_ref: {
        ...input.application.template_ref,
        template_id: input.template.template_id,
        template_version: input.template.template_version,
      },
    },
    input.template,
  )
  const graphDocument = applicationDocument.saved_template
  return { applicationDocument, graphDocument }
}
