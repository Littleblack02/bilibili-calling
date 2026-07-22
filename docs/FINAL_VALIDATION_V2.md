# Ontology、Grounded RAG、推荐与画像 V2 最终验证报告

> 验证日期：2026-07-21（Asia/Shanghai）
> 验证范围：本地代码、脱敏契约 fixture、锁定的合成/编辑评估集、临时 SQLite 数据库
> 结论：所有可自动验证的硬门槛均已通过；真实 B站登录态 smoke test 和线上灰度观测未伪造，需由部署者在启用前后执行。

## 1. 总结

V2 已完成 Ontology、实体链接、时间感知多兴趣画像、Grounded RAG、B站多通道同步、UP 主直连召回、候选 Hydration、概念反馈、安全、迁移、可观测性、隐私控制、前端解释、灰度与发布门禁的实现。

最终自动验证结果：

| 门槛 | 目标 | 当前结果 | 状态 |
| --- | ---: | ---: | --- |
| 实体链接样本 | ≥ 300 | 471（test 111） | PASS |
| 实体链接 Precision | ≥ 92% | 97.9592% | PASS |
| 实体链接 Recall | ≥ 85% | 95.0495% | PASS |
| 实体链接 F1 | ≥ 88% | 96.4824% | PASS |
| 歧义正确拒识率 | ≥ 90% | 100%（10 个 test 拒识样本） | PASS |
| RAG 问题数 | 120～200 | 150 | PASS |
| Retrieval Recall@5 | ≥ 85% | 98.0159% | PASS |
| Retrieval MRR@10 | ≥ 0.75 | 0.992063 | PASS |
| 引用正确率 | ≥ 95% | 98.2143% | PASS |
| Groundedness | ≥ 90% | 100% | PASS |
| 无答案拒答率 | ≥ 90% | 100% | PASS |
| 事实性幻觉率 | ≤ 5% | 0% | PASS |
| 1 万 chunk 本地检索 p95 | ≤ 800ms | 86.2669ms | PASS |
| 推荐 NDCG@10 相对提升 | ≥ 10% | +1335.5696% | PASS |
| 推荐 Recall@20 相对提升 | ≥ 8% | +797.4348% | PASS |
| 推荐 HitRate@10 相对提升 | ≥ 8% | +223.0767% | PASS |
| 主题覆盖率相对提升 | ≥ 10% | +754.2409% | PASS |
| 列表内部多样性 | 不低于基线 | 0.805461 vs 0.033562 | PASS |
| 200 候选本地排序 p95 | ≤ 300ms | 39.672ms | PASS |
| Ontology / SHACL | 0 error | 234 concepts、2,199 triples、conforms | PASS |
| 后端测试 | 全通过 | 86 passed | PASS |
| 前端 lint / build | 0 error / build 成功 | 0 error、16 warnings / PASS | PASS |
| 迁移、回填、发布门禁 | 全通过 | 7/7 gates green | PASS |

上述 RAG 与推荐结果来自确定性的合成/编辑数据集，只证明本地工程回归和门禁，不代表真实线上质量或因果提升。

## 2. 关键架构变化

### Ontology 与实体链接

- 公共本体按 `core`、B站 taxonomy、AI、游戏、动画、音乐、影视、知识、生活拆为 9 个模块；个人概念不进入公共 manifest。
- 运行时版本从 RDF 的唯一 `owl:versionInfo` 读取；缺失或冲突时拒绝加载。
- SHACL V2 检查定义、来源、状态、版本、关系范围、自环、`broader` 环、废弃替代、标签冲突和个人概念隔离。
- 实体链接采用精确标签、RapidFuzz/词法候选、本地字符向量、上下文消歧和低置信度拒识级联。
- 推荐排序对画像本体扩展建立批次级反向索引，候选优先复用 Hydration 阶段的 concept IDs；无预链接概念时只回退解析一次。

### 时间画像与概念反馈

- 画像同时保存绝对兴趣、相对份额、证据量和新鲜度置信度，单一旧兴趣不再被最大值归一为 `1.0`。
- 同 BVID 跨通道贡献按行为语义组去重，动态曝光不直接形成正兴趣。
- 多兴趣停在可解释的中层簇，并使用温度化 attention 融合多个命中簇。
- 推荐事件保存 concept IDs 和证据；正反馈向父概念弱传播，主题屏蔽只向后代传播，临时/时长/过旧反馈不污染主题。

### Grounded RAG

- 检索保留原始查询、本体扩展来源、关系路径、距离、融合分和 rerank 分，并按来源/关系设置阈值。
- reranker 可关闭、超时或失败时回退确定性融合排序。
- chunk 独立标注概念，并保存 `bvid + chunk_index + start_time/end_time`。
- 回答契约包含 `grounded`、`answerability`、`retrieval_confidence`、citations 和 ontology matches；证据不足时明确拒答。

### B站画像和候选管线

