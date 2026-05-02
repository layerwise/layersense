import { useEffect, useState } from 'react'

import { getRenderJob } from '../api'
import type { RenderJobSnapshot } from '../types'

const POLL_RETRY_DELAY_MS = 1000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

type UseRenderJobParams = {
  jobId: string | null
  initialJob: RenderJobSnapshot | null
}

export const useRenderJob = ({ jobId, initialJob }: UseRenderJobParams): RenderJobSnapshot | null => {
  const [job, setJob] = useState<RenderJobSnapshot | null>(initialJob)

  const initialVersion = initialJob?.version
  const initialStatus = initialJob?.status

  useEffect(() => {
    if (!jobId || !initialJob) return

    setJob((currentJob) => {
      if (currentJob?.job_id === initialJob.job_id && currentJob.version >= initialJob.version) {
        return currentJob
      }
      return initialJob
    })

    let cancelled = false

    void (async () => {
      let current = initialJob
      while (!cancelled && current.status !== 'succeeded' && current.status !== 'failed') {
        try {
          const next = await getRenderJob(jobId, { afterVersion: current.version, waitSeconds: 20 })
          if (cancelled) return
          current = next
          setJob(next)
        } catch {
          if (cancelled) return
          await sleep(POLL_RETRY_DELAY_MS)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [jobId, initialVersion, initialStatus])

  return job
}
