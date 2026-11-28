import type { PaginatedResult, PaginationMeta } from '@/shared/api/pagination'
import {
  listWorkflowTriggerSources,
  type WorkflowTriggerSource,
} from '@/modules/integrations/services/trigger-source.service'
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
  latestVersion: WorkflowAppVersion | null
  triggerCount: number
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

async function listProjectTriggerSourcesSafely(projectId: string): Promise<WorkflowTriggerSource[]> {
  try {
    const items: WorkflowTriggerSource[] = []
    const visitedOffsets = new Set<number>()
    let offset = 0
    const limit = 100
    while (!visitedOffsets.has(offset)) {
      visitedOffsets.add(offset)
      const page = await listWorkflowTriggerSources({ projectId, offset, limit })
      items.push(...page.items)
      const nextOffset = page.pagination.nextOffset
      if (!page.pagination.hasMore || nextOffset === null || visitedOffsets.has(nextOffset)) break
      offset = nextOffset
    }
    return items
  } catch {
    return []
  }
}

async function resolveAppLatestVersionSafely(
  projectId: string,
  applicationId: string,
): Promise<WorkflowAppVersion | null> {
  try {
    const firstPage = await listWorkflowAppVersions(projectId, applicationId, { offset: 0, limit: 10 })
    return resolveLatestPublishedVersion(projectId, applicationId, firstPage)
  } catch {
    return null
  }
}

export async function listWorkflowApps(projectId: string, query: WorkflowApplicationListQuery = {}): Promise<WorkflowAppListResult> {
  const [applicationResponse, triggerSources] = await Promise.all([
    listWorkflowApplications(projectId, query),
    listProjectTriggerSourcesSafely(projectId),
  ])
  const applicationIds = applicationResponse.items.map((application) => application.application_id)
  const runtimes = await listAllApplicationSetRuntimes(projectId, applicationIds)
  const runtimesByApplication = groupRuntimesByApplication(runtimes)
  const triggerCountByRuntime = new Map<string, number>()
  for (const trigger of triggerSources) {
    if (!trigger.workflow_runtime_id) continue
    triggerCountByRuntime.set(
      trigger.workflow_runtime_id,
      (triggerCountByRuntime.get(trigger.workflow_runtime_id) ?? 0) + 1,
    )
  }

  const latestVersionByApp = new Map<string, WorkflowAppVersion | null>()
  const versionConcurrency = 6
  for (let offset = 0; offset < applicationIds.length; offset += versionConcurrency) {
    const chunk = applicationIds.slice(offset, offset + versionConcurrency)
    const resolved = await Promise.all(
      chunk.map(async (appId) => [appId, await resolveAppLatestVersionSafely(projectId, appId)] as const),
    )
    for (const [appId, latest] of resolved) {
      latestVersionByApp.set(appId, latest)
    }
  }

  return {
    items: applicationResponse.items.map((application) => {
      const appRuntimes = runtimesByApplication.get(application.application_id) ?? []
      const triggerCount = appRuntimes.reduce(
        (sum, runtime) => sum + (triggerCountByRuntime.get(runtime.workflow_runtime_id) ?? 0),
        0,
      )
      return {
        application,
        runtimes: appRuntimes,
        primaryRuntime: pickPrimaryRuntime(appRuntimes),
        latestVersion: latestVersionByApp.get(application.application_id) ?? null,
        triggerCount,
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
