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
    let timer: number | undefined;
    const jobId = job.id;
    const poll = async () => {
      try {
        const { job: next } = await fetchJob(jobId);
        if (!active) return;
        setJob(next);
        if (!TERMINAL.has(next.status)) {
          timer = window.setTimeout(poll, 2000);
        }
      } catch (error) {
        if (!active) return;
        onError?.((error as Error).message);
        timer = window.setTimeout(poll, 4000);
      }
    };
    timer = window.setTimeout(poll, 2000);
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [job?.id]);

  return { job, setJob };
}
