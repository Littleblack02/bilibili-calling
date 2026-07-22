# Ontology、问答、推荐与用户画像 V2：TODO、排期与 Goal 模式提示词

> 编制日期：2026-07-21
> 适用项目：`E:\bilibili-calling-main`
> 估算方式：1 名全职开发者或 1 个持续工作的 Codex Goal，约 8 周。
> 完成原则：日期是目标，不是“完成”依据；只有通过对应验收门槛，阶段才能关闭。

## 1. 当前基线

开始 V2 前先固定当前基线，后续所有“提升”必须相对基线测量，不允许只凭主观感觉宣称推荐或问答更准。

- 本体：`bili-ontology-1.0.0`，约 42 个概念、273 条 RDF 三元组。
- 本体能力：SKOS 标签与关系、SHACL 基础校验、确定性实体链接、有界图扩展。
- 问答：Chroma 向量检索、本体查询扩展、RRF 融合、LLM 回答。
- 推荐：来源时间衰减、多兴趣簇、本体匹配、规则排序、MMR 多样性、可选 LLM 辅助。
- 画像通道：收藏、追番、影视、历史、稍后看、关注、课程、话题、专栏、笔记、追漫、直播、动态等。
- 当前自动验证：Python 测试 26 项通过；前端 lint 0 error；Next.js build 通过。

### 当前最重要的已知问题

1. 时间衰减后的概念分数再次除以最大值，可能把唯一一个很旧的兴趣重新归一成 `1.0`。
2. RAG 对每个本体扩展查询都强制取 Top-K，没有相关度阈值，扩展概念可能引入噪声。
3. `UserContentSignal.is_active` 只会被设为 `True`，取消关注、删除稍后看等快照型信号不会正常失效。
4. 大部分扩展 B站通道只取第一页，覆盖通道不等于覆盖完整数据。
5. 关注 UP 召回通过名称搜索，项目已有 `get_up_videos`，但尚未完成可靠 WBI 直连召回。
6. 本体约 42 个概念，AI/编程密度高，游戏、动画、音乐、影视等领域语义过浅。
7. 实体链接主要是字符串包含，缺少上下文消歧、候选排序和拒识机制。
8. 视频概念是视频级，不是 chunk/时间码级，问答引用无法精确到片段。
9. 推荐反馈仍以原始 topic 字符串为主，没有形成完整的概念级反馈传播。
10. Cookie 当前明文入库，缺少加密、轮换和用户数据删除流程。
11. 数据库依赖 `create_all` 和手写兼容迁移，缺少 Alembic 版本化迁移。
12. 测试能证明代码可运行，但缺少问答金标集、实体链接金标集和推荐时间切分评估集。

## 2. V2 最终目标与量化验收标准

### 2.1 本体与实体链接

- 建立不少于 300 条人工审阅样本，覆盖 AI、游戏、动画、音乐、影视、知识、生活等领域。
- 实体链接 Precision ≥ 92%。
- 实体链接 Recall ≥ 85%。
- 实体链接 F1 ≥ 88%。
- 歧义样本的“正确拒识率”≥ 90%。
- 短 ASCII 别名误匹配率 < 2%。
- 所有本体文件通过 SHACL，且不存在 `broader` 环、非法关系范围和重复语言首选标签。
- 本体版本从 RDF 中读取，不再由 Python 常量单独维护。

### 2.2 问答与 RAG

- 建立 120～200 条问题金标集，包含：同义词、跨视频综合、否定问题、无答案问题、时间码问题和歧义问题。
- Retrieval Recall@5 ≥ 85%。
- Retrieval MRR@10 ≥ 0.75。
- 引用正确率 ≥ 95%。
- 有证据问题的 groundedness ≥ 90%。
- 无证据问题的正确拒答率 ≥ 90%。
- 事实性幻觉率 ≤ 5%。
- 每条来源至少能返回 `bvid + chunk_index`；具备时间码时返回 `start_time/end_time`。
- 本地检索阶段在 1 万 chunk 规模下 p95 ≤ 800ms，不包含远程 LLM 生成时间。

### 2.3 推荐

- 用严格时间切分构建离线评估集，禁止随机打散未来行为。
- 相比当前 `temporal-ontology-xmix-v2` 基线：
  - NDCG@10 相对提升 ≥ 10%。
  - Recall@20 相对提升 ≥ 8%。
  - HitRate@10 相对提升 ≥ 8%。
  - 推荐列表内部多样性不得低于基线。
  - 主题覆盖率相对提升 ≥ 10%，同时保持相关性指标不下降。
- 同一概念、同一强度下，730 天前收藏的有效贡献 ≤ 1 天前观看历史贡献的 25%。
- 只有旧收藏、没有近期行为时，画像绝对置信度不得被归一成满分；推荐理由必须明确是“历史兴趣”而不是“近期兴趣”。
- 排序 200 个已补全候选的本地计算 p95 ≤ 300ms。
- 所有推荐批次保留算法版本、特征、概念命中、关系路径、召回源和画像版本。