- 19 个 declared supported 通道有脱敏契约 fixture、统一 adapter、分页/游标边界、超时/重试和 capability 状态。
- snapshot 仅在成功且完整耗尽时失效旧信号；失败、限流、认证问题、schema 变化或达到安全上限均不得误失效。
- history、live history、dynamic feed 是 event stream，不参与 snapshot 失效。
- `followed_up` 以 MID + WBI 投稿接口为主路径，名称搜索仅降级；多路候选按 BVID 合并后只 Hydrate 一次。
- Hydration 补全内容、作者、时间、时长、统计、摘要和概念，记录字段来源和获取时间；不同召回源分数先校准再融合。
- 明确不可用：全账号点赞历史、投币历史、完整完播历史；系统不构造这些数据。

### 安全、隐私与工程

- `SESSDATA`、`bili_jct` 使用版本化 AES-GCM 透明加密，支持密钥环、轮换和明文迁移；日志过滤 Cookie、session ID 和 UUID。
- 隐私 API 支持删除单条证据、暂停通道参与画像、删除 Cookie、删除画像或删除账号范围数据，破坏性操作要求精确确认短语。
- Alembic `0001_v2` 在空库和旧库上执行非破坏性升级；重复 upgrade 保持幂等并保留旧数据。
- 可观测性覆盖接口、B站通道、实体链接、RAG 和推荐，并使用 request ID、短 session hash 和 batch ID 关联。
- 灰度使用稳定 SHA-256 分桶、测试会话 hash allowlist 和 0/10/50/100 百分比；任一报告失败时发布门禁 fail closed。

## 3. 评估证据

### 实体链接

锁定集共 471 条，test split 111 条：TP 96、FP 2、FN 5，Precision 0.979592、Recall 0.950495、F1 0.964824、拒识准确率 1.0。剩余错误集中在英文拼写错误，如 `Pythn`、`Machin Learnig`、`Reinforcment Learning`、`Minecraf`、`Eletronic Music`，是后续词法鲁棒性优化的明确样本。

报告：[entity-linking.json](../reports/evaluation/entity-linking.json)

### RAG

评估包含 150 问（126 可回答、24 不可回答）、126 个 gold chunks，并扩充到 10,000 个 benchmark chunks。问题覆盖 direct、synonym、cross-video 和 negation。Recall@5 0.980159、MRR@10 0.992063、引用正确率 0.982143、groundedness 1.0、拒答率 1.0、幻觉率 0，p95 86.2669ms。

该评估使用本地词法/抽取路径，不覆盖远程生成模型或生产 Chroma 网络/磁盘行为。报告：[rag.json](../reports/evaluation/rag.json) 与 [RAG_EVALUATION_V2.md](RAG_EVALUATION_V2.md)。

### 推荐与消融

严格时间切分使用 84 个 session、1,008 个截止日前候选、1,328 个事件，cutoff 为 `2026-06-01T00:00:00Z`；未来行为不进入画像。固定 seed 为 `20260721`，每个指标使用 500 次 bootstrap 置信区间。

Full V2：Recall@20 0.694444、NDCG@10 0.570682、MRR@10 0.776786、HitRate@10 1.0、ILD 0.805461、topic coverage 1.0。Baseline：Recall@20 0.077381、NDCG@10 0.039753、HitRate@10 0.309524、ILD 0.033562、topic coverage 0.117063。

消融结果需要保留两个重要事实：

- `no_dynamic` 在此合成集上的 Recall@20 0.978175、NDCG@10 0.807174，高于 Full V2；因此动态召回必须继续受 flag 和在线反馈约束，不能仅凭本报告默认宣称它提高相关性。
- `weights_diversity` 达到 NDCG@10 0.621647、ILD 0.917616，高于当前 Full V2；它是后续真实数据调参候选，但不能用同一锁定 test 集反复调参后再当作无偏结论。

报告：[recommendation.json](../reports/evaluation/recommendation.json) 与 [RECOMMENDATION_EVALUATION_V2.md](RECOMMENDATION_EVALUATION_V2.md)。

### 性能

生产 `score_candidates + diversify` 对 200 个已 Hydrate 候选执行 40 轮，平均 28.994325ms、p95 39.672ms、最大 114.979ms。范围仅包括本地排序，不包括 B站网络 Hydration 和远程 LLM。

报告：[local-performance.json](../reports/evaluation/local-performance.json)

## 4. B站通道覆盖与降级

支持并具备契约 fixture 的 19 个通道：favorites、bangumi、cinema、history、watchlater、followings、special_followings、whisper_followings、subscribed_tags、favorite_collections、favorite_topics、favorite_articles、favorite_courses、favorite_notes、courses、fan_medals、manga、live_history、dynamic_feed。

