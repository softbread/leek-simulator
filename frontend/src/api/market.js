import service from './index'

export const uploadMarketDocuments = async (files) => {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return service.post('/api/market/uploads', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export const getXueqiuAuthStatus = async () => {
  return service.get('/api/market/xueqiu/auth/status')
}

export const startXueqiuAuth = async () => {
  return service.post('/api/market/xueqiu/auth/start')
}

export const completeXueqiuAuth = async () => {
  return service.post('/api/market/xueqiu/auth/complete')
}

export const logoutXueqiuAuth = async () => {
  return service.post('/api/market/xueqiu/auth/logout')
}

export const createMarketRun = async (payload) => {
  return service.post('/api/market/runs', payload)
}

export const listMarketRuns = async () => {
  return service.get('/api/market/runs')
}

export const getMarketRun = async (runId) => {
  return service.get(`/api/market/runs/${runId}`)
}

export const buildMarketWorld = async (runId) => {
  return service.post(`/api/market/runs/${runId}/build-world`)
}

export const prepareMarketRun = async (runId) => {
  return service.post(`/api/market/runs/${runId}/prepare`)
}

export const startMarketRun = async (runId) => {
  return service.post(`/api/market/runs/${runId}/start`)
}

export const getMarketRunStatus = async (runId) => {
  return service.get(`/api/market/runs/${runId}/status`)
}

export const getMarketRunResults = async (runId) => {
  return service.get(`/api/market/runs/${runId}/results`)
}

export const chatWithMarketAnalyst = async (runId, message) => {
  return service.post(`/api/market/runs/${runId}/chat`, { message })
}
