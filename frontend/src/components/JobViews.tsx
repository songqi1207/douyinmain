import { Bell, BellRing, Check, ChevronDown, ChevronUp, Circle, Clock3, Download, LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { fetchJobLogs } from "../api";
import type { Job, JobLogEntry } from "../types";
import { VideoPreview, videoOrientationHint } from "./VideoPreview";
import {
  JOB_NOTIFICATIONS_ENABLED_KEY,
  JOB_NOTIFICATIONS_REQUEST_EVENT,
  JOB_NOTIFICATIONS_STATE_EVENT,
} from "./JobNotifications";

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "等待执行",
  running: "正在生成内容",
  rendering: "正在通过剪映渲染",
  succeeded: "生成完成",
  failed: "生成失败",
};

const PHASES = [
  { label: "排队", threshold: 0 },
  { label: "内容生成", threshold: 15 },
  { label: "草稿生成", threshold: 45 },
  { label: "剪映渲染", threshold: 70 },
  { label: "完成", threshold: 100 },
];

const STAGE_TEXT: Record<string, string> = {
  waiting_for_device: "等待本机导出助手领取",
  device_rendering: "本机助手正在处理剪映导出",
  device_preparing: "助手正在接收任务数据",
  device_importing: "正在写入本机剪映草稿",
  device_draft_ready: "本机剪映草稿已经写入",
  device_preparing_resources: "正在准备字体与特效资源",
  device_opening_jianying: "正在打开剪映草稿",
  device_exporting: "剪映正在导出视频",
  device_uploading: "正在回传并处理视频",
};

const ACTIVE_STATUSES = new Set<Job["status"]>(["queued", "running", "rendering"]);

function formatElapsed(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return minutes > 0 ? `${minutes} 分 ${remainder} 秒` : `${remainder} 秒`;
}

export function JobProgress({
  job,
  onRetry,
  retrying = false,
}: {
  job: Job;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const active = ACTIVE_STATUSES.has(job.status);
  const [now, setNow] = useState(() => Date.now());
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => localStorage.getItem(JOB_NOTIFICATIONS_ENABLED_KEY) === "true",
  );

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, job.id]);

  useEffect(() => {
    const sync = () => setNotificationsEnabled(
      localStorage.getItem(JOB_NOTIFICATIONS_ENABLED_KEY) === "true",
    );
    window.addEventListener(JOB_NOTIFICATIONS_STATE_EVENT, sync);
    return () => window.removeEventListener(JOB_NOTIFICATIONS_STATE_EVENT, sync);
  }, []);

  let progressPhase = 0;
  PHASES.forEach((phase, index) => {
    if (job.progress >= phase.threshold) progressPhase = index;
  });
  const activePhase = job.status === "succeeded" ? PHASES.length - 1 : progressPhase;
  return (
    <section className="job-panel" aria-live="polite" aria-label="任务执行进度">
      <div className="job-heading">
        <div><span className={`status-dot ${job.status}`} />{STATUS_TEXT[job.status]}</div>
        <strong>{job.progress}%</strong>
      </div>
      <div className="progress-track" aria-hidden="true"><i style={{ width: `${job.progress}%` }} /></div>
      {job.billing && <div className={`job-billing-summary ${job.billing.status}`}>
        <span>{job.billing.status === "charged" ? "本次已扣积分" : job.billing.status === "refunded" ? "本次已退积分" : "本次冻结积分"}</span>
        <strong>{job.billing.status === "charged" ? job.billing.charged_points : job.billing.status === "refunded" ? job.billing.refunded_points : job.billing.reserved_points} 积分</strong>
        <small>{job.billing.status === "charged" ? "成功任务正式扣除" : job.billing.status === "refunded" ? "失败任务自动退回" : "任务完成后结算"}</small>
      </div>}
      <ol className="job-phases">
        {PHASES.map((phase, index) => {
          const done = job.status === "succeeded" || index < activePhase;
          const active = index === activePhase && job.status !== "failed";
          return (
            <li className={done ? "done" : active ? "active" : ""} key={phase.label}>
              <span>{done ? <Check /> : active ? <LoaderCircle className="spin" /> : <Circle />}</span>
              {phase.label}
            </li>
          );
        })}
      </ol>
      <p>{STAGE_TEXT[job.stage] || job.stage}</p>
      {active && (
        <div className="job-background-status">
          <span className="job-background-icon"><LoaderCircle className="spin" /></span>
          <div>
            <strong>任务正在后台持续处理</strong>
            <p>可以离开当前页面，任务不会中断；浏览器保持打开，完成后会通知你。</p>
            <small><Clock3 />已处理 {formatElapsed(now / 1000 - job.created_at)}</small>
          </div>
          <button
            className={notificationsEnabled ? "active" : ""}
            type="button"
            disabled={notificationsEnabled}
            onClick={() => window.dispatchEvent(new Event(JOB_NOTIFICATIONS_REQUEST_EVENT))}
          >
            {notificationsEnabled ? <BellRing /> : <Bell />}
            {notificationsEnabled ? "完成通知已开启" : "完成后通知我"}
          </button>
        </div>
      )}
      <JobLogs key={job.id} job={job} />
      {job.error && <div className="notice error">{job.error.message}</div>}
      {job.status === "failed" && onRetry && (
        <button className="secondary-button" disabled={retrying} type="button" onClick={onRetry}>
          <RotateCcw size={15} />{retrying ? "正在重试" : "安全重试"}
        </button>
      )}
    </section>
  );
}