### 2.4 B站画像同步

- 所有支持通道都有分页或游标策略、采样上限、超时、重试和错误状态。
- 快照型信号在一次成功全量同步后可以失效；同步失败不得误失效。
- 事件型信号按事件时间保存，不被快照失效逻辑删除。
- 同一内容跨通道重复产生的画像贡献经过相关性去重，重复贡献率 < 1%。
- 每个通道记录：开始/结束时间、耗时、状态码、获取条数、游标和错误摘要。
- 受支持通道的录制响应契约测试覆盖率 100%。
- 对无法获取的全量点赞、投币和完播数据继续明确标记为 unavailable，不允许伪造。

### 2.5 安全与工程质量

- 数据库内不存在明文 `SESSDATA`、`bili_jct`。
- 日志、异常和 API 响应不输出完整 Cookie。
- 支持 Cookie 密钥轮换和用户数据删除。
- 所有数据库变化通过 Alembic 管理，并在临时旧数据库副本上验证升级。
- 后端测试、SHACL、前端 lint、前端 build、迁移测试、契约测试全部通过。
- 新增核心代码具有单元测试；远程 API 使用脱敏 fixture，不依赖 CI 真实账号。

## 3. 总体排期

| 阶段 | 日期 | 重点 | 退出条件 |
|---|---|---|---|
| Phase 0 | 2026-07-21～07-22 | 基线、评估框架、Feature Flag、安全准备 | 基线报告和测试数据格式固定 |
| Phase 1 | 2026-07-23～07-27 | 时间权重绝对校准、重复信号控制 | 旧兴趣不再被重新放大 |
| Phase 2 | 2026-07-28～08-05 | RAG 阈值、重排、引用、chunk 概念 | RAG 金标集达到首轮门槛 |
| Phase 3 | 2026-08-06～08-14 | 同步批次、分页、游标、失效 | 快照和事件同步语义正确 |
| Phase 4 | 2026-08-15～08-21 | UP 直连召回、候选 Hydration、召回校准 | 候选字段完整且召回稳定 |
| Phase 5 | 2026-08-22～09-04 | 分层本体、实体链接消歧、SHACL V2 | 本体与链接金标指标达标 |
| Phase 6 | 2026-09-05～09-12 | 概念反馈闭环、离线推荐评估、消融实验 | 推荐离线指标达到门槛 |
| Phase 7 | 2026-09-13～09-18 | Alembic、监控、前端解释、灰度发布 | 完整 Definition of Done 通过 |

如果有两名开发者，可并行执行：

- A：Phase 1 → Phase 2 → Phase 5。
- B：Phase 0 安全部分 → Phase 3 → Phase 4 → Phase 7。
- Phase 6 必须等待 Phase 1、2、4、5 的稳定版本。

## 4. 分阶段 TODO

## Phase 0：基线、评估框架与安全护栏

**时间：2026-07-21～2026-07-22**

### TODO 0.1：固定可重复基线

- [ ] 记录当前 Git 状态、Python/Node 版本、依赖版本和配置摘要，不记录任何密钥。
- [ ] 运行并保存：
  - `python -m compileall -q app scripts`
  - `python -m pytest -q`
  - ontology SHACL 校验
  - `npm run lint`
  - `npm run build`
- [ ] 建立 `reports/baseline/`，保存 JSON 格式的测试和指标摘要。
- [ ] 为当前推荐算法固定 `baseline_algorithm_version`。
- [ ] 为当前 RAG 固定一份检索输出快照，避免后续只能凭印象比较。

**使用工具：** Python、pytest、RDFLib、pySHACL、Next.js、Git 只读检查。
**产出：** `reports/baseline/baseline.json`、环境摘要、当前指标。
**验收：** 任意开发机使用同一配置能复现基线测试；报告不含 Cookie/API Key。

### TODO 0.2：建立三类金标数据格式

- [ ] 创建 `evaluation/entity_linking.jsonl`。
- [ ] 创建 `evaluation/rag_qa.jsonl`。
- [ ] 创建 `evaluation/recommendation_events.jsonl` 或从脱敏数据库导出。
- [ ] 每条数据包含 schema version。
- [ ] 划分 `train/dev/test`；测试集一旦确定，调参过程中不反复查看答案。
- [ ] 推荐数据必须按时间切分，保存 cutoff timestamp。

建议格式：

```json
{"id":"el-001","text":"LangGraph Agent 实战","expected_concepts":[".../LangGraph",".../Agent"],"ambiguous":false}
{"id":"qa-001","question":"RAG 的索引阶段有哪些步骤？","expected_bvids":["BV..."],"answerable":true,"key_facts":["切分","向量化","入库"]}
{"session_hash":"...","event_time":"2026-01-01T00:00:00","event_type":"viewed","bvid":"BV..."}
```

**使用工具：** JSONL、Pydantic schema、pytest parameterization。
**产出：** 数据 schema、样例、校验脚本。
**验收：** 非法数据能被校验器拒绝；数据中无 session_id、Cookie、用户名等直接身份信息。

