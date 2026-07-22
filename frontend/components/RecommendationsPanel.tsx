"use client";

import { useEffect, useRef, useState } from "react";
import {
  RecommendationMetrics,
  RecommendationOptions,
  recommendationsApi,
  VideoRecommendation,
} from "@/lib/api";

interface RecommendationsPanelProps {
  sessionId: string;
  onClose?: () => void;
}

const MODES: Array<{ value: NonNullable<RecommendationOptions["mode"]>; label: string }> = [
  { value: "balanced", label: "平衡推荐" },
  { value: "learning", label: "学习提升" },
  { value: "relax", label: "放松娱乐" },
  { value: "following", label: "关注追更" },
  { value: "explore", label: "探索新领域" },
  { value: "rediscover", label: "重温收藏" },
];

export default function RecommendationsPanel({ sessionId, onClose }: RecommendationsPanelProps) {
  const [recommendations, setRecommendations] = useState<VideoRecommendation[]>([]);
  const [metrics, setMetrics] = useState<RecommendationMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [mode, setMode] = useState<NonNullable<RecommendationOptions["mode"]>>("balanced");
  const [query, setQuery] = useState("");
  const [maxDuration, setMaxDuration] = useState(0);
  const [exploration, setExploration] = useState(0.3);
  const [favoriteTarget, setFavoriteTarget] = useState<VideoRecommendation | null>(null);
  const [favoriteFolders, setFavoriteFolders] = useState<Array<{ media_id: number; title: string }>>([]);
  const [favoriteFolderId, setFavoriteFolderId] = useState(0);
  const [favoriteSubmitting, setFavoriteSubmitting] = useState(false);
  const recordedImpressions = useRef(new Set<string>());

  const topicOf = (rec: VideoRecommendation) =>
    rec.recall_tag || rec.recall_category || rec.matched_interest || rec.type;

  const refreshMetrics = async () => {
    try {
      const response = await recommendationsApi.metrics(sessionId);
      if (response.success) setMetrics(response.metrics);
    } catch (error) {
      console.error("获取推荐指标失败:", error);
    }
  };

  const loadRecommendations = async (overrides: RecommendationOptions = {}) => {
    setLoading(true);
    try {
      const options: RecommendationOptions = {
        mode,
        query: query.trim() || undefined,
        max_duration: maxDuration || undefined,
        exploration_level: exploration,
        ...overrides,
      };
      const response = await recommendationsApi.get(sessionId, 10, "all", options);
      if (response.success) setRecommendations(response.recommendations);
      await refreshMetrics();
    } catch (error) {
      console.error("获取推荐失败:", error);
      showMessage("error", "获取推荐失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  const submitFeedback = async (rec: VideoRecommendation, action: string, reasonCode?: string) => {
    try {
      const response = await recommendationsApi.feedback(sessionId, rec.bvid, action, {
        batch_id: rec.batch_id,
        reason_code: reasonCode,
        topic: topicOf(rec),
        up_mid: rec.mid,
      });
      if (response.success) {
        showMessage("success", action === "block_up" ? "已屏蔽该 UP 主" : "反馈已记录，将影响下一轮推荐");
        setRecommendations((previous) => previous.filter((item) => item.bvid !== rec.bvid));
        await refreshMetrics();
      }
    } catch (error) {
      console.error("提交反馈失败:", error);
      showMessage("error", "反馈记录失败");
    }
  };

  const showMessage = (type: "success" | "error", text: string) => {
    setMessage({ type, text });
    window.setTimeout(() => setMessage(null), 3000);
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadRecommendations();
    }, 0);
    return () => window.clearTimeout(timer);
    // 只在登录会话变化时初始化；筛选条件由“生成推荐”按钮显式提交。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    recommendations.forEach((rec, index) => {
      const key = `${rec.batch_id}:${rec.bvid}`;
      if (recordedImpressions.current.has(key)) return;
      recordedImpressions.current.add(key);
      recommendationsApi.event({
        session_id: sessionId,
        bvid: rec.bvid,
        event_type: "impression",
        batch_id: rec.batch_id,
        topic: topicOf(rec),
        up_mid: rec.mid,
        position: index + 1,
        score: rec.score,
        event_data: {
          algorithm_version: rec.algorithm_version,
          feature_scores: rec.feature_scores || {},
          recall_source: rec.type,
        },
      }).catch((error) => console.error("记录推荐曝光失败:", error));
    });
  }, [recommendations, sessionId]);

  const openVideo = (rec: VideoRecommendation) => {
    recommendationsApi.event({
      session_id: sessionId,
      bvid: rec.bvid,
      event_type: "click",
      batch_id: rec.batch_id,
      topic: topicOf(rec),
      up_mid: rec.mid,
      score: rec.score,
    }).catch((error) => console.error("记录推荐点击失败:", error));
  };

  const findSimilar = (rec: VideoRecommendation) => {
    setQuery(rec.matched_interest || rec.recall_tag || rec.title);
    void loadRecommendations({
      mode: "balanced",
      query: rec.matched_interest || rec.recall_tag || rec.title,
    });
  };

  const handleDismiss = (rec: VideoRecommendation, value: string) => {
    if (!value) return;
    if (value === "block_topic" || value === "block_up") {
      void submitFeedback(rec, value, value);
    } else {
      void submitFeedback(rec, "dismissed", value);
    }
  };

  const openFavoriteConfirmation = async (rec: VideoRecommendation) => {
    try {
      const preview = await recommendationsApi.favoritePreview(sessionId, rec.bvid);
      setFavoriteTarget(rec);
      setFavoriteFolders(preview.folders);
      setFavoriteFolderId(preview.folders[0]?.media_id || 0);
    } catch (error) {
      console.error("加载收藏夹失败:", error);
      showMessage("error", "无法加载收藏夹，请先同步收藏夹");
    }
  };

  const confirmFavorite = async () => {
    if (!favoriteTarget || !favoriteFolderId) return;
    setFavoriteSubmitting(true);
    try {
      const response = await recommendationsApi.favoriteExecute({
        session_id: sessionId,
        bvid: favoriteTarget.bvid,
        target_media_id: favoriteFolderId,
        confirmed: true,
        batch_id: favoriteTarget.batch_id,
        topic: topicOf(favoriteTarget),
        up_mid: favoriteTarget.mid,
      });
      showMessage("success", response.message);
      setRecommendations((items) => items.filter((item) => item.bvid !== favoriteTarget.bvid));
      setFavoriteTarget(null);
      await refreshMetrics();
    } catch (error) {
      console.error("收藏失败:", error);
      showMessage("error", "收藏失败，未修改 B 站收藏夹");
    } finally {
      setFavoriteSubmitting(false);
    }
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return "";
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  };

  return (
    <div className="recommendations-panel">
      <div className="panel-header">
        <div>
          <h2>为你推荐</h2>
          <p>反馈会影响下一轮结果；重温收藏模式才会返回已收藏视频。</p>
        </div>
        {onClose && <button className="close-btn" onClick={onClose}>×</button>}
      </div>

      {message && <div className={`message ${message.type}`}>{message.text}</div>}

      <div className="controls">
        <select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}>
          {MODES.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}
        </select>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="这次想看什么？可留空"
          maxLength={100}
        />
        <select value={maxDuration} onChange={(event) => setMaxDuration(Number(event.target.value))}>
          <option value={0}>不限时长</option>
          <option value={300}>5 分钟以内</option>
          <option value={1200}>20 分钟以内</option>
          <option value={3600}>60 分钟以内</option>
        </select>
        <label>
          探索度 {Math.round(exploration * 100)}%
          <input type="range" min="0" max="1" step="0.1" value={exploration}
            onChange={(event) => setExploration(Number(event.target.value))} />
        </label>
        <button className="primary" onClick={() => void loadRecommendations()} disabled={loading}>
          {loading ? "生成中…" : "生成推荐"}
        </button>
      </div>

      {metrics && (
        <div className="metrics" title={metrics.inference_note}>
          <span><strong>{metrics.events.impression || 0}</strong> 曝光</span>
          <span><strong>{(metrics.ctr * 100).toFixed(1)}%</strong> 点击率</span>
          <span><strong>{(metrics.favorite_rate * 100).toFixed(1)}%</strong> 收藏率</span>
          <span><strong>{(metrics.dismiss_rate * 100).toFixed(1)}%</strong> 不感兴趣</span>
          <span><strong>{(metrics.repeat_exposure_rate * 100).toFixed(1)}%</strong> 重复曝光</span>
          <span><strong>{metrics.topic_coverage}</strong> 主题覆盖</span>
          <span><strong>{metrics.up_coverage}</strong> UP覆盖</span>
          <span><strong>{(metrics.inferred_click_to_watch_rate * 100).toFixed(1)}%</strong> 点击后观看*</span>
          <span className="wide"><strong>召回贡献</strong> {Object.entries(metrics.channel_contribution)
            .map(([channel, count]) => `${channel} ${count}`).join(" · ") || "暂无"}</span>
        </div>
      )}

      {recommendations.length === 0 ? (
        <div className="empty-state">{loading ? "正在召回和排序…" : "暂无符合条件的内容，可调整模式或时长"}</div>
      ) : (
        <div className="recommendations-list">
          {recommendations.map((rec) => (
            <article key={rec.bvid} className="recommendation-item">
              {rec.pic && <img className="rec-cover" src={rec.pic} alt="" />}
              <div className="rec-info">
                <a href={`https://www.bilibili.com/video/${rec.bvid}`} target="_blank"
                  rel="noopener noreferrer" onClick={() => openVideo(rec)}>
                  <h3>{rec.title}</h3>
                </a>
                <p className="author">{rec.author}</p>
                <p className="reason">{rec.reason}</p>
                <p className="meta">
                  {topicOf(rec)}
                  {rec.duration ? ` · ${formatDuration(rec.duration)}` : ""}
                  {rec.pubdate ? ` · ${new Date(rec.pubdate).toLocaleDateString()}` : ""}
                  {` · ${rec.type}`}
                </p>
                <div className="inline-actions">
                  <button onClick={() => void submitFeedback(rec, "like")}>喜欢</button>
                  <button onClick={() => void submitFeedback(rec, "viewed")}>已看过</button>
                  <button onClick={() => void submitFeedback(rec, "watch_later")}>标记想看</button>
                  <button onClick={() => void openFavoriteConfirmation(rec)}>一键收藏</button>
                  <button onClick={() => findSimilar(rec)}>更多类似</button>
                  <select defaultValue="" aria-label="不感兴趣原因"
                    onChange={(event) => handleDismiss(rec, event.target.value)}>
                    <option value="" disabled>减少此类…</option>
                    <option value="not_relevant">内容不相关</option>
                    <option value="too_long">视频太长</option>
                    <option value="too_old">内容太旧</option>
                    <option value="temporary">暂时不想看</option>
                    <option value="block_topic">屏蔽此主题</option>
                    <option value="block_up">屏蔽该 UP 主</option>
                  </select>
                </div>
                <details>
                  <summary>为什么推荐</summary>
                  {rec.matched_concepts && rec.matched_concepts.length > 0 && (
                    <p className="concept-trace">
                      命中概念：{rec.matched_concepts.map((item) => item.label).join("、")}
                    </p>
                  )}
                  {rec.ontology_path && rec.ontology_path.length > 0 && (
                    <ol className="ontology-path">
                      {rec.ontology_path.map((edge, index) => (
                        <li key={`${edge.from}-${edge.relation}-${edge.to}-${index}`}>
                          {edge.from} —{edge.relation}→ {edge.to}
                        </li>
                      ))}
                    </ol>
                  )}
                  <code>{JSON.stringify(rec.feature_scores || {}, null, 2)}</code>
                  <small>算法 {rec.algorithm_version} · 批次 {rec.batch_id.slice(0, 8)}</small>
                </details>
              </div>
            </article>
          ))}
        </div>
      )}

      {favoriteTarget && (
        <div className="confirm-backdrop" role="dialog" aria-modal="true" aria-label="确认收藏">
          <div className="confirm-card">
            <h3>确认收藏</h3>
            <p>即将把《{favoriteTarget.title}》写入你的 B 站收藏夹。请选择目标：</p>
            <select value={favoriteFolderId} onChange={(event) => setFavoriteFolderId(Number(event.target.value))}>
              {favoriteFolders.map((folder) => (
                <option key={folder.media_id} value={folder.media_id}>{folder.title}</option>
              ))}
            </select>
            {favoriteFolders.length === 0 && <p>没有可用收藏夹，请先同步收藏夹。</p>}
            <div className="confirm-actions">
              <button onClick={() => setFavoriteTarget(null)} disabled={favoriteSubmitting}>取消</button>
              <button className="primary" onClick={() => void confirmFavorite()}
                disabled={!favoriteFolderId || favoriteSubmitting}>
                {favoriteSubmitting ? "收藏中…" : "确认写入 B 站"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .recommendations-panel { background:#fff; border-radius:12px; padding:22px; width:min(980px,90vw); max-height:86vh; overflow:auto; }
        .panel-header { display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:16px; }
        .panel-header h2 { margin:0; font-size:22px; }
        .panel-header p { margin:5px 0 0; color:#777; font-size:13px; }
        .close-btn { border:0; background:none; font-size:28px; cursor:pointer; }
        .message { padding:10px 12px; border-radius:7px; margin-bottom:12px; }
        .message.success { background:#e7f7ed; color:#176b36; } .message.error { background:#fdecec; color:#9d2626; }
        .controls { display:grid; grid-template-columns:1fr 2fr 1fr 1.3fr auto; gap:9px; align-items:center; padding:12px; background:#faf7f9; border-radius:9px; }
        .controls input,.controls select,.inline-actions select { border:1px solid #ddd; border-radius:6px; padding:8px; background:white; min-width:0; }
        .controls label { display:flex; flex-direction:column; font-size:12px; color:#555; }
        button { cursor:pointer; } .primary { border:0; border-radius:7px; padding:10px 16px; color:#fff; background:#fb5b93; }
        .metrics { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin:12px 0; }
        .metrics span { background:#f7f7f7; border-radius:7px; padding:8px; text-align:center; color:#666; font-size:11px; }
        .metrics strong { display:block; color:#222; font-size:16px; }
        .metrics .wide { grid-column:span 2; text-align:left; }
        .recommendations-list { display:flex; flex-direction:column; gap:12px; margin-top:12px; }
        .recommendation-item { display:flex; padding:14px; border:1px solid #eee; border-radius:10px; }
        .recommendation-item:hover { border-color:#ff8db5; box-shadow:0 3px 12px rgba(255,94,157,.09); }
        .rec-cover { width:192px; height:108px; object-fit:cover; border-radius:7px; margin-right:15px; background:#f3f3f3; }
        .rec-info { flex:1; min-width:0; } h3 { margin:0 0 4px; font-size:16px; color:#ee4c88; }
        a { text-decoration:none; } .author,.meta { color:#777; margin:4px 0; font-size:12px; }
        .reason { color:#257742; font-size:13px; margin:6px 0; }
        .concept-trace, .ontology-path { color:#52657a; font-size:12px; margin:6px 0; }
        .ontology-path { padding-left:18px; }
        .inline-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:9px; }
        .inline-actions button { border:1px solid #e5d6dc; background:#fff; border-radius:6px; padding:5px 9px; }
        details { margin-top:8px; color:#777; font-size:12px; } details code { display:block; white-space:pre-wrap; margin:5px 0; }
        details small { display:block; } .empty-state { text-align:center; color:#777; padding:42px; }
        @media (max-width:760px) { .controls { grid-template-columns:1fr; } .metrics { grid-template-columns:repeat(2,1fr); } .rec-cover { width:120px; height:75px; } }
        .confirm-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.45); display:grid; place-items:center; z-index:20; }
        .confirm-card { width:min(460px,90vw); background:white; border-radius:10px; padding:20px; box-shadow:0 16px 50px rgba(0,0,0,.2); }
        .confirm-card h3 { color:#222; } .confirm-card select { width:100%; padding:9px; border:1px solid #ddd; border-radius:6px; }
        .confirm-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
        .confirm-actions button { padding:8px 12px; border-radius:6px; border:1px solid #ddd; }
      `}</style>
    </div>
  );
}
