import type { RouteRecordRaw } from 'vue-router'

import TaskDetailPage from './pages/TaskDetailPage.vue'
import TaskListPage from './pages/TaskListPage.vue'

export const taskRoutes: RouteRecordRaw[] = [
  {
    path: '/tasks',
    component: TaskListPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
  {
    path: '/tasks/:taskId',
    component: TaskDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
]