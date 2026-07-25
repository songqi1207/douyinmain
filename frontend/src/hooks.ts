import { useEffect, useState } from "react";

import { fetchJob } from "./api";
import type { Job } from "./types";

const TERMINAL = new Set<Job["status"]>(["succeeded", "failed"]);

export function useJobPolling(
  initialJob: Job | null,
  onError?: (message: string) => void,
) {
  const [job, setJob] = useState<Job | null>(initialJob);

  useEffect(() => setJob(initialJob), [initialJob?.id]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      fetchJob(job.id)
        .then(({ job: next }) => active && setJob(next))
        .catch((error: Error) => active && onError?.(error.message));
    }, 2000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [job?.id, job?.status, job?.updated_at]);

  return { job, setJob };
}
