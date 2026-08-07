import { Check, Clipboard, Download, Laptop, Link2, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  ApiError,
  createRenderDevicePairingCode,
  fetchDraftKeyRenderStatus,
  revokeRenderDevice,
} from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";
import type { RenderStatus } from "../types";

const EMPTY_STATUS: RenderStatus = {
  configured: false,
  device_online: false,
  central_configured: false,
  devices: [],
  message: "正在检查设备",
};

function capabilityText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

type HelperUpdateProgress = {
  percent: number;
  phase: string;
  running: boolean;
  startedAt: number;
  targetVersion: string;
};

function updateProgressAt(elapsedSeconds: number): Pick<HelperUpdateProgress, "percent" | "phase" | "running"> {
  if (elapsedSeconds < 4) {
    return { percent: 8 + Math.round(elapsedSeconds * 3), phase: "正在唤醒本机助手", running: true };
  }
  if (elapsedSeconds < 45) {
    return {
      percent: Math.min(75, 20 + Math.round((elapsedSeconds - 4) * 1.35)),
      phase: "正在下载最新版助手",
      running: true,
    };
  }
  if (elapsedSeconds < 80) {
    return {
      percent: Math.min(92, 76 + Math.round((elapsedSeconds - 45) * 0.45)),
      phase: "正在安装并重启助手",
      running: true,
    };
  }
  if (elapsedSeconds < 100) {
    return { percent: 95, phase: "正在等待新版助手重新连接", running: true };
  }
  return {
    percent: 95,
    phase: "新版助手未重新连接，请点击下方“下载安装包”并运行一次",
    running: false,
  };
}

function jianyingStatus(capabilities: Record<string, unknown>): string {
  const version = capabilityText(capabilities.jianying_version);
  if (version) return `剪映 v${version}`;
  if (capabilities.jianying_found === false) return "未检测到剪映";
  if (capabilities.jianying_found === true) return "已检测到剪映（版本未知）";
  return "剪映版本等待助手上报";
}