function formatLogTime(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleTimeString("zh-CN", { hour12: false });
}

export function JobLogs({ job }: { job: Job }) {
  const [logs, setLogs] = useState<JobLogEntry[]>([]);
  const [open, setOpen] = useState(true);
  const afterIdRef = useRef(0);
  const bodyRef = useRef<HTMLDivElement>(null);
  const active = ACTIVE_STATUSES.has(job.status);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = async () => {
      try {
        const { items } = await fetchJobLogs(job.id, afterIdRef.current);
        if (cancelled) return;
        if (items.length > 0) {
          afterIdRef.current = items[items.length - 1].id;
          setLogs((previous) => [...previous, ...items]);
        }
      } catch {
        // 日志拉取失败时静默重试，不打断任务进度展示
      }
      if (!cancelled && active) timer = window.setTimeout(load, 3000);
    };
    load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [job.id, active]);

  useEffect(() => {
    if (open && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [logs, open]);

  if (logs.length === 0) return null;
  return (
    <div className="job-logs">
      <button className="job-logs-toggle" type="button" onClick={() => setOpen(!open)}>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        详细日志（{logs.length} 条）
      </button>
      {open && (
        <div className="job-logs-body" ref={bodyRef}>
          {logs.map((log) => (
            <div className={`job-log-line ${log.level}`} key={log.id}>
              <time>{formatLogTime(log.created_at)}</time>
              <span>{log.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Results({ job, compact = false }: { job: Job; compact?: boolean }) {
  if (job.status !== "succeeded") return null;
  return (
    <section className={`result-panel ${compact ? "compact" : ""}`}>
      <div className="section-title">
        <span>生成结果</span>
        <small>任务已安全保存到创作记录</small>
      </div>
      <div className={`result-grid ${job.results.length === 1 ? "single" : ""}`}>
        {job.results.map((result, index) => (
          <article className="result-item" key={`${result.url}-${index}`}>
            {result.type === "image" ? (
              <img src={result.url} alt={`${job.display_title} 生成结果 ${index + 1}`} />
            ) : result.type === "video" ? (
              <VideoPreview jobId={job.id} result={result} orientationHint={videoOrientationHint(job.workflow_code)} />
            ) : (
              <div className="draft-result">
                <Sparkles />
                <strong>{result.format === "draft_key" ? "剪映草稿已生成" : "工作流文件已生成"}</strong>
              </div>
            )}
            <div className="result-actions">
              <span>结果 {index + 1}</span>
              <a href={result.download_url || result.url} target="_blank" rel="noreferrer" download={result.downloadable || undefined}>
                <Download size={14} />{result.type === "video" ? "下载视频" : "打开 / 下载"}
              </a>
            </div>
          </article>
        ))}
      </div>
      <div className="result-footer">
        <Link to="/records">查看全部创作记录</Link>
      </div>
    </section>
  );
}
