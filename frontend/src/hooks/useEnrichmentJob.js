import { useCallback, useEffect, useRef, useState } from 'react'
import { getJobStatus, startEnrichment } from '../lib/api'

// Polling rather than SSE/WebSocket: the backend is single-process uvicorn on
// the seller's own machine, the job takes minutes, and a 1.5s poll is both
// adequate and far less to maintain than a streaming transport.
const POLL_MS = 1500

// A dead backend would otherwise leave the UI polling forever. At 1.5s this is
// ~30 minutes, comfortably longer than a large catalog takes.
const MAX_POLLS = 1200

/**
 * Drives a background enrichment job and exposes its live progress.
 *
 * Returns { job, running, error, start, reset } where `job` carries
 * { stage, message, progress, total, done, ok, result }.
 */
export default function useEnrichmentJob({ onComplete } = {}) {
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)

  const timerRef = useRef(null)
  const pollsRef = useRef(0)
  const cancelledRef = useRef(false)
  // Held in a ref so changing the callback does not restart polling.
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // Unmounting mid-job must not leave a timer writing to dead state. The job
  // itself keeps running on the server and can be polled again later.
  useEffect(() => {
    cancelledRef.current = false
    return () => {
      cancelledRef.current = true
      stopTimer()
    }
  }, [stopTimer])

  const poll = useCallback(
    async (jobId) => {
      if (cancelledRef.current) return

      if (pollsRef.current++ > MAX_POLLS) {
        setError('Analysis is taking longer than expected. Check the backend logs.')
        setRunning(false)
        return
      }

      try {
        const { data } = await getJobStatus(jobId)
        if (cancelledRef.current) return
        setJob(data)

        if (data.done) {
          setRunning(false)
          if (data.ok) {
            onCompleteRef.current?.(data)
          } else {
            setError(data.error || 'Analysis failed.')
          }
          return
        }
        timerRef.current = setTimeout(() => poll(jobId), POLL_MS)
      } catch (err) {
        if (cancelledRef.current) return
        setError(err.message || 'Lost contact with the server.')
        setRunning(false)
      }
    },
    [],
  )

  const start = useCallback(async () => {
    stopTimer()
    pollsRef.current = 0
    setError(null)
    setJob(null)
    setRunning(true)
    try {
      const initial = await startEnrichment()
      if (cancelledRef.current) return
      setJob(initial)
      poll(initial.job_id)
    } catch (err) {
      setError(err.message || 'Could not start analysis.')
      setRunning(false)
    }
  }, [poll, stopTimer])

  const reset = useCallback(() => {
    stopTimer()
    setJob(null)
    setError(null)
    setRunning(false)
  }, [stopTimer])

  return { job, running, error, start, reset }
}