### TODO 0.3：Feature Flag 和回滚准备

- [ ] 增加：
  - `TEMPORAL_AFFINITY_V2_ENABLED`
  - `RAG_GROUNDED_V2_ENABLED`
  - `PROFILE_SYNC_V2_ENABLED`
  - `ONTOLOGY_LINKER_V2_ENABLED`
  - `CANDIDATE_HYDRATION_ENABLED`
- [ ] 每个新模块能够回退到 V1。
- [ ] 批次快照保存实际启用的 flag。
- [ ] 不允许两个版本共写互不兼容的数据而不记录 schema version。

**使用工具：** Pydantic Settings、环境变量、推荐批次 context。
**验收：** 每个 flag 有测试；关闭 flag 后旧测试仍通过。

### TODO 0.4：Cookie 安全设计先行

- [ ] 设计 `CookieCipher` 接口，使用 `cryptography` 的 AES-GCM 或 Fernet。
- [ ] 增加 `BILIBILI_COOKIE_ENCRYPTION_KEY`，不得提供不安全默认值。
- [ ] 设计密钥版本字段和轮换流程。
- [ ] 设计现有明文 Cookie 的一次性迁移。
- [ ] 所有日志字段增加 Cookie/CSRF 脱敏过滤器。
- [ ] 设计用户数据删除 API 的范围和二次确认。

**使用工具：** `cryptography`、SQLAlchemy、FastAPI、结构化日志。
**验收：** 数据库字符串搜索找不到明文测试 Cookie；错误日志不包含测试 Cookie。

## Phase 1：时间兴趣绝对校准与信号去重

**时间：2026-07-23～2026-07-27**

### TODO 1.1：拆分绝对强度和相对占比

- [ ] 将当前 `score / maximum` 归一化替换为两个值：
  - `absolute_affinity = 1 - exp(-raw_score / tau)`。
  - `relative_share = raw_score / sum(all_raw_scores)`。
- [ ] `tau` 必须通过 dev 数据校准，不直接硬编码为无法解释的常量。
- [ ] Profile schema 同时保存：
  - `concept_absolute_affinities`
  - `concept_relative_shares`
  - `profile_evidence_mass`
  - `profile_recency_confidence`
- [ ] 推荐本体分使用绝对强度控制“是否真的感兴趣”，用相对占比控制“兴趣之间的排序”。
- [ ] 老版本字段保留一个兼容周期。

**修改位置：**

- `app/services/recommendation/temporal_interest.py`
- `app/services/recommendation/profile_schema.py`
- `app/services/recommendation/ranking.py`
- `app/models.py`

**测试：**

- [ ] 只有一个 730 天旧收藏时，绝对兴趣不能为 1。
- [ ] 1 天历史行为应显著高于 730 天收藏。
- [ ] 时间未知行为不得进入近期兴趣。
- [ ] 同等时间下，明确收藏/稍后看和普通关注具有不同强度。
- [ ] 空画像、单概念画像、多概念画像均无除零和 NaN。

**验收：** 730 天收藏贡献 ≤ 1 天历史的 25%；旧数据仅保留弱先验。

### TODO 1.2：处理跨通道相关性和重复贡献

- [ ] 为行为定义语义组：`exposure`、`consumed`、`intent`、`durable_interest`、`creator_affinity`。
- [ ] 同一 BVID 在短时间内先出现在动态、后被观看、再被收藏时，不进行简单三次相加。
- [ ] 使用“最强行为 + 次强行为折扣”或 noisy-OR 合并相关信号。
- [ ] 动态曝光不得产生正兴趣，只能用于候选和疲劳控制。
- [ ] 相同内容在多个收藏夹只计一次主题贡献，但可保留多个文件夹证据。
- [ ] 保存贡献明细，能够解释最终分数来自哪些事件。

**使用工具：** SQLAlchemy、行为语义枚举、确定性聚合、pytest。
**验收：** 同一行为重复同步不改变画像；相关事件不会线性无限放大。

### TODO 1.3：改进多兴趣簇

- [ ] `top_cluster` 不再一直爬到最顶层。
- [ ] 支持配置最大上溯层数和最小簇粒度。
- [ ] 优先生成“AI Agent”“编程”“影视”等中层簇，而不是都变成“科技”。
- [ ] 候选匹配多个簇时使用 softmax attention 或温度化加权，不只取最大值。
- [ ] 每个簇保存长期强度、近期强度、证据量和最近发生时间。

**验收：** 人工构造的 LangGraph + Python + 音乐行为至少产生两个有意义的兴趣簇；簇标签不能全部是顶层分类。

## Phase 2：Grounded RAG V2

**时间：2026-07-28～2026-08-05**

### TODO 2.1：带分数的本体扩展检索

- [ ] 所有查询使用带 relevance/distance 的检索接口。
- [ ] 分别配置：
  - 原始查询阈值。
  - 同义词阈值。
  - `broader/narrower` 阈值。
  - `related/requires` 阈值。
