import { describe, expect, it, vi, afterEach } from 'vitest'

import { createAnimation, getRenderJob, queueRender } from './api'

describe('api client', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('createAnimation posts to agent and returns conversation data', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ conversation_id: 'conv-123', source_code: 'code', content_hash: 'hash' }), {
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
    expect(response).toEqual({ conversation_id: 'conv-123', source_code: 'code', content_hash: 'hash' })
  })

  it('queueRender posts to controller and returns a job snapshot', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: 'job-123',
          job: {
            job_id: 'job-123',
            conversation_id: 'conv-123',
            status: 'queued',
            version: 1,
            preview_url: null,
            final_url: null,
            error: null,
            stderr: null,
          },
        }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )

    const response = await queueRender({
      source_code: 'code', content_hash: 'hash',
      conversation_id: 'conv-123',
      cli_flags: { quality: 'm' },
    })

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8001/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_code: 'code', content_hash: 'hash',
        conversation_id: 'conv-123',
        cli_flags: { quality: 'm' },
      }),
    })
    expect(response.job_id).toBe('job-123')
    expect(response.job.status).toBe('queued')
  })

  it('getRenderJob requests the controller job endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          job_id: 'job-123',
          conversation_id: 'conv-123',
          status: 'waiting_for_final',
          version: 2,
          preview_url: '/artifacts/by-hash/hash/preview',
          final_url: null,
          error: null,
          stderr: null,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )

    const response = await getRenderJob('job-123', { afterVersion: 1, waitSeconds: 20 })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/render-jobs/job-123?after_version=1&wait_seconds=20',
      { method: 'GET' },
    )
    expect(response.status).toBe('waiting_for_final')
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
      queueRender({ source_code: 'code', content_hash: 'hash', conversation_id: 'conv-123', cli_flags: {} }),
    ).rejects.toThrow('POST http://localhost:8001/render failed (500): internal error')
  })
})
