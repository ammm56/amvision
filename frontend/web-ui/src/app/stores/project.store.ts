import { defineStore } from 'pinia'

import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import type { ProjectCatalogItem, ProjectSummary } from '@/shared/contracts'
import { bootstrapProject, getProjectSummary, listProjects } from '@/modules/projects/services/project.service'

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
        this.error = error instanceof Error ? error.message : 'Project 列表加载失败'
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
      await bootstrapProject({ project_id: getRuntimeConfig().defaultProjectId, display_name: '默认项目' })
      await this.loadProjects()
    },
  },
})