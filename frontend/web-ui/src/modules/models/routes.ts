import type { RouteRecordRaw } from 'vue-router'

const ConversionTaskDetailPage = () => import('./pages/ConversionTaskDetailPage.vue')
const ModelOperationsPage = () => import('./pages/ModelOperationsPage.vue')
const TrainingTaskDetailPage = () => import('./pages/TrainingTaskDetailPage.vue')

export const modelRoutes: RouteRecordRaw[] = [
  {
    path: '/models',
    component: ModelOperationsPage,
    meta: { requiredScopes: ['models:read', 'tasks:read'] },
  },
  {
    path: '/models/:taskType/training-tasks/:taskId',
    component: TrainingTaskDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
  {
    path: '/models/:taskType/conversion-tasks/:taskId',
    component: ConversionTaskDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
]
