"use client";

import { useEffect, useState } from "react";
import { PrivacyControls as PrivacyControlsData, privacyApi } from "@/lib/api";


interface Props {
  sessionId: string;
  onProfileChanged?: () => void;
}

const SCOPE_LABELS = {
  cookies: "仅删除登录凭据",
  profile: "删除画像与证据",
  all: "删除全部账户数据",
} as const;

const CONFIRMATIONS = {
  cookies: "DELETE COOKIES",
  profile: "DELETE PROFILE",
  all: "DELETE ALL",
} as const;

function evidencePeriod(occurredAt?: string | null) {
  if (!occurredAt) return "时间未知";
  const ageDays = Math.max(0, (Date.now() - new Date(occurredAt).getTime()) / 86400000);
  if (ageDays <= 30) return "近期证据";
  if (ageDays > 180) return "历史证据";
  return "长期证据";
}

export default function PrivacyControls({ sessionId, onProfileChanged }: Props) {
  const [controls, setControls] = useState<PrivacyControlsData | null>(null);
  const [status, setStatus] = useState("");
  const [scope, setScope] = useState<keyof typeof SCOPE_LABELS>("cookies");
  const [confirmation, setConfirmation] = useState("");

  const load = async () => {
    try {
      setControls(await privacyApi.controls(sessionId));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "隐私设置加载失败");
    }
  };

  useEffect(() => {
    let cancelled = false;
    privacyApi.controls(sessionId).then((data) => {
      if (!cancelled) setControls(data);
    }).catch((error: unknown) => {
      if (!cancelled) setStatus(error instanceof Error ? error.message : "隐私设置加载失败");
    });
    return () => { cancelled = true; };
  }, [sessionId]);

  const toggleChannel = async (channel: string, enabled: boolean) => {
    await privacyApi.setChannel(sessionId, channel, enabled);
    setStatus(enabled ? `已恢复 ${channel} 参与画像` : `已暂停 ${channel} 参与画像`);
    await load();
    onProfileChanged?.();
  };

  const removeEvidence = async (id: number, title: string) => {
    if (!window.confirm(`确认删除画像证据“${title}”？此操作无法撤销。`)) return;
    await privacyApi.deleteEvidence(sessionId, id);
    setStatus("证据已删除，画像已重新计算");
    await load();
    onProfileChanged?.();
  };

  const deleteData = async () => {
    const expected = CONFIRMATIONS[scope];
    if (confirmation !== expected) {
      setStatus(`请输入确认短语：${expected}`);
      return;
    }
    await privacyApi.deleteData(sessionId, scope, confirmation);
    setStatus(`${SCOPE_LABELS[scope]}已完成`);
    setConfirmation("");
    if (scope === "all" || scope === "cookies") {
      localStorage.removeItem("bili_session");
      localStorage.removeItem("bili_user");
      window.location.reload();
      return;
    }
    await load();
    onProfileChanged?.();
  };

  return (
    <section className="privacy-controls">
      <h3>隐私与证据控制</h3>
      <p className="privacy-hint">暂停通道只停止其参与画像；删除证据或账户数据不可撤销。</p>
      {status && <p className="privacy-status" role="status">{status}</p>}

      <div className="channel-grid">
        {Object.entries(controls?.channels || {}).map(([channel, detail]) => (
          <label key={channel} className="channel-row">
            <span><strong>{channel}</strong><small>{detail.evidence_count} 条证据</small></span>
            <input type="checkbox" checked={detail.enabled}
              onChange={(event) => void toggleChannel(channel, event.target.checked)} />
          </label>
        ))}
        {controls && Object.keys(controls.channels).length === 0 && <p>暂无可控制的画像通道。</p>}
      </div>

      <details>
        <summary>逐条管理画像证据（最多显示 100 条）</summary>
        <div className="evidence-list">
          {(controls?.evidence || []).map((item) => (
            <div key={item.id} className="evidence-row">
              <span>
                <strong>{item.title}</strong>
                <small>{item.source} · {evidencePeriod(item.occurred_at)}
                  {item.occurred_at ? ` · ${new Date(item.occurred_at).toLocaleString()}` : ""}</small>
              </span>
              <button onClick={() => void removeEvidence(item.id, item.title)}>删除</button>
            </div>
          ))}
        </div>
      </details>

      <div className="danger-zone">
        <strong>数据删除</strong>
        <select value={scope} onChange={(event) => {
          setScope(event.target.value as keyof typeof SCOPE_LABELS);
          setConfirmation("");
        }}>
          {Object.entries(SCOPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)}
          placeholder={`输入 ${CONFIRMATIONS[scope]}`} />
        <button onClick={() => void deleteData()} disabled={confirmation !== CONFIRMATIONS[scope]}>确认删除</button>
      </div>

      <style jsx>{`
        .privacy-controls { margin: 12px 16px; padding: 14px; border: 1px solid #eadfe3; border-radius: 10px; background: #fff; }
        h3 { margin: 0 0 4px; font-size: 15px; }
        .privacy-hint, .privacy-status { margin: 4px 0 10px; font-size: 12px; color: #6d6870; }
        .privacy-status { color: #245d43; }
        .channel-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 7px; }
        .channel-row, .evidence-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px; border: 1px solid #eee; border-radius: 7px; }
        span { display: flex; flex-direction: column; min-width: 0; }
        small { color: #777; font-size: 11px; overflow-wrap: anywhere; }
        details { margin-top: 12px; }
        summary { cursor: pointer; color: #46576b; font-size: 13px; }
        .evidence-list { display: grid; gap: 6px; margin-top: 8px; max-height: 260px; overflow: auto; }
        button { border: 1px solid #d9c8cf; background: white; border-radius: 6px; padding: 5px 8px; cursor: pointer; }
        .danger-zone { display: grid; grid-template-columns: auto minmax(150px, 1fr) minmax(180px, 1fr) auto; align-items: center; gap: 7px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #f0d4dc; }
        .danger-zone input, .danger-zone select { padding: 7px; border: 1px solid #ddd; border-radius: 6px; }
        .danger-zone button { color: #9d2038; border-color: #dcaab5; }
        .danger-zone button:disabled { opacity: .45; cursor: not-allowed; }
        @media (max-width: 720px) { .danger-zone { grid-template-columns: 1fr; } }
      `}</style>
    </section>
  );
}