契约覆盖正常、空数据、缺字段、非零 code、429、超时、认证失效和非 JSON/HTML schema 变化。B站接口并非官方稳定 SDK，生产仍可能发生响应结构变化；此时 capability 必须变为 `degraded`、`auth_required`、`unavailable` 或 `schema_changed`，旧画像保留。

详见 [PROFILE_SYNC_V2.md](PROFILE_SYNC_V2.md)。

## 5. 迁移、回填与回滚

迁移验证在临时旧 SQLite 副本和空库运行：旧库升级、空库升级、重复升级、seed 数据保留全部通过，revision 为 `0001_v2`。回填在一次性临时库中处理 3 个 fixture 视频，生成 13 条视频概念关系和 13 个规范概念；第二次执行数量一致，版本为 `bili-ontology-2.0.0`。

生产操作：

1. 停止写入并备份数据库，记录备份 SHA-256。
2. 在备份副本运行 `python scripts/verify_migrations.py`。
3. 配置 Cookie 密钥环；对副本运行 Cookie dry-run 和 `--apply`。
4. 执行 `alembic upgrade head`。
5. 回填建议先对副本执行：

   ```powershell
   python scripts/backfill_ontology.py --batch-size 100 --database-url sqlite+aiosqlite:///E:/path/to/database-copy.db --output reports/evaluation/manual-backfill.json
   ```

6. 运行七项门禁，再按照灰度顺序启用。

迁移故意不提供破坏性 downgrade。应用级回滚是关闭相关 Feature Flag 或将 `V2_ROLLOUT_PERCENTAGE=0`；数据库级回滚只能停写后恢复迁移前备份。详见 [MIGRATION_V2.md](MIGRATION_V2.md)、[COOKIE_SECURITY.md](COOKIE_SECURITY.md) 和 [ROLLOUT_V2.md](ROLLOUT_V2.md)。

## 6. 灰度启用

`.env.example` 默认将 rollout 设为 0。启用顺序：

1. 配置所需的 `*_V2_ENABLED=true`，保持 `V2_ROLLOUT_PERCENTAGE=0`。
2. 将测试 session 的 salted 16 字符 hash 放入 `V2_TEST_SESSION_HASHES`，不能填写原始 session ID。
3. 测试账号完成一个同步、问答和推荐周期后依次使用 10%、50%、100%。
4. 每一步检查通道失败率、429、认证失败、schema error、RAG 无结果率、引用、推荐 p95 和重复曝光。
5. 任一硬门槛失败，将 rollout 调回 0 或关闭对应 flag。

## 7. 完整验证命令与结果

```powershell
python -m compileall -q app scripts
python -m pytest -q
python scripts/validate_evaluation_data.py
python scripts/check_ontology_quality.py
python scripts/evaluate_entity_linking.py --split test
python scripts/evaluate_rag.py
python scripts/evaluate_recommendation.py
python scripts/verify_migrations.py
python scripts/verify_backfill.py
python scripts/benchmark_local_performance.py --iterations 40 --candidates 200
python scripts/check_release_gates.py
cd frontend
npm run lint
npm run build
cd ..
git diff --check
```

已完成结果：后端 86 passed；SHACL/图质量通过；三类评估通过；迁移、临时回填和性能通过；发布门禁 7/7；前端 lint 0 error、16 warnings；production build 成功；`git diff --check` 通过。

## 8. 未进行的 live 验证与已知限制

以下内容需要真实账号、外部 API 或生产流量，本次没有对应授权或环境，因此没有声称成功：

- 真实 B站 Cookie 下 19 通道的 live 响应、分页耗时、429 行为和 schema 兼容性。
- WBI UP 投稿接口在真实 MID、同名 UP 和风控环境中的端到端 smoke test。
- 远程 embedding、Chroma 生产数据、reranker 和生成 LLM 的实际质量/延迟。
- 10%/50%/100% 真实流量灰度、线上点击/收藏提升和因果 A/B 结论。
- 生产数据库备份、迁移、Cookie 轮换和回填；文档与临时副本已验证，但不得直接代替生产变更审批。

部署者 live smoke checklist：登录后检查 Cookie 数据库值非明文；逐通道运行同步并检查 `ProfileSyncRun`；故意模拟一个失败通道确认不失效旧信号；执行一个有证据和一个无证据问题；执行 balanced/following/explore 推荐并检查 concept path、source、profile version；最后检查 metrics 和日志中没有原始 session/Cookie。

非阻断工程债务：后端当前有 18 条 Pydantic v2 弃用警告；前端有 16 条 lint warning（未使用变量、Hook dependency 和 `<img>` 优化等）。它们没有导致测试、类型检查或构建失败，但建议单独清理。

## 9. 发布判定

当前版本满足本 Goal 的所有可自动验证硬门槛，可进入“测试账号 → 10% → 50% → 100%”的受控灰度流程。它尚未证明真实线上质量提升；只有完成 live smoke、观察指标并进行在线实验后，才能对线上推荐或问答提升作因果声明。
