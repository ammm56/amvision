import type { RouteRecordRaw } from 'vue-router'
import './model-layout.css'

const ConversionTaskDetailPage = () => import('./pages/ConversionTaskDetailPage.vue')
const ModelOperationsPage = () => import('./pages/ModelOperationsPage.vue')
const TrainingTaskDetailPage = () => import('./pages/TrainingTaskDetailPage.vue')
const DetectionEvaluationDetailPage = () => import('./pages/DetectionEvaluationDetailPage.vue')
const ModelEvaluationDetailPage = () => import('./pages/ModelEvaluationDetailPage.vue')
const DenseEvaluationDetailPage = () => import('./pages/DenseEvaluationDetailPage.vue')

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
  {
    path: '/models/detection/evaluation-tasks/:taskId',
    component: DetectionEvaluationDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
  {
    path: '/models/:taskType(classification|segmentation|pose|obb)/evaluation-tasks/:taskId',
    component: ModelEvaluationDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
  {
    path: '/models/:taskType(semantic|anomaly)/evaluation-tasks/:taskId',
    component: DenseEvaluationDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
]