- [ ] 原始查询在融合中权重最高。
- [ ] `related` 和反向 `requires` 默认更严格，避免语义漂移。
- [ ] 无结果时返回真实的无结果状态，不能为了凑够 K 条加入明显低相关内容。
- [ ] 记录每个结果来自哪个查询、距离、图路径和融合分。

**使用工具：** Chroma `similarity_search_with_score`、RRF 或 weighted RRF、RDFLib。
**验收：** 无关扩展词不会进入最终上下文；金标 Retrieval Recall@5 ≥ 85%。

### TODO 2.2：增加轻量级 reranker

- [ ] 在 RRF 后对最多 20～30 个 chunk 重排。
- [ ] 优先方案：已有 LLM/API 的小规模结构化 relevance 评分。
- [ ] 可选本地方案：`sentence-transformers` CrossEncoder 或中文/多语言 reranker。
- [ ] reranker 必须可关闭，失败自动使用融合排序。
- [ ] 评分输出包含 relevance、evidence completeness、query coverage。
- [ ] 固定超时和最大 token，不允许 reranker 成为单点故障。

**验收：** MRR@10 ≥ 0.75；reranker 关闭时系统仍能回答。

### TODO 2.3：chunk/时间码级概念

- [ ] 新增 `ChunkConcept` 或在向量 metadata 中保存 chunk 概念。
- [ ] 字幕 chunk 保存时间范围。
- [ ] 实体链接针对 chunk 内容单独执行，不再把整视频概念复制到每个 chunk。
- [ ] 视频级概念由 chunk 概念聚合产生。
- [ ] 来源返回 `bvid/title/chunk_index/start_time/end_time/concept_ids`。

**使用工具：** SQLAlchemy/Alembic、Chroma metadata、字幕分段器、ontology linker。
**验收：** 测试问题能定位到正确视频片段；不相关 chunk 不继承整视频概念。

### TODO 2.4：答案证据约束和拒答

- [ ] Prompt 明确要求每项事实引用对应来源。
- [ ] 上下文不足时返回“收藏知识库证据不足”。
- [ ] 如允许通用知识回答，必须返回 `grounded=false` 并与知识库回答分区展示。
- [ ] 增加返回字段：
  - `grounded`
  - `retrieval_confidence`
  - `answerability`
  - `citations`
  - `ontology_matches`
- [ ] 对引用做后验证：引用 chunk 必须包含或支持对应事实。

**验收：** 引用正确率 ≥ 95%；无答案问题正确拒答率 ≥ 90%。

## Phase 3：画像同步 V2

**时间：2026-08-06～2026-08-14**

### TODO 3.1：同步批次模型

- [ ] 新增 `ProfileSyncRun`：session、channel、status、started_at、finished_at、cursor、count、error、schema_version。
- [ ] `UserContentSignal` 增加 `last_seen_sync_id`。
- [ ] 区分 `snapshot` 和 `event_stream` 通道类型。
- [ ] 快照通道只有在成功完成全量同步时才能失效缺失数据。
- [ ] 通道超时、Cookie 失效、429、schema error 时保留旧数据。
- [ ] 支持幂等重试。

**使用工具：** SQLAlchemy、Alembic、FastAPI background job、pytest。
**验收：** 成功同步能失效已取消关注；失败同步不会失效任何旧信号。

### TODO 3.2：统一分页和游标适配器

- [ ] 定义 `PageNumberPaginator`、`CursorPaginator`、`OffsetPaginator`。
- [ ] 每个通道设置：最大页数、最大条数、时间窗口和速率限制。
- [ ] 收藏/关注等快照通道尽量完整；动态/历史采用近期窗口。
- [ ] 游标持久化，支持下一次增量同步。
- [ ] 429 使用指数退避和 jitter。
- [ ] Cookie 失效立即停止同账号后续请求，并标记认证状态。

**验收：** 多页 fixture 可以完整采集；重复执行只新增真实新增项。

### TODO 3.3：B站接口契约测试

- [ ] 为每个支持通道保存脱敏 JSON fixture。
- [ ] 测试正常响应、空数据、字段缺失、非零 code、429、超时和 HTML 错误页。
- [ ] 统一 schema adapter，不让原始响应结构渗透到画像算法。
- [ ] 增加 capability 状态：`working/degraded/auth_required/unavailable/schema_changed`。

**使用工具：** `httpx`、`respx` 或自定义 mock transport、pytest。
**验收：** 所有已声明 supported 的通道具有契约测试；schema 改变时测试明确失败。

## Phase 4：候选召回与 Hydration

**时间：2026-08-15～2026-08-21**

### TODO 4.1：关注 UP 投稿直连

- [ ] 修复 `get_up_videos` 的 WBI 签名。
- [ ] `followed_up` 优先调用 UP 投稿接口，不再用名称搜索作为主路径。
- [ ] 名称搜索只保留为降级方案。
- [ ] 对特别关注、普通关注和弱关注设置不同候选先验。
- [ ] 缓存 UP 最近投稿，避免每次推荐重复请求。

**验收：** fixture 中 UP 投稿无串号；同名 UP 不会召回错误账号。

