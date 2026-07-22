# 推荐闭环 MVP

## 目标与边界

推荐主链路采用确定性的规则特征排序，LLM 仅是可选的 Top-N 辅助能力。系统不包含协同过滤、在线模型训练、Learning-to-Rank、真实播放完成率或 A/B 实验平台。

“标记想看”只记录本产品内的推荐偏好，不声称已写入 B 站稍后再看；“一键收藏”会先读取当前会话已同步的收藏夹，用户选择目标并二次确认后才执行 B 站写入。移动、删除收藏等不可逆操作不属于推荐 MVP。

## 数据流

```text
时序长期兴趣 + 近期兴趣 + 本体多兴趣簇 + 当前明确意图
  → 兴趣 / 近期兴趣 / 分区 / 热榜 / 关注UP / 关注动态 / 系列追更 / 当前主题召回
  → 重温收藏模式下的本地 Chroma 向量召回
  → 已收藏、已看、已拒绝、已屏蔽、近期曝光过滤
  → 可解释规则评分
  → 可选 LLM 25% 辅助分（失败自动降级）
  → MMR + UP主硬上限 + 来源/时长覆盖重排
  → 基于真实特征的理由
  → 批次、算法版本和特征快照
  → 曝光、点击和细分反馈
  → 下一轮时间衰减加权或硬过滤
```

每个网络召回通道受 3 个并发槽限制，单次超时 45 秒，失败重试一次并退避 0.5 秒。单个通道失败只会减少候选，不会让其他通道失效。

## 画像

`app/services/recommendation/profile_schema.py` 是推荐侧稳定 Schema，兼容 `interest_tags`、`unified_tags` 和 `top_interests` 等旧字段：

- `interest_tags`：长期兴趣。
- `recent_interests`：近期行为兴趣。
- `current_intent`：用户在画像面板或本次推荐请求中明确输入的意图。
- `concept_affinities`、`recent_concept_affinities`：时间衰减后的规范概念偏好。
- `multi_interests`：不把所有偏好压进单个向量的多个语义兴趣簇。
- `source_freshness`：各通道的数量、时间覆盖、最新事件和生效权重。
- `followed_ups`、分区、内容类型及置信度：其他稳定画像维度。

推荐时按 `RECOMMENDATION_PROFILE_MAX_AGE_HOURS` 检查 `updated_at`。过期后优先使用已同步到本地的数据增量刷新；刷新失败保留旧画像，推荐接口不因此中断。前端允许新增、删除、调高或调低标签，设置当前想看、清除近期偏好，以及解除主题/UP 屏蔽。

Agent 已有 `update_profile_from_conversation` 工具可以从对话摘要更新短期兴趣。推荐服务也会自动使用已保存的 `current_intent`；直接请求中的 `query` 优先级更高。它们是当前会话主题的可解释替代，不把整段私人对话写进推荐批次。

## 召回通道

- `interest`：长期高权重标签搜索。
- `recent_interest`：近期标签按发布时间搜索。
- `category`：偏好分区热榜。
- `trending`：全站热榜，用于冷启动和探索。
- `followed_up`：关注 UP 主新内容。
- `dynamic_following`：关注动态中的近期投稿，只作候选源，不自动转为正偏好。
- `series_update`：本地“正在追”系列的近期内容。
- `context_query`：当前明确主题；“更多类似”使用视频标题或命中标签作为查询。
- `vector_rediscovery`：仅在“重温收藏”模式启用，只从当前会话自己的本地收藏/Chroma 结果中召回，并综合语义距离和收藏时间。

去重会合并 `recall_sources`，保留最佳 `raw_recall_score`。普通模式过滤已收藏；重温收藏模式显式允许返回自己的旧收藏。

## 排序与多样性

`app/services/recommendation/ranking.py` 是权威实现。默认权重通过 `RECOMMENDATION_SCORING_WEIGHTS` 配置：

- 内容匹配 18%
- 本体语义匹配 17%
- 近期兴趣 16%
- 多兴趣簇匹配 10%
- UP 主偏好 10%
- 新鲜度 9%
- 质量 8%
- 探索价值 7%
- 当前场景 5%

质量分使用“播放量 ÷ 发布天数”的播放速度再做对数平滑，避免老热门只靠累计播放量长期占优。反馈亲和度、模式奖励、重复疲劳和负反馈作为可追踪的增减项。最终执行 MMR 风格重排，同一 UP 默认最多两条，同时奖励不同召回来源和长/中/短时长覆盖。

模式包括：随便看看、学习提升、放松娱乐、关注追更、探索新领域和重温收藏；请求还可提供最大时长与探索程度。

