"use client";

import { useState, useEffect } from "react";
import { recommendationsApi, VideoRecommendation } from "@/lib/api";

interface RecommendationsPanelProps {
  sessionId: string;
  onClose?: () => void;
}

export default function RecommendationsPanel({ sessionId, onClose }: RecommendationsPanelProps) {
  const [recommendations, setRecommendations] = useState<VideoRecommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // 加载推荐
  const loadRecommendations = async () => {
    setLoading(true);
    try {
      const res = await recommendationsApi.get(sessionId, 10, "all");
      if (res.success) {
        setRecommendations(res.recommendations);
      }
    } catch (error) {
      console.error("获取推荐失败:", error);
      showMessage("error", "获取推荐失败");
    } finally {
      setLoading(false);
    }
  };

  // 提交反馈
  const submitFeedback = async (bvid: string, action: string) => {
    try {
      const res = await recommendationsApi.feedback(sessionId, bvid, action);
      if (res.success) {
        showMessage("success", "反馈已记录");
        // 移除该推荐
        setRecommendations(prev => prev.filter(r => r.bvid !== bvid));
      }
    } catch (error) {
      console.error("提交反馈失败:", error);
    }
  };

  const showMessage = (type: "success" | "error", text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 3000);
  };

  // 初始化加载
  useEffect(() => {
    loadRecommendations();
  }, [sessionId]);

  return (
    <div className="recommendations-panel">
      <div className="panel-header">
        <h2>推荐视频</h2>
        {onClose && (
          <button className="close-btn" onClick={onClose}>×</button>
        )}
      </div>

      {message && (
        <div className={`message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="action-bar">
        <button onClick={loadRecommendations} disabled={loading}>
          {loading ? "加载中..." : "刷新推荐"}
        </button>
        <button onClick={() => recommendationsApi.updateInterest(sessionId)}>
          更新画像
        </button>
      </div>

      {recommendations.length === 0 ? (
        <div className="empty-state">
          {loading ? "加载中..." : "暂无推荐内容"}
        </div>
      ) : (
        <div className="recommendations-list">
          {recommendations.map((rec) => (
            <div key={rec.bvid} className="recommendation-item">
              <div className="rec-info">
                <a
                  href={`https://www.bilibili.com/video/${rec.bvid}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <h3>{rec.title}</h3>
                </a>
                <p className="author">{rec.author}</p>
                <p className="reason">{rec.reason}</p>
                {rec.play !== undefined && (
                  <p className="stats">播放: {rec.play.toLocaleString()}</p>
                )}
              </div>
              <div className="rec-actions">
                <button
                  className="like-btn"
                  onClick={() => submitFeedback(rec.bvid, "viewed")}
                  title="看过"
                >
                  ✓
                </button>
                <button
                  className="dismiss-btn"
                  onClick={() => submitFeedback(rec.bvid, "dismissed")}
                  title="不感兴趣"
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <style jsx>{`
        .recommendations-panel {
          background: white;
          border-radius: 8px;
          padding: 20px;
          max-width: 800px;
          max-height: 80vh;
          overflow-y: auto;
        }

        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
        }

        .panel-header h2 {
          margin: 0;
          font-size: 20px;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #666;
        }

        .message {
          padding: 10px;
          border-radius: 4px;
          margin-bottom: 15px;
        }

        .message.success {
          background: #d4edda;
          color: #155724;
        }

        .message.error {
          background: #f8d7da;
          color: #721c24;
        }

        .action-bar {
          display: flex;
          gap: 30px;
          margin-bottom: 20px;
          justify-content: center;
        }

        .action-bar button {
          padding: 10px 20px;
          border: none;
          background: linear-gradient(135deg, #ff5a9d 0%, #ff9ec4 100%);
          color: white;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.3s ease;
          font-size: 15px;
          font-weight: 500;
        }

        .action-bar button:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(255, 94, 157, 0.3);
        }

        .action-bar button:disabled {
          background: #ccc;
          cursor: not-allowed;
        }

        .empty-state {
          text-align: center;
          color: #666;
          padding: 40px;
        }

        .recommendations-list {
          display: flex;
          flex-direction: column;
          gap: 15px;
        }

        .recommendation-item {
          display: flex;
          justify-content: space-between;
          padding: 15px;
          border: 1px solid #eee;
          border-radius: 8px;
          transition: all 0.3s ease;
        }

        .recommendation-item:hover {
          border-color: #ff5a9d;
          box-shadow: 0 2px 8px rgba(255, 94, 157, 0.1);
        }

        .rec-info h3 {
          margin: 0 0 5px 0;
          font-size: 16px;
        }

        .rec-info a {
          color: #ff5a9d;
          text-decoration: none;
        }

        .rec-info a:hover {
          text-decoration: underline;
        }

        .rec-info .author {
          color: #666;
          margin: 5px 0;
          font-size: 14px;
        }

        .rec-info .reason {
          color: #28a745;
          margin: 5px 0;
          font-size: 13px;
        }

        .rec-info .stats {
          color: #666;
          margin: 5px 0;
          font-size: 12px;
        }

        .rec-actions {
          display: flex;
          flex-direction: column;
          gap: 5px;
        }

        .rec-actions button {
          width: 30px;
          height: 30px;
          border: none;
          border-radius: 50%;
          cursor: pointer;
          transition: all 0.3s ease;
        }

        .like-btn {
          background: #28a745;
          color: white;
        }

        .like-btn:hover {
          background: #218838;
          transform: scale(1.1);
        }

        .dismiss-btn {
          background: #dc3545;
          color: white;
        }

        .dismiss-btn:hover {
          background: #c82333;
          transform: scale(1.1);
        }
      `}</style>
    </div>
  );
}