### TODO 4.2：Candidate Hydration

- [ ] 召回仅产生轻量 candidate ID。
- [ ] 合并多路召回后再批量补全，避免重复请求。
- [ ] 补全字段：标题、简介、标签、分区、合集、UP、发布时间、时长、播放/点赞/投币/收藏/评论统计、已有摘要和概念。
- [ ] 保存字段时间戳和数据来源。
- [ ] 缺失字段不使用虚构默认值参与质量评分。

**使用工具：** BilibiliService、批量并发、TTL cache、SQLAlchemy VideoCache。
**验收：** 排序输入的关键字段覆盖率 ≥ 90%；相同 BVID 只 hydration 一次。

### TODO 4.3：召回源分数校准

- [ ] 不直接比较不同通道的原始分数。
- [ ] 以历史曝光/点击/收藏数据做每通道分位数或 Platt/Isotonic 校准。
- [ ] 数据不足时使用显式先验并标记未校准。
- [ ] 保留 source attribution，重复候选合并多个召回证据。

**验收：** 不同召回源的分数进入统一范围；单个通道不会因数值尺度垄断 Top-K。

## Phase 5：Ontology V2 与实体链接 V2

**时间：2026-08-22～2026-09-04**

### TODO 5.1：本体模块化

- [ ] 拆分：
  - `ontology/core.ttl`
  - `ontology/bilibili-taxonomy.ttl`
  - `ontology/domains/ai.ttl`
  - `ontology/domains/game.ttl`
  - `ontology/domains/animation.ttl`
  - `ontology/domains/music.ttl`
  - `ontology/domains/film.ttl`
  - `ontology/domains/knowledge.ttl`
  - `ontology/domains/life.ttl`
- [ ] 使用 `owl:imports` 或显式 loader 清单。
- [ ] 接入 B站 tid/category 映射。
- [ ] 每个概念增加定义、来源、状态和维护版本。
- [ ] 支持 `deprecated` 与 `replacedBy`。
- [ ] 个人概念与公共概念分离，不能污染全局 ontology。

**目标规模：** 首轮 200～400 个高质量概念，而不是追求无审阅的大规模自动扩充。
**验收：** 非 AI 金标覆盖率显著提升；所有模块通过 SHACL。

### TODO 5.2：实体链接级联

- [ ] Stage 1：精确 prefLabel/altLabel，高精度直接命中。
- [ ] Stage 2：分词、BM25、RapidFuzz 生成候选。
- [ ] Stage 3：向量候选，用上下文相似度排序。
- [ ] Stage 4：使用标题、分区、UP、相邻句进行消歧。
- [ ] Stage 5：低置信度拒识。
- [ ] 返回 top candidates、最终选择、置信度和拒识原因。
- [ ] 对“智能、本体、Agent、Java”等歧义词增加专项测试。

**使用工具：** RDFLib、RapidFuzz、中文分词、现有 embedding；LLM 仅作为低频可选消歧器。
**验收：** Precision ≥ 92%、Recall ≥ 85%、F1 ≥ 88%。

### TODO 5.3：SHACL 与图质量

- [ ] 检查 prefLabel、语言唯一性、定义和来源。
- [ ] 检查 self-loop 和 `broader` cycle。
- [ ] 检查 relation domain/range。
- [ ] 检查废弃概念是否有替代目标。
- [ ] 检查孤立概念和不可达概念。
- [ ] 检查过宽别名和重复别名冲突。
- [ ] CI 中强制运行。

**验收：** SHACL 与自定义图检查均为 0 error；warning 有显式白名单和原因。

## Phase 6：概念反馈闭环与推荐评估

**时间：2026-09-05～2026-09-12**

### TODO 6.1：概念级反馈

- [ ] RecommendationEvent 保存 concept IDs 和对应证据。
- [ ] 原始 topic 先实体链接，再进入 affinity。
- [ ] 不同反馈使用不同传播：
  - `favorite/like`：向父概念弱传播。
  - `not_relevant`：当前概念中强负反馈，父概念极弱或不传播。
  - `temporary/too_long/too_old`：不污染主题。
  - `block_topic`：只向下位概念传播。
- [ ] 正负反馈分别设置半衰期。
- [ ] 用户解除屏蔽时保留审计事件。

**验收：** 屏蔽 LangGraph 不会屏蔽整个 Python/科技；屏蔽人工智能会覆盖其下位概念。

### TODO 6.2：离线推荐评估器

- [ ] 编写 `scripts/evaluate_recommendation.py`。
- [ ] 使用行为时间切分：历史构建画像，未来行为作为目标。
- [ ] 输出 Recall@K、NDCG@K、MRR、HitRate、Coverage、Novelty、ILD。
- [ ] 按用户活跃度、画像新鲜度和内容领域分桶。
- [ ] 固定随机种子和候选集合。
- [ ] 报告置信区间，不只报告单个均值。

### TODO 6.3：消融实验

