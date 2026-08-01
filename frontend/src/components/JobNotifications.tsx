import { Bell, BellOff, Check, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { fetchJobs } from "../api";
import { useAuth } from "../auth";
import type { Job } from "../types";

const ENABLED_KEY = "job-notifications-enabled";
const TERMINAL = new Set<Job["status"]>(["succeeded", "failed"]);

function notificationText(job: Job) {
  if (job.status === "succeeded") {
    return { title: "视频已生成完成", body: `${job.display_title || "创作任务"} 已完成，可以查看或下载视频。` };
  }
  return { title: "视频生成失败", body: `${job.display_title || "创作任务"} 处理失败，请打开创作记录查看原因。` };
}

export function JobNotifications() {
  const { user } = useAuth();
  const [enabled, setEnabled] = useState(() => localStorage.getItem(ENABLED_KEY) === "true");
  const [toast, setToast] = useState<{ kind: "success" | "error"; title: string; body: string } | null>(null);
  const statuses = useRef(new Map<string, Job["status"]>());
  const initialized = useRef(false);
  const watcherStartedAt = useRef(Date.now() / 1000);
  const toastTimer = useRef<number | undefined>(undefined);

  function showToast(job: Job) {
    const message = notificationText(job);
    setToast({ kind: job.status === "succeeded" ? "success" : "error", ...message });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 8000);

    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    try {
      const notification = new Notification(message.title, {
        body: message.body,
        tag: `workflow-job-${job.id}`,
      });
      notification.onclick = () => {
        window.focus();
        window.location.assign("/business/records");
        notification.close();
      };
    } catch {
      // The in-page toast remains available when the OS notification fails.
    }
  }

  useEffect(() => {
    statuses.current.clear();
    initialized.current = false;
    watcherStartedAt.current = Date.now() / 1000;
  }, [user?.id]);

  useEffect(() => {
    if (!user || !enabled) return;
    let active = true;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const { items } = await fetchJobs({ page: 1, pageSize: 50 });
        if (!active) return;
        for (const job of items) {
          const previous = statuses.current.get(job.id);
          const becameTerminal = previous && !TERMINAL.has(previous) && TERMINAL.has(job.status);
          const completedBetweenPolls = !previous
            && TERMINAL.has(job.status)
            && job.created_at >= watcherStartedAt.current;
          if (initialized.current && (becameTerminal || completedBetweenPolls)) {
            showToast(job);
          }
          statuses.current.set(job.id, job.status);
        }
        initialized.current = true;
      } catch {
        // A temporary polling failure must not disable notifications.
      } finally {
        if (active) timer = window.setTimeout(poll, 5000);
      }
    };

    void poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [user?.id, enabled]);

  useEffect(() => () => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
  }, []);

  async function toggle() {
    if (enabled) {
      localStorage.setItem(ENABLED_KEY, "false");
      setEnabled(false);
      return;
    }
    if (typeof Notification === "undefined") {
      setToast({ kind: "error", title: "无法开启通知", body: "当前浏览器不支持系统通知。" });
      return;
    }
    const permission = Notification.permission === "default"
      ? await Notification.requestPermission()
      : Notification.permission;
    if (permission !== "granted") {
      setToast({ kind: "error", title: "通知未开启", body: "浏览器已阻止通知，请在网站权限中允许通知。" });
      return;
    }
    localStorage.setItem(ENABLED_KEY, "true");
    setEnabled(true);
    setToast({ kind: "success", title: "任务通知已开启", body: "视频完成或失败时会立即提醒你。" });
  }

  if (!user) return null;

  return (
    <>
      <button
        className={`job-notification-toggle ${enabled ? "active" : ""}`}
        type="button"
        onClick={() => void toggle()}
        aria-label={enabled ? "关闭任务通知" : "开启任务通知"}
        title={enabled ? "任务通知已开启" : "开启任务完成通知"}
      >
        {enabled ? <Bell size={15} /> : <BellOff size={15} />}
        <span>{enabled ? "通知已开" : "开启通知"}</span>
      </button>
      {toast && (
        <aside className={`job-notification-toast ${toast.kind}`} role="status" aria-live="polite">
          <span>{toast.kind === "success" ? <Check /> : <Bell />}</span>
          <div><strong>{toast.title}</strong><p>{toast.body}</p></div>
          <button type="button" onClick={() => setToast(null)} aria-label="关闭通知"><X /></button>
        </aside>
      )}
    </>
  );
}
