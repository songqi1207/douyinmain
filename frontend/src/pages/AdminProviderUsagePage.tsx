import { Activity, AlertTriangle, CheckCircle2, Gauge, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchAdminHealthCheck, fetchAdminProviderUsage, runAdminHealthCheck } from "../api";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";
import type { ProviderUsageSnapshot, SystemHealthCheck } from "../types";

function providerName(provider: string) {
  return provider === "coze" ? "扣子 / Coze" : provider === "mihe" ? "米核 / Mihe" : provider;
}

export function AdminProviderUsagePage() {
  const { tr } = usePreferences();
  const [days, setDays] = useState(30);
  const [usage, setUsage] = useState<ProviderUsageSnapshot | null>(null);
  const [health, setHealth] = useState<SystemHealthCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [usageResult, healthResult] = await Promise.all([fetchAdminProviderUsage(days), fetchAdminHealthCheck()]);
      setUsage(usageResult.usage);
      setHealth(healthResult.health);
      setError("");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [days]);

  async function runHealth() {
    setLoading(true);
    try {
      const result = await runAdminHealthCheck();
      setHealth(result.health);
      setError("");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Layout>
      <main className="content-page page-width admin-provider-usage-page">
        <div className="page-heading"><span className="page-icon"><Activity /></span><div><h1>{tr("供应商用量监控", "Provider usage")}</h1><p>{tr("查看扣子、米核的调用次数、失败情况和估算积分消耗。", "Track Coze and Mihe calls, failures and estimated credit usage.")}</p></div><div className="page-heading-actions"><button type="button" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{tr("刷新", "Refresh")}</button></div></div>
        {error && <div className="notice error">{error}</div>}
        {health && <section className={`health-check-panel ${health.overall}`}>
          <div className="health-check-heading"><div><span className="health-check-icon">{health.overall === "ok" ? <CheckCircle2 /> : <AlertTriangle />}</span><div><strong>{tr("\u7cfb\u7edf\u5065\u5eb7\u68c0\u67e5", "System health check")}</strong><small>{tr("\u6700\u540e\u68c0\u67e5", "Last checked")} {new Date(health.checked_at * 1000).toLocaleString()}</small></div></div><button type="button" onClick={() => void runHealth()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{tr("\u7acb\u5373\u68c0\u67e5", "Run now")}</button></div>
          <div className="health-check-list">{health.checks.map((check) => <article className={check.status} key={`${check.name}-${check.code}`}><span>{check.status === "ok" ? "OK" : check.status === "warning" ? "WARN" : "ERROR"}</span><strong>{check.name}</strong><p>{check.message}</p><small>{check.code}</small></article>)}</div>
        </section>}
        <section className="provider-usage-toolbar"><span>{tr("统计窗口", "Window")}</span>{[7, 30, 90].map((value) => <button className={days === value ? "selected" : ""} type="button" key={value} onClick={() => setDays(value)}>{value} {tr("天", "days")}</button>)}</section>
        {loading && !usage ? <div className="loading-state"><LoaderCircle className="spin" />{tr("正在读取供应商用量", "Loading provider usage")}</div> : usage && <>
          <div className="notice warning"><AlertTriangle />{tr("当前为按管理员计价表计算的估算值，不代表供应商后台实时余额。", "These are estimates from the admin pricing table, not live supplier balances.")}</div>
          <section className="quota-overview-grid provider-usage-summary">
            <article><span><Gauge /></span><div><small>{tr("调用次数", "Calls")}</small><strong>{usage.totals.calls}</strong><p>{usage.totals.successes} {tr("成功", "successful")} · {usage.totals.failures} {tr("失败", "failed")}</p></div></article>
            <article><span><Activity /></span><div><small>{tr("估算供应商成本", "Estimated provider cost")}</small><strong>{usage.totals.estimated_points} {tr("积分", "credits")}</strong><p>{tr(`最近 ${usage.days} 天`, `Last ${usage.days} days`)}</p></div></article>
            {Object.entries(usage.by_provider).map(([provider, item]) => <article key={provider}><span><Gauge /></span><div><small>{providerName(provider)}</small><strong>{item.estimated_points} {tr("积分", "credits")}</strong><p>{item.calls} {tr("次调用", "calls")} · {item.failures} {tr("次失败", "failed")}</p></div></article>)}
          </section>
          <section className="admin-provider-table"><div className="section-title"><span>{tr("按工作流统计", "By workflow")}</span><small>{tr("每次重试按一次供应商调用记录", "Each retry is counted as a provider call")}</small></div>{usage.by_workflow.length ? usage.by_workflow.map((item) => <article key={`${item.workflow_code}-${item.provider}`}><strong>{item.workflow_code}</strong><span>{providerName(item.provider)}</span><span>{item.calls} {tr("次", "calls")}</span><span>{item.estimated_points} {tr("积分", "credits")}</span><span className={item.failures ? "negative" : "positive"}>{item.failures} {tr("失败", "failed")}</span><small>{Math.round(item.avg_elapsed_ms)} ms avg</small></article>) : <div className="small-empty">{tr("暂无供应商调用记录", "No provider calls in this window")}</div>}</section>
          <section className="admin-provider-table"><div className="section-title"><span>{tr("最近失败与告警", "Recent failures and alerts")}</span></div>{usage.recent_errors.length ? usage.recent_errors.map((item) => <article key={item.id}><strong>{providerName(item.provider)}</strong><span>{item.workflow_code}</span><span>{item.status}</span><span>{item.error_code || `HTTP ${item.http_status || "-"}`}</span><small>{item.error_message || "-"}</small></article>) : <div className="small-empty">{tr("暂无失败记录", "No failures recorded")}</div>}</section>
        </>}
      </main>
    </Layout>
  );
}