- [ ] Baseline：当前 V1/V2。
- [ ] 去掉时间衰减。
- [ ] 去掉 ontology。
- [ ] 去掉多兴趣簇。
- [ ] 去掉 hydration。
- [ ] 去掉关注动态。
- [ ] 不同权重组合。
- [ ] 将结果保存到 `reports/evaluation/`，不得手工挑选最好样本。

**验收：** NDCG@10、Recall@20、HitRate@10 达到最终目标；否则不宣称推荐更准。

## Phase 7：迁移、监控、前端解释和发布

**时间：2026-09-13～2026-09-18**

### TODO 7.1：Alembic

- [ ] 初始化 Alembic，导入现有 metadata。
- [ ] 为 profile features、chunk concepts、sync runs、加密 Cookie、concept events 创建迁移。
- [ ] 在临时复制的旧 SQLite 数据库上测试升级。
- [ ] 生产迁移前备份；不得自动删除用户数据。
- [ ] 明确哪些迁移不可逆。

### TODO 7.2：可观测性

- [ ] 指标：通道成功率、延迟、429、认证失败、schema error。
- [ ] 指标：实体链接覆盖率、拒识率、歧义率、每视频概念数。
- [ ] 指标：RAG 无结果率、低置信度率、引用数、检索耗时。
- [ ] 指标：召回源贡献、过滤率、排序耗时、多样性、重复曝光率。
- [ ] 所有日志关联 request_id/session_hash/batch_id，禁止直接记录真实 session_id 和 Cookie。

### TODO 7.3：前端解释和隐私控制

- [ ] 展示长期/近期/历史兴趣，不混为一种标签。
- [ ] 展示兴趣证据来源和时间。
- [ ] 允许删除单条画像证据。
- [ ] 允许暂停某个通道参与画像。
- [ ] 展示推荐命中的概念和关系路径。
- [ ] 问答来源可跳转到对应视频时间码。
- [ ] 增加删除账号数据、画像和 Cookie 的明确流程。

### TODO 7.4：灰度发布与回滚

- [ ] 先对测试账号启用 V2。
- [ ] 再对 10% 本地会话启用，观察错误率和延迟。
- [ ] 逐步到 50%、100%。
- [ ] 任一硬门槛失败立即关闭对应 Feature Flag。
- [ ] 不回滚数据库破坏性变化；使用兼容读写和版本字段。

## 5. 测试矩阵

| 层级 | 必须覆盖 |
|---|---|
| Ontology unit | 标签、别名、边界、关系方向、循环、版本、废弃概念 |
| Entity linking | 精确、模糊、歧义、否定、无概念、混合中英文 |
| Temporal | 近期/陈旧/未知时间、单概念、多概念、重复事件、相关事件 |
| RAG retrieval | 原始查询、同义词、父子概念、related 漂移、无结果、过滤 BVID |
| RAG answer | 引用、拒答、冲突证据、多视频综合、时间码 |
| Profile sync | 单页、多页、cursor、429、超时、认证失效、成功失效、失败不失效 |
| Recall | UP 直连、动态、搜索降级、重复候选、多源合并 |
| Ranking | 缺字段、旧配置、新旧算法、负反馈、屏蔽方向、多样性 |
| Security | 加密、错误密钥、密钥轮换、日志脱敏、用户数据删除 |
| Migration | 空库、旧库升级、重复升级、异常恢复 |
| Frontend | 类型检查、lint、build、解释字段缺失时降级 |

## 6. 每阶段通用完成流程

每个 Phase 都必须按下面顺序执行：

1. 先写或更新设计说明和数据 schema。
2. 添加会失败的测试，证明问题可复现。
3. 小步实现，不在同一次补丁中混入无关重构。
4. 运行目标模块测试。
5. 运行完整后端测试。
6. 涉及前端时运行 lint 和 build。
7. 涉及本体时运行 SHACL 和实体链接 benchmark。
8. 涉及推荐时运行离线评估与消融。
9. 更新文档和算法版本。
10. 检查 diff，确认未覆盖用户已有修改、未泄露密钥、未引入临时文件。
11. 只有验收指标通过才将 TODO 标记为完成。

## 7. Definition of Done

整个 Goal 只有满足以下条件才能标记完成：

- [ ] Phase 0～7 的硬性 TODO 全部完成。
- [ ] 实体链接、RAG、推荐三个评估报告存在且可复现。
- [ ] 所有目标指标达到，或明确记录未达到项且 Goal 不标记 complete。
- [ ] 所有新增表由 Alembic 创建。
- [ ] 旧数据库升级测试通过。
- [ ] Cookie 加密和日志脱敏测试通过。
- [ ] 所有 supported B站通道有契约测试和状态报告。
- [ ] 后端完整测试通过。
- [ ] SHACL 和图质量检查通过。
- [ ] 前端 lint 无 error，production build 通过。
- [ ] `git diff --check` 通过。
- [ ] 文档包含架构、配置、迁移、回填、评估、回滚和已知限制。
- [ ] 没有把无法获取的数据描述成已获取。
- [ ] 没有在缺少 A/B 或离线证据时声称线上指标提升。

