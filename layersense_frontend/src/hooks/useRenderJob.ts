import { useEffect, useState } from 'react'

import { getRenderJob } from '../api'
import type { RenderJobSnapshot } from '../types'

const POLL_RETRY_DELAY_MS = 1000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

type UseRenderJobParams = {
  jobId: string | null
  initialJob: RenderJobSnapshot | null
}

type TrackedJob = { jobId: string; snapshot: RenderJobSnapshot }

export const useRenderJob = ({ jobId, initialJob }: UseRenderJobParams): RenderJobSnapshot | null => {
  const [trackedJob, setTrackedJob] = useState<TrackedJob | null>(null)

  const initialVersion = initialJob?.version
  const initialStatus = initialJob?.status
  const polledJob = trackedJob?.jobId === jobId ? trackedJob.snapshot : null

  useEffect(() => {
    if (!jobId || initialVersion === undefined || initialStatus === undefined) return

    let cancelled = false

    void (async () => {
      let current = { status: initialStatus, version: initialVersion }
      while (!cancelled && current.status !== 'succeeded' && current.status !== 'failed') {
        try {
          const next = await getRenderJob(jobId, { afterVersion: current.version, waitSeconds: 20 })
          if (cancelled) return
          current = next
          setTrackedJob({ jobId, snapshot: next })
        } catch {
          if (cancelled) return
          await sleep(POLL_RETRY_DELAY_MS)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [jobId, initialStatus, initialVersion])

  return polledJob
}
