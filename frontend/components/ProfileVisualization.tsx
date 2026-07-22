"use client";

import { useState, useEffect } from "react";
import { RecommendationPreferences, recommendationsApi } from "@/lib/api";
import PrivacyControls from "@/components/PrivacyControls";

interface InterestTag {
  tag: string;
  score: number;
}

interface FollowedUp {
  mid: number;
  name: string;
  score: number;
}

interface CategoryDistribution {
  category: string;
  count: number;
  percentage: number;
}

interface ProfileData {
  interest_tags: InterestTag[];
  followed_ups: FollowedUp[];
  category_distribution: CategoryDistribution[];
  total_favorites: number;
  summary: string;  // 用户画像总结
  visual_style_preference?: Record<string, number>;
  content_type_preference?: Record<string, number>;
  ontology_version?: string;
  multi_interests: Array<{ concept_id: string; label: string; weight: number }>;
}

interface ProfileVisualizationProps {
  sessionId: string;
  onClose?: () => void;
}

export default function ProfileVisualization({ sessionId, onClose }: ProfileVisualizationProps) {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"tags" | "categories" | "ups">("tags");
  const [error, setError] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<RecommendationPreferences | null>(null);
  const [intent, setIntent] = useState("");
  const [newTag, setNewTag] = useState("");
  const [newTagScore, setNewTagScore] = useState(0.7);

  useEffect(() => {
    fetchProfile();
  }, [sessionId]);

  const fetchProfile = async () => {
    setLoading(true);
    setError(null);
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_BASE_URL}/recommendations/update-interest?session_id=${sessionId}`, {
        method: "POST",
      });
      const data = await response.json();

      if (data.success && data.profile) {
        // 格式化数据 - 使用 unified_tags 而不是 interest_tags
        const interestTags: InterestTag[] = Object.entries(data.profile.unified_tags || {})
          .map(([tag, score]) => ({ tag, score: score as number }))
          .sort((a, b) => b.score - a.score);

        const followedUps: FollowedUp[] = (data.profile.followed_ups || []).map((up: Partial<FollowedUp>) => ({
          mid: up.mid || 0,
          name: up.name || "未知UP主",
          score: up.score || 0,
        }));

        setProfile({
          interest_tags: interestTags,
          followed_ups: followedUps,
          category_distribution: [],
          total_favorites: data.profile.total_analyzed || 0,
          summary: data.profile.summary || "",  // 添加画像总结
          ontology_version: data.profile.profile_features?.ontology_version,
          multi_interests: data.profile.profile_features?.multi_interests || [],
        });
      } else {
        setProfile({
          interest_tags: [],
          followed_ups: [],
          category_distribution: [],
          total_favorites: 0,
          summary: "",
          multi_interests: [],
        });
      }
      const preferenceResponse = await recommendationsApi.preferences(sessionId);
      if (preferenceResponse.success) {
        setPreferences(preferenceResponse.preferences);
        setIntent(preferenceResponse.preferences.current_intent || "");
      }
    } catch (err) {
      console.error("获取画像失败:", err);
      setError("获取画像失败");
    } finally {
      setLoading(false);
    }
  };

  const removeTag = async (tag: string) => {
    await recommendationsApi.updatePreferences(sessionId, { tag_updates: { [tag]: null } });
    setProfile((current) => current ? {
      ...current,
      interest_tags: current.interest_tags.filter((item) => item.tag !== tag),
    } : current);
    setPreferences((current) => current ? {
      ...current,
      tags: current.tags.filter((item) => item.tag !== tag),
    } : current);
  };

  const updateTagScore = async (tag: string, score: number) => {
    const nextScore = Math.max(0, Math.min(1, Number(score.toFixed(2))));
    await recommendationsApi.updatePreferences(sessionId, { tag_updates: { [tag]: nextScore } });
    setProfile((current) => current ? {
      ...current,
      interest_tags: current.interest_tags
        .map((item) => item.tag === tag ? { ...item, score: nextScore } : item)
        .sort((a, b) => b.score - a.score),
    } : current);
    setPreferences((current) => current ? {
      ...current,
      tags: current.tags.map((item) => item.tag === tag ? { ...item, score: nextScore } : item),
    } : current);
  };

  const addTag = async () => {
    const tag = newTag.trim();
    if (!tag) return;
    await recommendationsApi.updatePreferences(sessionId, { tag_updates: { [tag]: newTagScore } });
    setProfile((current) => current ? {
      ...current,
      interest_tags: [
        ...current.interest_tags.filter((item) => item.tag !== tag),
        { tag, score: newTagScore },
      ].sort((a, b) => b.score - a.score),
    } : current);
    setPreferences((current) => current ? {
      ...current,
      tags: [
        ...current.tags.filter((item) => item.tag !== tag),
        { tag, score: newTagScore, source: "long_term" as const },
      ].sort((a, b) => b.score - a.score),
    } : current);
    setNewTag("");
  };

  const saveIntent = async () => {
    await recommendationsApi.updatePreferences(sessionId, { current_intent: intent });
  };

  const resetRecent = async () => {
    await recommendationsApi.updatePreferences(sessionId, { reset_recent: true });
    await fetchProfile();
  };

  const unblockTopic = async (topic: string) => {
    await recommendationsApi.unblock(sessionId, { preference_type: "topic", topic });
    setPreferences((current) => current ? {
      ...current,
      blocked_topics: current.blocked_topics.filter((item) => item !== topic),
    } : current);
  };

  const unblockUp = async (upMid: number) => {
    await recommendationsApi.unblock(sessionId, { preference_type: "up", up_mid: upMid });
    setPreferences((current) => current ? {
      ...current,
      blocked_up_mids: current.blocked_up_mids.filter((item) => item !== upMid),
    } : current);
  };

  const getMaxScore = (tags: InterestTag[]) => {
    if (tags.length === 0) return 1;
    return Math.max(...tags.map(t => t.score));
  };

  const getBarWidth = (score: number, maxScore: number) => {
    return Math.max((score / maxScore) * 100, 5);
  };

  return (
    <div className="profile-visualization">
      <div className="panel-header">
        <h2>兴趣画像</h2>
        {onClose && (
          <button className="close-btn" onClick={onClose}>×</button>
        )}
      </div>

      {loading ? (
        <div className="loading-state">
          <div className="spinner"></div>
          <span>加载中...</span>
        </div>
      ) : error ? (
        <div className="error-state">
          <p>{error}</p>
          <button onClick={fetchProfile}>重试</button>
        </div>
      ) : profile ? (
        <>
          <div className="profile-stats">
            <div className="stat-item">
              <span className="stat-value">{profile.total_favorites}</span>
              <span className="stat-label">收藏总数</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{profile.interest_tags.length}</span>
              <span className="stat-label">兴趣标签</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{profile.followed_ups.length}</span>
              <span className="stat-label">关注UP主</span>
            </div>
          </div>

          {/* 画像总结 */}
          {profile.summary && (
            <div className="profile-summary">
              <p>{profile.summary}</p>
            </div>
          )}

          {profile.multi_interests.length > 0 && (
            <div className="ontology-clusters">
              <div className="ontology-title">
                语义兴趣簇
                {profile.ontology_version ? <small>{profile.ontology_version}</small> : null}
              </div>
              <div className="cluster-list">
                {profile.multi_interests.slice(0, 8).map((cluster) => (
                  <span key={cluster.concept_id}>
                    {cluster.label} · {(cluster.weight * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            </div>
          )}

          {preferences && (
            <div className="preference-editor">
              <div className="intent-row">
                <label>当前想看</label>
                <input value={intent} onChange={(event) => setIntent(event.target.value)}
                  placeholder="例如：最近想系统学习 LangGraph" maxLength={100} />
                <button onClick={() => void saveIntent()}>保存</button>
                <button onClick={() => void resetRecent()}>清除近期偏好</button>
              </div>
              <p className="confidence">
                画像置信度 {(preferences.confidence_score * 100).toFixed(0)}%
                {preferences.updated_at ? ` · 更新于 ${new Date(preferences.updated_at).toLocaleString()}` : ""}
              </p>
              {(preferences.blocked_topics.length > 0 || preferences.blocked_up_mids.length > 0) && (
                <div className="blocked-list">
                  <strong>已屏蔽：</strong>
                  {preferences.blocked_topics.map((topic) => (
                    <button key={topic} onClick={() => void unblockTopic(topic)}>主题 {topic} ×</button>
                  ))}
                  {preferences.blocked_up_mids.map((mid) => (
                    <button key={mid} onClick={() => void unblockUp(mid)}>UP {mid} ×</button>
                  ))}
                </div>
              )}
            </div>
          )}

          {preferences && (
            <div className="interest-periods">
              {([
                ["recent", "近期兴趣"],
                ["long_term", "长期兴趣"],
                ["historical", "历史兴趣"],
              ] as const).map(([period, label]) => {
                const rows = preferences.tags.filter((item) => item.source === period);
                return (
                  <div key={period}>
                    <strong>{label}</strong>
                    <small>{rows.length ? rows.slice(0, 8).map((item) => item.tag).join("、") : "暂无"}</small>
                  </div>
                );
              })}
              {(preferences.interest_evidence || []).slice(0, 8).map((item, index) => (
                <p key={`${item.concept_id}-${item.source}-${index}`}>
                  {item.concept_label} · {item.source}
                  {typeof item.age_days === "number" ? ` · ${Math.round(item.age_days)} 天前` : ""}
                  {item.title ? ` · ${item.title}` : ""}
                </p>
              ))}
            </div>
          )}

          <div className="tab-nav">
            <button
              className={activeTab === "tags" ? "active" : ""}
              onClick={() => setActiveTab("tags")}
            >
              兴趣标签
            </button>
            <button
              className={activeTab === "ups" ? "active" : ""}
              onClick={() => setActiveTab("ups")}
            >
              关注UP主
            </button>
          </div>

          <div className="tab-content">
            {activeTab === "tags" && (
              <div className="tags-section">
                <div className="add-tag-row">
                  <input value={newTag} onChange={(event) => setNewTag(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") void addTag(); }}
                    placeholder="添加兴趣标签" maxLength={100} />
                  <input type="range" min="0.1" max="1" step="0.1" value={newTagScore}
                    onChange={(event) => setNewTagScore(Number(event.target.value))} />
                  <span>{(newTagScore * 100).toFixed(0)}%</span>
                  <button onClick={() => void addTag()}>添加</button>
                </div>
                {profile.interest_tags.length === 0 ? (
                  <div className="empty-state">
                    <p>暂无兴趣标签</p>
                    <p className="hint">构建知识库后会自动分析</p>
                  </div>
                ) : (
                  <div className="tags-chart">
                    {profile.interest_tags.slice(0, 15).map((tag, index) => (
                      <div key={index} className="tag-item">
                        <div className="tag-info">
                          <span className="tag-name">{tag.tag}</span>
                          <span className="tag-score">
                            {(tag.score * 100).toFixed(0)}%
                            {preferences?.tags.find((item) => item.tag === tag.tag)?.source === "recent" ? " · 近期" : " · 长期"}
                            <button className="score-button" onClick={() => void updateTagScore(tag.tag, tag.score - 0.1)}
                              aria-label={`降低 ${tag.tag} 权重`}>−</button>
                            <button className="score-button" onClick={() => void updateTagScore(tag.tag, tag.score + 0.1)}
                              aria-label={`提高 ${tag.tag} 权重`}>+</button>
                            <button className="remove-tag" onClick={() => void removeTag(tag.tag)} title="删除此画像标签">×</button>
                          </span>
                        </div>
                        <div className="tag-bar-container">
                          <div
                            className="tag-bar"
                            style={{ width: `${getBarWidth(tag.score, getMaxScore(profile.interest_tags))}%` }}
                          ></div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === "ups" && (
              <div className="ups-section">
                {profile.followed_ups.length === 0 ? (
                  <div className="empty-state">
                    <p>暂无关注的UP主信息</p>
                    <p className="hint">同步收藏夹后可查看</p>
                  </div>
                ) : (
                  <div className="ups-list">
                    {profile.followed_ups.map((up, index) => (
                      <div key={index} className="up-item">
                        <div className="up-avatar">
                          {up.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="up-info">
                          <span className="up-name">{up.name}</span>
                          <span className="up-score">相关度: {(up.score * 100).toFixed(0)}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <PrivacyControls sessionId={sessionId} onProfileChanged={() => void fetchProfile()} />

          <div className="panel-footer">
            <button onClick={fetchProfile} className="btn btn-outline">
              刷新画像
            </button>
          </div>
        </>
      ) : (
        <div className="empty-state">
          <p>暂无画像数据</p>
        </div>
      )}

      <style jsx>{`
        .profile-visualization {
          height: 100%;
          display: flex;
          flex-direction: column;
          background: #fff;
        }

        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 16px;
          border-bottom: 1px solid #eee;
        }

        .panel-header h2 {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #666;
          padding: 0;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 4px;
        }

        .close-btn:hover {
          background: #f5f5f5;
        }

        .loading-state, .error-state, .empty-state {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 40px;
          color: #666;
        }

        .spinner {
          width: 32px;
          height: 32px;
          border: 3px solid #f3f3f3;
          border-top: 3px solid #1890ff;
          border-radius: 50%;
          animation: spin 1s linear infinite;
          margin-bottom: 12px;
        }

        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }

        .hint {
          font-size: 12px;
          color: #999;
          margin-top: 8px;
        }

        .profile-stats {
          display: flex;
          gap: 16px;
          padding: 16px;
          background: #fafafa;
          border-bottom: 1px solid #eee;
        }

        .stat-item {
          flex: 1;
          text-align: center;
          padding: 12px;
          background: #fff;
          border-radius: 8px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .stat-value {
          display: block;
          font-size: 24px;
          font-weight: 600;
          color: #1890ff;
        }

        .stat-label {
          display: block;
          font-size: 12px;
          color: #666;
          margin-top: 4px;
        }

        .profile-summary {
          padding: 12px 16px;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: #fff;
          border-radius: 8px;
          margin: 16px;
          text-align: center;
          font-size: 14px;
          line-height: 1.5;
        }

        .ontology-clusters {
          margin: 0 16px 12px;
          padding: 12px;
          border: 1px solid #dbe8ff;
          border-radius: 8px;
          background: #f7faff;
        }

        .ontology-title {
          display: flex;
          justify-content: space-between;
          color: #315a94;
          font-weight: 600;
          font-size: 13px;
        }

        .ontology-title small { color: #789; font-weight: 400; }
        .cluster-list { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
        .cluster-list span {
          padding: 4px 8px;
          border-radius: 999px;
          background: #eaf2ff;
          color: #42648d;
          font-size: 12px;
        }

        .preference-editor {
          margin: 0 16px 12px;
          padding: 12px;
          border: 1px solid #f0dce4;
          border-radius: 8px;
          background: #fff9fb;
        }

        .intent-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .intent-row input, .add-tag-row input[type="text"] {
          flex: 1;
          min-width: 160px;
          padding: 7px;
          border: 1px solid #ddd;
          border-radius: 6px;
        }

        .intent-row button, .blocked-list button, .remove-tag, .score-button, .add-tag-row button {
          border: 1px solid #e6ccd6;
          border-radius: 5px;
          background: white;
          cursor: pointer;
        }

        .confidence { color: #777; font-size: 12px; margin: 8px 0 0; }
        .interest-periods {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
          margin: 0 16px 12px;
          padding: 10px;
          border: 1px solid #e6edf5;
          border-radius: 8px;
          background: #fbfdff;
        }
        .interest-periods div { display: flex; flex-direction: column; gap: 4px; }
        .interest-periods strong { font-size: 12px; color: #334e68; }
        .interest-periods small, .interest-periods p { font-size: 11px; color: #708090; margin: 0; }
        .interest-periods p { grid-column: 1 / -1; }
        .blocked-list { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; font-size: 12px; }
        .remove-tag { margin-left: 5px; color: #a44; }
        .score-button { margin-left: 4px; min-width: 22px; color: #456; }

        .add-tag-row {
          display: grid;
          grid-template-columns: minmax(110px, 1fr) minmax(80px, 0.8fr) auto auto;
          align-items: center;
          gap: 7px;
          padding-bottom: 12px;
          border-bottom: 1px solid #eee;
          margin-bottom: 12px;
          font-size: 12px;
        }

        .add-tag-row input:first-child {
          padding: 7px;
          border: 1px solid #ddd;
          border-radius: 6px;
        }

        .tab-nav {
          display: flex;
          border-bottom: 1px solid #eee;
        }

        .tab-nav button {
          flex: 1;
          padding: 12px;
          background: none;
          border: none;
          cursor: pointer;
          font-size: 14px;
          color: #666;
          border-bottom: 2px solid transparent;
          transition: all 0.2s;
        }

        .tab-nav button.active {
          color: #1890ff;
          border-bottom-color: #1890ff;
        }

        .tab-nav button:hover {
          background: #f5f5f5;
        }

        .tab-content {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
          min-height: 0;
          max-height: 50vh;
        }

        .tags-chart {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .tag-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .tag-info {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .tag-name {
          font-size: 14px;
          color: #333;
        }

        .tag-score {
          font-size: 12px;
          color: #999;
        }

        .tag-bar-container {
          height: 8px;
          background: #f0f0f0;
          border-radius: 4px;
          overflow: hidden;
        }

        .tag-bar {
          height: 100%;
          background: linear-gradient(90deg, #1890ff, #36cfc9);
          border-radius: 4px;
          transition: width 0.3s ease;
        }

        .ups-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          overflow-y: auto;
          max-height: 45vh;
        }

        .up-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          background: #fafafa;
          border-radius: 8px;
        }

        .up-avatar {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 600;
          font-size: 16px;
        }

        .up-info {
          flex: 1;
          display: flex;
          flex-direction: column;
        }

        .up-name {
          font-size: 14px;
          color: #333;
          font-weight: 500;
        }

        .up-score {
          font-size: 12px;
          color: #999;
          margin-top: 2px;
        }

        .panel-footer {
          padding: 16px;
          border-top: 1px solid #eee;
          display: flex;
          gap: 12px;
        }

        .btn {
          flex: 1;
          padding: 10px 16px;
          border-radius: 6px;
          font-size: 14px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn-outline {
          background: #fff;
          border: 1px solid #d9d9d9;
          color: #333;
        }

        .btn-outline:hover {
          border-color: #1890ff;
          color: #1890ff;
        }
      `}</style>
    </div>
  );
}