LLM 默认关闭。开启后只处理规则 Top-N，最终占比 25%；缺失、非法、非有限值或统一分数不会抹平规则差异。理由生成失败时使用规则模板，只引用命中兴趣、召回来源、关注关系、新鲜度和探索目的等已有事实。

## 事件与反馈语义

`recommendation_batches` 保存批次、算法版本、上下文、请求/返回数量和逐条特征快照。`recommendation_events` 支持：

- `impression`、`click`：真实展示与打开 B 站链接。
- `like`、`favorite`、`watch_later`：正反馈，分别使用不同强度并按 30 天半衰期衰减。
- `viewed`：用户明确表示已看过，后续排除同一视频。
- `dismiss`：排除同一视频；`not_relevant` 会迁移为主题/UP 负偏好，半衰期 14 天。
- `temporary`、`too_long`、`too_old`：较弱的临时负反馈，半衰期分别为 3/7/7 天，不污染主题或 UP 偏好。
- `block_topic`、`block_up`：持续硬过滤，直到用户显式解除。
- `unblock_topic`、`unblock_up`：保留审计记录的撤销事件。

同一批次、同一视频、同一事件自动去重。近期曝光默认 7 天内不重复；已收藏、已看、已拒绝在普通推荐中排除。

## API 与前端

- `POST /recommendations/`：生成推荐，支持 `mode`、`query`、`max_duration`、`exploration_level`。
- `POST /recommendations/events`：记录曝光、点击等原始事件。
- `POST /recommendations/feedback`：记录喜欢、已看、想看、细分拒绝和屏蔽。
- `GET|PUT /recommendations/preferences/{session_id}`：读取和编辑画像。
- `POST /recommendations/preferences/{session_id}/unblock`：解除屏蔽。
- `GET /recommendations/metrics/{session_id}?days=30`：最小指标。
- `GET /recommendations/profile-sources/{session_id}`：画像通道覆盖、采集数和新鲜度审计。
- `POST /recommendations/favorite/preview`：只读预览当前会话收藏夹。
- `POST /recommendations/favorite/execute`：要求 `confirmed=true` 且目标收藏夹属于当前会话，随后才执行真实收藏。

推荐卡展示封面、标题、UP、时长、发布时间、来源、可信理由、特征分、算法版本和批次，并提供所有上述反馈操作。

## 指标解释

指标面板计算曝光、CTR、收藏率、拒绝率、重复曝光率、主题覆盖、UP 覆盖、各召回通道贡献及拒绝原因分布。全部来自已记录事件，不伪造线上提升。

点击后观看率是“点击事件之后，在后续同步的 B 站观看历史中出现相同 BVID”的推断指标。返回值固定声明 `watch_completion_available: false`；该指标不等于播放完成率。

## 配置

环境变量及默认值见 `.env.example`：

- `RECOMMENDATION_ALGORITHM_VERSION`
- `RECOMMENDATION_LLM_RERANK_ENABLED`
- `RECOMMENDATION_LLM_TOP_N`
- `RECOMMENDATION_LLM_TIMEOUT_SECONDS`
- `RECOMMENDATION_RECENT_EXPOSURE_DAYS`
- `RECOMMENDATION_MAX_PER_UP`
- `RECOMMENDATION_PROFILE_MAX_AGE_HOURS`
- `RECOMMENDATION_SCORING_WEIGHTS`（JSON）

新表由现有 `init_db()` 的 `Base.metadata.create_all()` 以 `checkfirst` 兼容创建，未修改上游 DeerFlow。正式生产环境建议后续引入 Alembic 管理迁移。

## 验证

```bash
python -m compileall -q app scripts
python -m pytest -q
cd frontend
npm run lint
npm run build
```

测试覆盖：画像字段统一、本体 SHACL/别名/关系方向、旧收藏和旧追番衰减、多兴趣簇、新鲜度、正负反馈与临时反馈、召回去重、时间归一质量、多样性约束、LLM 非法/统一分降级、事件去重/撤销、批次追踪和指标推断。

## 已知限制与下一阶段

- 只有单用户内容与规则信号，没有协同过滤、训练排序或跨用户数据。
- B 站站外播放完成率不可观测；只能关联后续观看历史。
- “更多类似”当前是主题/标题搜索，不是 B 站内部相关视频接口。
- 本地向量召回依赖已构建的 Chroma 收藏知识库；不可用时安全跳过。
- “标记想看”是本地反馈，不会写入 B 站稍后再看。
- 指标可用于闭环验证，但没有对照实验时不能归因推荐质量提升。
