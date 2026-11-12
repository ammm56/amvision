import type { RouteRecordRaw } from 'vue-router'

const ProjectListPage = () => import('./pages/ProjectListPage.vue')

export const projectRoutes: RouteRecordRaw[] = [
  { path: '/projects/:projectId', component: () => import('./pages/ProjectOverviewPage.vue') },
  {
    path: '/projects',
    component: ProjectListPage,
  },
]
