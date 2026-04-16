"use client";

import { useState, useEffect } from "react";

interface ScheduleTask {
  id: string;
  task_type: string;
  schedule_type: string;
  next_run_time?: string;
  created_at: string;
  status?: "active" | "paused";
}

interface ScheduleManagerProps {
  sessionId: string;
  folderIds: number[];
  onClose?: () => void;
}

export default function ScheduleManager({ sessionId, folderIds, onClose }: ScheduleManagerProps) {
  const [tasks, setTasks] = useState<ScheduleTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    fetchTasks();
  }, [sessionId]);

  const showMessage = (type: "success" | "error", text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 3000);
  };

  const fetchTasks = async () => {
    setLoading(true);
    setError(null);
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_BASE_URL}/schedule/tasks/${sessionId}`);
      const data = await response.json();

      if (data.success) {
        setTasks(data.tasks || []);
      } else {
        setTasks([]);
      }
    } catch (err) {
      console.error("获取任务失败:", err);
      setError("获取任务失败");
    } finally {
      setLoading(false);
    }
  };

  const createTask = async (taskType: string) => {
    setCreating(taskType);
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      let endpoint = "";
      let body: any = { session_id: sessionId };

      switch (taskType) {
        case "sync":
          endpoint = "/schedule/tasks/sync";
          body.folder_ids = folderIds;
          body.schedule_type = "daily";
          break;
        case "recommendation":
          endpoint = "/schedule/tasks/recommendation";
          body.interval_minutes = 60;
          break;
        case "auto-collect":
          endpoint = "/schedule/tasks/auto-collect";
          body.schedule_type = "daily";
          body.limit = 5;
          break;
      }

      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await response.json();

      if (data.success) {
        showMessage("success", "任务创建成功");
        fetchTasks();
      } else {
        showMessage("error", data.message || "创建失败");
      }
    } catch (err) {
      console.error("创建任务失败:", err);
      showMessage("error", "创建任务失败");
    } finally {
      setCreating(null);
    }
  };

  const pauseTask = async (taskId: string) => {
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_BASE_URL}/schedule/tasks/${taskId}/pause`, {
        method: "POST",
      });

      const data = await response.json();

      if (data.success) {
        showMessage("success", "任务已暂停");
        fetchTasks();
      } else {
        showMessage("error", data.message || "操作失败");
      }
    } catch (err) {
      console.error("暂停任务失败:", err);
      showMessage("error", "暂停任务失败");
    }
  };

  const resumeTask = async (taskId: string) => {
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_BASE_URL}/schedule/tasks/${taskId}/resume`, {
        method: "POST",
      });

      const data = await response.json();

      if (data.success) {
        showMessage("success", "任务已恢复");
        fetchTasks();
      } else {
        showMessage("error", data.message || "操作失败");
      }
    } catch (err) {
      console.error("恢复任务失败:", err);
      showMessage("error", "恢复任务失败");
    }
  };

  const deleteTask = async (taskId: string) => {
    if (!confirm("确定要删除这个任务吗？")) return;

    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_BASE_URL}/schedule/tasks/${taskId}`, {
        method: "DELETE",
      });

      const data = await response.json();

      if (data.success) {
        showMessage("success", "任务已删除");
        fetchTasks();
      } else {
        showMessage("error", data.message || "删除失败");
      }
    } catch (err) {
      console.error("删除任务失败:", err);
      showMessage("error", "删除任务失败");
    }
  };

  const runTaskNow = async (taskId: string) => {
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_BASE_URL}/schedule/tasks/${taskId}/run`, {
        method: "POST",
      });

      const data = await response.json();

      if (data.success) {
        showMessage("success", "任务已开始执行");
      } else {
        showMessage("error", data.message || "执行失败");
      }
    } catch (err) {
      console.error("执行任务失败:", err);
      showMessage("error", "执行任务失败");
    }
  };

  const getTaskIcon = (taskType: string) => {
    switch (taskType) {
      case "sync":
        return "🔄";
      case "recommendation":
        return "🎬";
      case "auto-collect":
        return "📤";
      case "profile_build":
        return "📊";
      default:
        return "⏰";
    }
  };

  const getTaskName = (taskType: string) => {
    switch (taskType) {
      case "sync":
        return "收藏夹同步";
      case "recommendation":
        return "推荐检查";
      case "auto-collect":
        return "智能投送";
      case "profile_build":
        return "画像构建";
      default:
        return taskType;
    }
  };

  const getTaskDescription = (task: ScheduleTask) => {
    switch (task.schedule_type) {
      case "daily":
        return "每天执行";
      case "hourly":
        return "每小时执行";
      case "interval":
        return "定时执行";
      default:
        return task.schedule_type;
    }
  };

  return (
    <div className="schedule-manager">
      <div className="panel-header">
        <h2>定时任务</h2>
        {onClose && (
          <button className="close-btn" onClick={onClose}>×</button>
        )}
      </div>

      {message && (
        <div className={`message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="create-section">
        <h3>创建新任务</h3>
        <div className="create-buttons">
          <button
            className="create-btn"
            onClick={() => createTask("sync")}
            disabled={creating !== null || folderIds.length === 0}
            title={folderIds.length === 0 ? "请先选择收藏夹" : ""}
          >
            <span className="btn-icon">🔄</span>
            <span className="btn-text">收藏夹同步</span>
            {creating === "sync" && <span className="creating">...</span>}
          </button>
          <button
            className="create-btn"
            onClick={() => createTask("recommendation")}
            disabled={creating !== null}
          >
            <span className="btn-icon">🎬</span>
            <span className="btn-text">推荐检查</span>
            {creating === "recommendation" && <span className="creating">...</span>}
          </button>
          <button
            className="create-btn"
            onClick={() => createTask("auto-collect")}
            disabled={creating !== null}
          >
            <span className="btn-icon">📤</span>
            <span className="btn-text">智能投送</span>
            {creating === "auto-collect" && <span className="creating">...</span>}
          </button>
        </div>
      </div>

      <div className="tasks-section">
        <h3>已创建的任务</h3>

        {loading ? (
          <div className="loading-state">
            <div className="spinner"></div>
            <span>加载中...</span>
          </div>
        ) : error ? (
          <div className="error-state">
            <p>{error}</p>
            <button onClick={fetchTasks}>重试</button>
          </div>
        ) : tasks.length === 0 ? (
          <div className="empty-state">
            <p>暂无定时任务</p>
            <p className="hint">点击上方按钮创建新任务</p>
          </div>
        ) : (
          <div className="tasks-list">
            {tasks.map((task) => (
              <div key={task.id} className="task-item">
                <div className="task-icon">{getTaskIcon(task.task_type)}</div>
                <div className="task-info">
                  <div className="task-name">{getTaskName(task.task_type)}</div>
                  <div className="task-meta">
                    <span className="task-desc">{getTaskDescription(task)}</span>
                    {task.next_run_time && (
                      <span className="task-next">下次: {task.next_run_time}</span>
                    )}
                  </div>
                </div>
                <div className="task-actions">
                  <button
                    className="action-btn run"
                    onClick={() => runTaskNow(task.id)}
                    title="立即执行"
                  >
                    ▶
                  </button>
                  {task.status === "paused" ? (
                    <button
                      className="action-btn resume"
                      onClick={() => resumeTask(task.id)}
                      title="恢复"
                    >
                      ▶
                    </button>
                  ) : (
                    <button
                      className="action-btn pause"
                      onClick={() => pauseTask(task.id)}
                      title="暂停"
                    >
                      ⏸
                    </button>
                  )}
                  <button
                    className="action-btn delete"
                    onClick={() => deleteTask(task.id)}
                    title="删除"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style jsx>{`
        .schedule-manager {
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

        .message {
          padding: 12px 16px;
          font-size: 14px;
          text-align: center;
        }

        .message.success {
          background: #f6ffed;
          color: #52c41a;
          border-bottom: 1px solid #b7eb8f;
        }

        .message.error {
          background: #fff2f0;
          color: #ff4d4f;
          border-bottom: 1px solid #ffccc7;
        }

        .create-section {
          padding: 16px;
          border-bottom: 1px solid #eee;
        }

        .create-section h3 {
          margin: 0 0 12px 0;
          font-size: 14px;
          color: #666;
        }

        .create-buttons {
          display: flex;
          gap: 12px;
        }

        .create-btn {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 16px 12px;
          background: #fafafa;
          border: 1px solid #d9d9d9;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s;
          position: relative;
        }

        .create-btn:hover:not(:disabled) {
          border-color: #1890ff;
          background: #e6f7ff;
        }

        .create-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .btn-icon {
          font-size: 24px;
        }

        .btn-text {
          font-size: 12px;
          color: #333;
        }

        .creating {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          background: rgba(255,255,255,0.9);
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 12px;
        }

        .tasks-section {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }

        .tasks-section h3 {
          margin: 0 0 12px 0;
          font-size: 14px;
          color: #666;
        }

        .loading-state, .error-state, .empty-state {
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

        .tasks-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .task-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          background: #fafafa;
          border-radius: 8px;
          border: 1px solid #eee;
        }

        .task-icon {
          font-size: 24px;
          width: 40px;
          height: 40px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #fff;
          border-radius: 8px;
        }

        .task-info {
          flex: 1;
        }

        .task-name {
          font-size: 14px;
          color: #333;
          font-weight: 500;
        }

        .task-meta {
          display: flex;
          gap: 12px;
          margin-top: 4px;
        }

        .task-desc, .task-next {
          font-size: 12px;
          color: #999;
        }

        .task-actions {
          display: flex;
          gap: 8px;
        }

        .action-btn {
          width: 32px;
          height: 32px;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          transition: all 0.2s;
        }

        .action-btn.run {
          background: #e6f7ff;
          color: #1890ff;
        }

        .action-btn.run:hover {
          background: #bae7ff;
        }

        .action-btn.pause {
          background: #fff7e6;
          color: #faad14;
        }

        .action-btn.pause:hover {
          background: #ffe58f;
        }

        .action-btn.resume {
          background: #e6fffb;
          color: #13c2c2;
        }

        .action-btn.resume:hover {
          background: #b5f5ec;
        }

        .action-btn.delete {
          background: #fff1f0;
          color: #ff4d4f;
        }

        .action-btn.delete:hover {
          background: #ffccc7;
        }
      `}</style>
    </div>
  );
}
