import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useRenderJob } from './useRenderJob'

const mockGetRenderJob = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, getRenderJob: (...args: unknown[]) => mockGetRenderJob(...args) }
})

describe('useRenderJob', () => {
  afterEach(() => {
    mockGetRenderJob.mockReset()
    vi.useRealTimers()
  })

  it('polls with afterVersion and updates snapshot', async () => {
    const initialJob = {
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'queued',
      version: 1,
      preview_url: null,
      final_url: null,
      error: null,
      stderr: null,
    } as const

    mockGetRenderJob.mockImplementation(async () => ({
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'succeeded',
      version: 2,
      preview_url: '/preview.mp4',
      final_url: '/final.mp4',
      error: null,
      stderr: null,
    }))

    const { result, unmount } = renderHook(() =>
      useRenderJob({
        jobId: 'job-1',
        initialJob,
      }),
    )

    await waitFor(() => expect(result.current?.version).toBe(2))
    expect(mockGetRenderJob).toHaveBeenCalledWith('job-1', { afterVersion: 1, waitSeconds: 20 })
    unmount()
  })

  it('retries after a transient polling error', async () => {
    vi.useFakeTimers()
    const initialJob = {
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'queued',
      version: 1,
      preview_url: null,
      final_url: null,
      error: null,
      stderr: null,
    } as const
    let attempts = 0
    mockGetRenderJob.mockImplementation(async () => {
      attempts += 1
      if (attempts === 1) {
        throw new Error('temporary network error')
      }

      return {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'succeeded',
        version: 2,
        preview_url: '/preview.mp4',
        final_url: '/final.mp4',
        error: null,
        stderr: null,
      }
    })

    const { result, unmount } = renderHook(() =>
      useRenderJob({
        jobId: 'job-1',
        initialJob,
      }),
    )

    await act(async () => {
      await Promise.resolve()
    })
    expect(mockGetRenderJob).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(mockGetRenderJob).toHaveBeenCalledTimes(2)
    expect(result.current?.version).toBe(2)
    unmount()
  })

  it('does not restart polling when the same job snapshot is re-created by value', async () => {
    const currentJob = {
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'queued',
      version: 1,
      preview_url: null,
      final_url: null,
      error: null,
      stderr: null,
    } as const

    mockGetRenderJob.mockImplementation(async () => ({
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'succeeded',
      version: 2,
      preview_url: '/preview.mp4',
      final_url: '/final.mp4',
      error: null,
      stderr: null,
    }))

    const { rerender, unmount } = renderHook(
      ({ initialJob }) =>
        useRenderJob({
          jobId: 'job-1',
          initialJob,
        }),
      {
        initialProps: { initialJob: currentJob },
      },
    )

    await waitFor(() => expect(mockGetRenderJob).toHaveBeenCalledTimes(1))

    rerender({
      initialJob: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'queued',
        version: 1,
        preview_url: null,
        final_url: null,
        error: null,
        stderr: null,
      },
    })

    await waitFor(() => expect(mockGetRenderJob).toHaveBeenCalledTimes(1))
    unmount()
  })
})
