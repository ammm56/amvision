import type { RouteRecordRaw } from 'vue-router'

const TaskDetailPage = () => import('./pages/TaskDetailPage.vue')
const TaskListPage = () => import('./pages/TaskListPage.vue')

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