## 8. 可直接复制到 Goal 模式的完整提示词

```text
请为当前线程创建并持续执行一个 Goal，目标如下：

在 E:\bilibili-calling-main 中完成 Ontology、Grounded RAG、时间感知推荐、多通道 B站用户画像和工程安全性的 V2 升级。不要只给方案，要在项目中逐阶段实现、测试、评估、文档化并完成整体验证。在真正达到验收标准之前不要把 Goal 标记为 complete。

一、当前已知基线

1. 项目已经有 bili-ontology-1.0.0，约 42 个概念、273 条 RDF 三元组。
2. 已有 SKOS/SHACL、本体实体链接、查询扩展、Chroma RRF、多兴趣画像、时间衰减、本体推荐排序、MMR、多通道画像和推荐事件。
3. 当前后端测试约 26 项通过，前端 lint 0 error，Next.js build 通过。
4. 主要文件包括：
   - ontology/bilibili.ttl
   - ontology/shapes.ttl
   - app/services/ontology/service.py
   - app/services/ontology/repository.py
   - app/services/rag.py
   - app/services/recommendation/temporal_interest.py
   - app/services/recommendation/profile_schema.py
   - app/services/recommendation/ranking.py
   - app/services/recommendation/event_service.py
   - app/services/recommendation/candidate_recalls.py
   - app/services/profile/multi_source_profile_builder.py
   - app/services/profile/signals.py
   - app/services/bilibili.py
   - app/models.py
   - app/database.py
   - frontend/components/ProfileVisualization.tsx
   - docs/ONTOLOGY_RECOMMENDATION_TODO_GOAL.md

二、必须解决的核心问题

1. 修正时间衰减后再除以最大值导致旧兴趣重新变成 1.0 的问题。
2. 将概念兴趣拆分为绝对强度、相对占比、证据量和画像新鲜度置信度。
3. 处理同一 BVID 在动态、历史、稍后看、收藏等通道中的相关行为，避免简单重复相加。
4. 改进多兴趣簇，避免所有 AI/编程概念都爬到“科技”顶层。
5. 将 RAG 改为带相关度阈值的本体扩展检索，避免每个扩展词强制召回低相关结果。
6. 在 RRF 后增加可关闭、可降级的小规模 reranker。
7. 建立 chunk/时间码级概念标注、精确引用和 grounded/ungrounded 返回状态。
8. 对无证据问题正确拒答，不把通用知识伪装成用户收藏知识库内容。
9. 新增画像同步批次、分页/游标、快照/事件语义和成功同步后的失效逻辑。
10. 通道失败时绝不能误失效旧画像信号。
11. 为所有 supported B站通道增加脱敏响应契约测试和 working/degraded 状态。
12. 修复 get_up_videos 的 WBI 直连召回；名称搜索只作为降级方案。
13. 增加候选 Hydration，补全简介、标签、分区、统计、摘要和本体概念后再排序。
14. 扩展并模块化本体，首轮目标 200～400 个经过审阅的高质量概念，覆盖 AI、游戏、动画、音乐、影视、知识和生活。
15. 实体链接升级为精确标签、模糊候选、向量候选、上下文消歧和低置信度拒识的级联流程。
16. 扩展 SHACL：关系范围、循环、自环、废弃替换、定义来源和别名冲突。
17. 将推荐反馈归一到 concept IDs，并按事件类型执行有方向、可衰减的传播。
18. 建立推荐时间切分评估器和消融实验，不能凭主观感觉宣称推荐提升。
19. 加密数据库中的 SESSDATA/bili_jct，支持密钥轮换、日志脱敏和用户数据删除。
20. 使用 Alembic 管理新增数据库结构，并验证旧 SQLite 数据库升级。
21. 增加接口、实体链接、RAG、推荐和同步的可观测性。
22. 前端展示兴趣证据、长期/近期区别、本体路径、问答时间码来源和通道隐私控制。

三、量化验收标准

1. 实体链接金标集不少于 300 条；Precision >= 92%，Recall >= 85%，F1 >= 88%，歧义正确拒识率 >= 90%。
2. RAG 金标问题 120～200 条；Recall@5 >= 85%，MRR@10 >= 0.75，引用正确率 >= 95%，groundedness >= 90%，无答案正确拒答率 >= 90%，事实性幻觉率 <= 5%。
3. 推荐使用严格时间切分；相比当前基线 NDCG@10 相对提升 >= 10%，Recall@20 相对提升 >= 8%，HitRate@10 相对提升 >= 8%，多样性不得下降，主题覆盖率相对提升 >= 10%。
4. 同一概念和强度下，730 天前收藏的有效贡献 <= 1 天前观看历史贡献的 25%。
5. 单一旧收藏不得产生绝对强度 1.0。
6. 所有支持通道有分页或游标策略、采样上限、超时、重试、状态和契约测试。
7. 快照型信号成功同步后可失效，失败同步不失效；事件型信号不受快照失效影响。
8. 同一内容重复同步不改变画像，跨通道重复贡献率 < 1%。
9. 数据库中不存在明文 Cookie，日志和 API 响应不泄露 Cookie。
10. 排序 200 个已 Hydrate 候选的本地计算 p95 <= 300ms；1 万 chunk 下本地检索 p95 <= 800ms，不含远程 LLM 时间。
11. SHACL、后端测试、迁移测试、API 契约测试、前端 lint 和 production build 全部通过。

四、阶段和顺序

Phase 0：固定基线，建立 entity_linking.jsonl、rag_qa.jsonl、时间切分推荐数据格式；加入 Feature Flags；完成 Cookie 加密方案和测试护栏。

Phase 1：时间兴趣绝对校准、跨通道相关行为去重、多兴趣簇改进。先写失败测试，再改实现。

Phase 2：Grounded RAG，包括分数阈值、关系类型权重、RRF、reranker、chunk/时间码概念、引用验证和无答案拒答。

Phase 3：画像同步 V2，包括 ProfileSyncRun、分页/游标、snapshot/event_stream 区分、幂等同步、成功失效、失败保护和契约测试。

Phase 4：关注 UP 投稿直连、候选 Hydration、缓存、多源合并和召回源分数校准。

Phase 5：Ontology V2，包括 core、B站 taxonomy、AI/游戏/动画/音乐/影视/知识/生活领域模块，实体链接级联和 SHACL V2。

Phase 6：概念反馈闭环、推荐离线评估、置信区间和消融实验。没有达到指标时继续分析和迭代，不得把 Goal 标记完成。

Phase 7：Alembic、监控、前端解释与隐私控制、灰度开关、回滚验证、最终文档和完整验收。

五、工作规则

1. 先完整阅读 docs/ONTOLOGY_RECOMMENDATION_TODO_GOAL.md，并以其中 TODO 和 Definition of Done 为执行清单。
2. 开始时检查当前 Git 状态。工作区可能已有用户修改，必须保留，不得 reset、checkout 或覆盖无关改动。
3. 文件修改使用 apply_patch；格式化工具的机械修改除外。
4. 每个阶段先写测试复现问题，再实现；每次修改后运行目标测试，阶段结束运行完整测试。
5. 涉及外部技术、算法、B站接口或依赖版本且可能变化时，查阅官方文档、论文原文或维护中的一手来源；不要依赖过期聚合文档。
6. B站接口是非官方公开接口，必须失败隔离、限速、记录 capability 状态，不得声称可以获取不存在的全量点赞、投币或完播历史。
7. 不使用真实 Cookie 作为测试 fixture，不在输出中显示密钥或私人数据。
8. 所有破坏性数据库操作必须先在临时副本验证，并明确回滚方式。
9. LLM 只能是可关闭的辅助模块；确定性检索、排序和降级链路必须独立可运行。
10. 不把论文模型名称当作已经复现的证据。若只是借鉴时间注意力、多兴趣或候选混合机制，要在文档中明确是工程化近似。
11. 不因为时间或工作量大而停止。只在需要新的用户授权、缺少真实账号验证或同一外部阻塞连续出现时报告阻塞。
12. 真实 B站登录态验证如果不可用，使用脱敏 fixture 完成全部可自动验证内容，并单独列出需要用户手工执行的 live smoke test，不能伪造成功结果。
13. 每阶段更新计划状态和文档；只有全部 Definition of Done 满足时才能完成 Goal。

六、必须产出的文件或等价物

1. 详细设计与迁移文档。
2. evaluation 数据 schema、校验器和金标样例。
3. entity linking、RAG 和 recommendation 三类评估脚本。
4. 每阶段 benchmark JSON/Markdown 报告。
5. Feature Flag 和回滚说明。
6. Alembic migrations。
7. B站通道契约 fixture 和测试。
8. Cookie 加密、轮换、脱敏和删除流程。
9. 前端解释和隐私控制。
10. 最终验证报告，包含测试命令、结果、指标、未验证的 live 项和已知限制。

七、最终验证命令至少包括

python -m compileall -q app scripts
python -m pytest -q
python scripts/backfill_ontology.py --batch-size 100（在临时或明确指定数据库验证）
本体 SHACL 和图质量检查
实体链接 benchmark
RAG retrieval/answer benchmark
推荐离线时间切分和消融 benchmark
Alembic 旧库升级验证
cd frontend && npm run lint
cd frontend && npm run build
git diff --check

八、完成报告格式

最终报告必须先给出是否达到全部验收门槛，然后列出：

1. 已实现内容。
2. 关键架构变化。
3. 实体链接指标。
4. RAG 指标。
5. 推荐指标和消融结果。
6. B站通道覆盖、降级和未支持项。
7. 安全与迁移结果。
8. 后端、前端、SHACL、契约测试和构建结果。
9. 未完成或只能 live 验证的事项。
10. 回填、迁移和启用 Feature Flag 的操作步骤。

当且仅当所有硬性 Definition of Done 达成、没有未说明的必需工作、没有伪造的线上或 live 验证结果时，才将 Goal 标记为 complete。
```
