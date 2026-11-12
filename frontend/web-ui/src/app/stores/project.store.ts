import { defineStore } from 'pinia'

import { useSessionStore } from './session.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import type { ProjectCatalogItem, ProjectSummary } from '@/shared/contracts'
import { bootstrapProject, getProject, getProjectSummary, listProjects, type ProjectBootstrapInput } from '@/modules/projects/services/project.service'
import { ApiError } from '@/shared/api/error'
import { translate } from '@/platform/i18n'

interface LoadProjectsOptions {
  includeSummary?: boolean
  loadSelectedSummary?: boolean
}

/** 同一账号的范围或操作权限也可能变化；旧请求不得恢复已经失效的项目缓存。 */
function readProjectAccessKey(): string {
  const user = useSessionStore().currentUser
  return JSON.stringify([user?.principal_id, user?.project_ids, user?.scopes, user?.allowed_pages])
}

export const useProjectStore = defineStore('project', {
  state: () => ({
    projects: [] as ProjectCatalogItem[],
    selectedProjectId: getRuntimeConfig().defaultProjectId,
    selectedSummary: null as ProjectSummary | null,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    selectedProject: (state) => state.projects.find((project) => project.project_id === state.selectedProjectId) ?? null,
  },
  actions: {
    async loadProjects(options: LoadProjectsOptions = {}): Promise<void> {
      const accessKey = readProjectAccessKey()
      this.loading = true
      this.error = null
      try {
        const session = useSessionStore()
        if (!['datasets:read', 'models:read', 'workflows:read', 'tasks:read', 'datasets:write', 'workflows:write'].some(scope => session.hasScopes([scope]))) {
          this.projects = session.bootstrap?.visible_projects ?? []
          this.selectedSummary = null
          if (!this.projects.some((p) => p.project_id === this.selectedProjectId)) this.selectedProjectId = this.projects[0]?.project_id ?? ''
          return
        }
        const includeSummary = options.includeSummary ?? false
        const loadSelectedSummary = options.loadSelectedSummary ?? false
        const response = await listProjects({ includeSummary })
        if (readProjectAccessKey() !== accessKey) return
        // 首屏目录不是完整项目集合；保留分页范围外仍可访问的当前项目。
        if (response.pagination.hasMore && this.selectedProjectId && !response.items.some(item => item.project_id === this.selectedProjectId)) {
          try {
            const selected = await getProject(this.selectedProjectId)
            if (readProjectAccessKey() !== accessKey) return
            response.items.push(selected)
          } catch (error) {
            if (!(error instanceof ApiError) || ![403, 404].includes(error.status)) throw error
          }
        }
        if (readProjectAccessKey() !== accessKey) return
        this.projects = response.items
        if (!this.projects.some((project) => project.project_id === this.selectedProjectId)) {
          const defaultProjectId = getRuntimeConfig().defaultProjectId
          this.selectedProjectId = this.projects.find((project) => project.project_id === defaultProjectId)?.project_id
            ?? this.projects[0]?.project_id
            ?? ''
        }
        if (includeSummary) {
          this.selectedSummary = this.projects.find((project) => project.project_id === this.selectedProjectId)?.summary ?? null
        } else if (loadSelectedSummary && this.selectedProjectId) {
          await this.loadSummary(this.selectedProjectId)
        }
      } catch (error) {
        if (readProjectAccessKey() === accessKey) this.error = error instanceof Error ? error.message : translate('projects.listLoadFailed')
      } finally {
        if (readProjectAccessKey() === accessKey) this.loading = false
      }
    },
    async refreshAfterDeletion(projectId: string): Promise<void> {
      if (this.selectedProjectId === projectId) {
        this.selectedProjectId = ''
        this.selectedSummary = null
      }
      await this.loadProjects({ includeSummary: true })
      await useSessionStore().loadBootstrap({ includeDevices: false }).catch(() => undefined)
    },
    async loadSummary(projectId: string): Promise<void> {
      const session = useSessionStore()
      const accessKey = readProjectAccessKey()
      if (!session.hasScopes(['workflows:read', 'models:read', 'datasets:read', 'tasks:read']) || (session.currentUser?.allowed_pages != null && !['datasets', 'models', 'workflow-apps', 'deployments', 'tasks'].every(page => session.currentUser!.allowed_pages!.includes(page)))) { this.selectedSummary = null; return }
      const summary = await getProjectSummary(projectId)
      if (readProjectAccessKey() === accessKey && this.selectedProjectId === projectId) this.selectedSummary = summary
    },
    async selectProject(projectId: string): Promise<void> {
      this.selectedProjectId = projectId
      this.selectedSummary = null
      await this.loadSummary(projectId)
    },
    async bootstrapDefaultProject(): Promise<void> {
      await bootstrapProject({ project_id: getRuntimeConfig().defaultProjectId, display_name: translate('projects.defaultDisplayName') })
      await this.loadProjects()
      await useSessionStore().loadBootstrap({ includeDevices: false }).catch(() => undefined)
    },
    async createProject(input: ProjectBootstrapInput): Promise<void> {
      const project = await bootstrapProject(input)
      await this.loadProjects()
      await useSessionStore().loadBootstrap({ includeDevices: false }).catch(() => undefined)
      await this.selectProject(project.project_id)
    },
  },
})
