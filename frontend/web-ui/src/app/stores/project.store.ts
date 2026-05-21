import { defineStore } from 'pinia'

import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import type { ProjectCatalogItem, ProjectSummary } from '@/shared/contracts'
import { bootstrapProject, getProjectSummary, listProjects, type ProjectBootstrapInput } from '@/modules/projects/services/project.service'
import { translate } from '@/platform/i18n'

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
    async loadProjects(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await listProjects({ includeSummary: true })
        this.projects = response.items
        if (!this.projects.some((project) => project.project_id === this.selectedProjectId)) {
          this.selectedProjectId = this.projects[0]?.project_id ?? getRuntimeConfig().defaultProjectId
        }
        if (this.selectedProjectId) {
          await this.loadSummary(this.selectedProjectId)
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : translate('projects.listLoadFailed')
      } finally {
        this.loading = false
      }
    },
    async loadSummary(projectId: string): Promise<void> {
      this.selectedSummary = await getProjectSummary(projectId)
    },
    async selectProject(projectId: string): Promise<void> {
      this.selectedProjectId = projectId
      await this.loadSummary(projectId)
    },
    async bootstrapDefaultProject(): Promise<void> {
      await bootstrapProject({ project_id: getRuntimeConfig().defaultProjectId, display_name: translate('projects.defaultDisplayName') })
      await this.loadProjects()
    },
    async createProject(input: ProjectBootstrapInput): Promise<void> {
      const project = await bootstrapProject(input)
      await this.loadProjects()
      await this.selectProject(project.project_id)
    },
  },
})