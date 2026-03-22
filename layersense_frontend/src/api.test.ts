import { describe, expect, it, vi, afterEach } from 'vitest'

import { createAnimation, queueRender } from './api'

describe('api client', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('createAnimation posts to agent and returns conversation data', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ conversation_id: 'conv-123', scene_path: '/tmp/scene.py' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )

    const response = await createAnimation({
      prompt: 'animate a circle',
      scene: { elements: [], appState: {}, files: {} },
    })

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/api/v1/animation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: 'animate a circle', scene: { elements: [], appState: {}, files: {} } }),
    })
    expect(response).toEqual({ conversation_id: 'conv-123', scene_path: '/tmp/scene.py' })
  })

  it('queueRender posts to controller and returns status', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'queued' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )

    const response = await queueRender({ scene_path: '/tmp/scene.py', conversation_id: 'conv-123' })

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8001/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scene_path: '/tmp/scene.py', conversation_id: 'conv-123' }),
    })
    expect(response).toEqual({ status: 'queued' })
  })

  it('createAnimation maps non-2xx responses to errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'bad request' }), {
        status: 400,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await expect(
      createAnimation({ prompt: 'animate', scene: { elements: [], appState: {}, files: {} } }),
    ).rejects.toThrow('POST http://localhost:8000/api/v1/animation failed (400): bad request')
  })

  it('queueRender maps non-2xx responses to errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('internal error', {
        status: 500,
        headers: { 'content-type': 'text/plain' },
      }),
    )

    await expect(
      queueRender({ scene_path: '/tmp/scene.py', conversation_id: 'conv-123' }),
    ).rejects.toThrow('POST http://localhost:8001/render failed (500): internal error')
  })
})
