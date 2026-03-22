import type {
  AnimationRequest,
  AnimationResponse,
  RenderQueueRequest,
  RenderQueueResponse,
} from './types'

export const AGENT_BASE = 'http://localhost:8000'
export const CONTROLLER_BASE = 'http://localhost:8001'

const parseErrorBody = async (response: Response): Promise<string> => {
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    const data = (await response.json()) as { detail?: string; error?: string }
    return data.detail ?? data.error ?? 'request failed'
  }

  const text = await response.text()
  return text || 'request failed'
}

const parseJsonResponse = async <T>(response: Response, url: string): Promise<T> => {
  if (!response.ok) {
    const message = await parseErrorBody(response)
    throw new Error(`POST ${url} failed (${response.status}): ${message}`)
  }

  return (await response.json()) as T
}

export const createAnimation = async (payload: AnimationRequest): Promise<AnimationResponse> => {
  const url = `${AGENT_BASE}/api/v1/animation`
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  return parseJsonResponse<AnimationResponse>(response, url)
}

export const queueRender = async (payload: RenderQueueRequest): Promise<RenderQueueResponse> => {
  const url = `${CONTROLLER_BASE}/render`
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  return parseJsonResponse<RenderQueueResponse>(response, url)
}
