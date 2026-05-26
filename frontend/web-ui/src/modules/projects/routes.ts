import type { RouteRecordRaw } from 'vue-router'

import ProjectListPage from './pages/ProjectListPage.vue'

export const projectRoutes: RouteRecordRaw[] = [
  {
    path: '/projects',
    component: ProjectListPage,
    meta: { requiredScopes: ['workflows:read', 'models:read'] },
  },
]