export function DevicesPage() {
  const { tr } = usePreferences();
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<RenderStatus>(EMPTY_STATUS);
  const [pairing, setPairing] = useState<{ code: string; expires_at: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [helperUpdate, setHelperUpdate] = useState<HelperUpdateProgress | null>(null);
  const latestHelperVersion = capabilityText(status.latest_helper_version);
  const helperRecoveryRequired = status.devices.length > 0 && !status.device_online;
  const helperDownloadUrl = `/api/v1/downloads/draft-bridge${latestHelperVersion ? `?v=${encodeURIComponent(latestHelperVersion)}` : ""}`;
  const helperRedownloadUrl = `${helperDownloadUrl}${helperDownloadUrl.includes("?") ? "&" : "?"}download=again`;

  async function refresh() {
    try {
      setStatus(await fetchDraftKeyRenderStatus());
    } catch (nextError) {
      setError((nextError as Error).message);
    }
  }

  useEffect(() => {
    if (loading) return;
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/devices")}`);
      return;
    }
    if (user.must_change_password) {
      navigate("/account/security");
      return;
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [loading, user?.id, user?.must_change_password]);

  useEffect(() => {
    if (!helperUpdate?.running) return;
    const timer = window.setInterval(() => {
      setHelperUpdate((current) => {
        if (!current?.running) return current;
        const elapsedSeconds = (Date.now() - current.startedAt) / 1000;
        return { ...current, ...updateProgressAt(elapsedSeconds) };
      });
    }, 500);
    return () => window.clearInterval(timer);
  }, [helperUpdate?.startedAt, helperUpdate?.running]);

  useEffect(() => {
    if (!helperUpdate?.running || !helperUpdate.targetVersion) return;
    const updatedDevice = status.devices.find((device) => (
      device.online
      && capabilityText(device.capabilities.helper_version) === helperUpdate.targetVersion
    ));
    if (!updatedDevice) return;
    setHelperUpdate((current) => current ? {
      ...current,
      percent: 100,
      phase: `更新完成，助手 v${current.targetVersion} 已重新连接`,
      running: false,
    } : current);
    setMessage(`AI 视频创作助手已更新到 v${helperUpdate.targetVersion} 并重新上线`);
  }, [helperUpdate?.running, helperUpdate?.targetVersion, status.devices]);

  async function createPairing() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const next = await createRenderDevicePairingCode();
      setPairing(next);
      wakeHelper(next.code);
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "password_change_required") navigate("/account/security");
      else setError(apiError.message);
    } finally {
      setBusy(false);
    }
  }

  function wakeHelper(pairingCode = pairing?.code) {
    const query = new URLSearchParams({ site: window.location.origin });
    if (pairingCode) query.set("code", pairingCode);
    const launcher = document.createElement("iframe");
    launcher.style.display = "none";
    launcher.src = `douyin-draft://wake?${query.toString()}`;
    document.body.appendChild(launcher);
    window.setTimeout(() => launcher.remove(), 1500);
    setMessage(pairingCode ? "正在后台唤醒并连接助手" : "已尝试唤醒助手，正在等待设备上线");
  }

  function updateHelper() {
    if (helperRecoveryRequired || (helperUpdate?.percent === 95 && !helperUpdate.running)) {
      window.location.href = helperDownloadUrl;
      setMessage("安装包已开始下载。下载完成后请双击运行，无需卸载旧版或重新配对。");
      return;
    }
    const query = new URLSearchParams({ site: window.location.origin });
    const onlineCurrent = status.devices.some((device) => (
      device.online
      && latestHelperVersion
      && capabilityText(device.capabilities.helper_version) === latestHelperVersion
    ));
    if (onlineCurrent) {
      setHelperUpdate({
        percent: 100,
        phase: `当前已是最新版 v${latestHelperVersion}`,
        running: false,
        startedAt: Date.now(),
        targetVersion: latestHelperVersion,
      });
      setMessage(`当前助手已经是最新版 v${latestHelperVersion}`);
      return;
    }
    setError("");
    setHelperUpdate({
      percent: 8,
      phase: "正在唤醒本机助手",
      running: true,
      startedAt: Date.now(),
      targetVersion: latestHelperVersion,
    });
    window.location.href = `douyin-draft://update?${query.toString()}`;
    setMessage(
      "正在打开 AI 视频创作助手。请在浏览器询问时选择“打开”；更新完成约需 1 分钟。"
      + "若版本仍未变化，请点击下方“下载安装包”并运行一次。",
    );
  }

  function calibrateHelper() {
    const query = new URLSearchParams({ site: window.location.origin });
    window.location.href = `douyin-draft://calibrate?${query.toString()}`;
    setMessage("正在打开助手的剪映导出按钮校准界面…");
  }

  async function copyPairing() {
    if (!pairing) return;
    await navigator.clipboard.writeText(pairing.code);
    setMessage("配对码已复制");
  }

  async function removeDevice(deviceId: string) {
    setError("");
    try {
      await revokeRenderDevice(deviceId);
      setMessage("设备已解除");
      await refresh();
    } catch (nextError) {
      setError((nextError as Error).message);
    }
  }

  return (
    <Layout>
      <main className="content-page page-width devices-page">
        <div className="page-heading">
          <span className="page-icon"><Laptop /></span>
          <div><h1>{tr("渲染设备", "Render Devices")}</h1><p>{tr("只需配对一次，之后网页会自动把草稿发送到你的电脑并返回 MP4。", "Pair once, then drafts are sent to your computer and exported MP4 files return automatically.")}</p></div>
        </div>

        <div className={`device-hero-status ${status.configured ? "ready" : ""}`}>
          <span>{status.configured ? <Check /> : <Laptop />}</span>
          <div>
            <strong>{status.message}</strong>
            <p>{status.shared_device ? tr("普通用户无需单独配对，任务会自动进入管理员电脑的渲染队列。", "No personal pairing is required. Tasks are sent to the shared administrator render queue.") : status.device_online ? tr("你的电脑已准备好接收视频任务。", "Your computer is ready for video tasks.") : status.central_configured ? tr("当前使用服务端视频渲染。", "Server-side rendering is available.") : tr("完成下方四步，即可从首页一键生成视频。", "Complete the steps below to enable one-click video generation.")}</p>
          </div>
          <button type="button" onClick={() => void refresh()}><RefreshCw />刷新状态</button>
        </div>

        {status.shared_device ? (
          <section className="shared-render-device-card">
            <span><Check /></span>
            <div>
              <h2>{tr("全站共享渲染设备已连接", "Shared render device connected")}</h2>
              <p>{tr("你的任务会自动排队到管理员的剪映电脑，无需下载安装助手，也不需要再次配对。", "Your tasks automatically enter the shared rendering queue. No download or additional pairing is needed.")}</p>
            </div>
          </section>
        ) : <section className="device-onboarding">
          <article>
            <em>01</em>
            <span><Download /></span>
            <h2>{tr("安装兼容版剪映", "Install a compatible editor")}</h2>
            <p>自动导出使用剪映专业版 5.9.0.11632。安装包来自字节官方 CDN，并已核对数字签名和 SHA-256。</p>
            <a className="secondary-button" href="/api/v1/downloads/jianying-compatible">
              <Download />{tr("下载剪映 5.9", "Download Jianying 5.9")}
            </a>
          </article>
          <article>
            <em>02</em>
            <span><Download /></span>
            <h2>{tr("下载 / 更新 AI 视频创作助手", "Download / update the Video Assistant")}</h2>
            <p>{tr("当前最新版", "Latest version")} {latestHelperVersion ? `v${latestHelperVersion}` : tr("检测中", "checking")}。{tr("已安装助手时可一键更新；未安装时请先下载安装包。", "Update with one click if installed, or download the installer first.")}</p>
            <button className="secondary-button" disabled={Boolean(helperUpdate?.running)} type="button" onClick={() => updateHelper()}>
              {helperUpdate?.running ? <LoaderCircle className="spin" /> : <Download />}
              {helperUpdate?.running
                ? `正在更新 ${helperUpdate.percent}%`
                : helperRecoveryRequired || helperUpdate?.percent === 95
                  ? "下载安装包并修复"
                  : "一键更新最新版"}
            </button>
            {helperUpdate && (
              <div className={`helper-update-progress ${helperUpdate.percent === 100 ? "complete" : ""}`} aria-live="polite">
                <div><span>{helperUpdate.phase}</span><strong>{helperUpdate.percent}%</strong></div>
                <progress max="100" value={helperUpdate.percent} aria-label="助手更新进度" />
              </div>
            )}
            <button className="secondary-button" type="button" onClick={() => calibrateHelper()}><Laptop />校准导出按钮</button>
            <a
              className="secondary-button helper-redownload-button"
              href={helperRedownloadUrl}
            ><Download />{tr("重新下载安装包", "Download installer again")}</a>
          </article>
          <article>
            <em>03</em>
            <span><Link2 /></span>
            <h2>{tr("一键连接助手", "Connect assistant")}</h2>
            <p>{tr("网页会生成一次性配对信息并在后台唤醒助手，无需复制或在助手窗口中确认。", "The browser creates one-time pairing information and wakes the assistant automatically.")}</p>
            <button className="secondary-button" disabled={busy} type="button" onClick={() => void createPairing()}>
              {busy ? <LoaderCircle className="spin" /> : <Link2 />}{busy ? tr("正在连接", "Connecting") : tr("连接助手", "Connect")}
            </button>
          </article>
          <article>
            <em>04</em>
            <span><Laptop /></span>
            <h2>{tr("启动并保持在线", "Start and stay online")}</h2>
            <p>{tr("助手会静默常驻；只有剪映原生渲染阶段会短暂打开剪映，完成后自动最小化。", "The assistant stays quiet in the background and opens the editor only during native rendering.")}</p>
            <button className="secondary-button" type="button" onClick={() => wakeHelper()}><Laptop />{tr("唤醒助手", "Wake assistant")}</button>
          </article>
        </section>}

        {!status.shared_device && pairing && (
          <section className="pairing-display" aria-live="polite">
            <div><span>网站地址</span><strong>{window.location.origin}</strong></div>
            <div><span>{tr("一次性配对码", "One-time pairing code")}</span><strong className="pairing-number">{pairing.code}</strong></div>
            <button type="button" onClick={() => void copyPairing()}><Clipboard />{tr("复制配对码", "Copy code")}</button>
          </section>
        )}
        {message && <div className="notice success">{message}</div>}
        {error && <div className="notice error">{error}</div>}

        {!status.shared_device && <section className="connected-devices">
          <div className="section-title"><span>{tr("已连接设备", "Connected devices")}</span><small>{tr(`${status.devices.length} 台`, `${status.devices.length} devices`)}</small></div>
          {status.devices.length ? (
            <div className="connected-device-grid">
              {status.devices.map((device) => (
                <article key={device.id}>
                  <span className={`device-computer ${device.online ? "online" : ""}`}><Laptop /></span>
                  <div>
                    <strong>{device.name}</strong>
                    <small>{device.platform} · {device.online ? tr("在线", "Online") : tr("离线", "Offline")}</small>
                    <small className={device.capabilities.jianying_found === false ? "device-version warning" : "device-version"}>
                      {jianyingStatus(device.capabilities)}
                      {capabilityText(device.capabilities.helper_version)
                        ? ` · 助手 v${capabilityText(device.capabilities.helper_version)}`
                        : ""}
                    </small>
                  </div>
                  <button type="button" aria-label={`解除 ${device.name}`} onClick={() => void removeDevice(device.id)}><Trash2 /></button>
                </article>
              ))}
            </div>
          ) : <div className="small-empty">{tr("还没有配对设备，请按上方步骤完成首次连接。", "No paired devices yet. Follow the steps above to connect one.")}</div>}
        </section>}
      </main>
    </Layout>
  );
}
