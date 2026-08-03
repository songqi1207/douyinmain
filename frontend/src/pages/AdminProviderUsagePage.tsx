import { Activity, AlertTriangle, Gauge, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchAdminProviderUsage } from "../api";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";
import type { ProviderUsageSnapshot } from "../types";

function providerName(provider: string) {
  return provider === "coze" ? "扣子 / Coze" : provider === "mihe" ? "米核 / Mihe" : provider;
}

export function AdminProviderUsagePage() {
  const { tr } = usePreferences();
  const [days, setDays] = useState(30);
  const [usage, setUsage] = useState<ProviderUsageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      const result = await fetchAdminProviderUsage(days);
      setUsage(result.usage);
      setError("");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [days]);

  return (
    <Layout>
      <main className="content-page page-width admin-provider-usage-page">
        <div className="page-heading"><span className="page-icon"><Activity /></span><div><h1>{tr("供应商用量监控", "Provider usage")}</h1><p>{tr("查看扣子、米核的调用次数、失败情况和估算积分消耗。", "Track Coze and Mihe calls, failures and estimated credit usage.")}</p></div><div className="page-heading-actions"><button type="button" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{tr("刷新", "Refresh")}</button></div></div>
        {error && <div className="notice error">{error}</div>}
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
