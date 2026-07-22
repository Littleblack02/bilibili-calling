# V2 可观测性

`GET /observability/metrics` 返回有界的进程内计数器、延迟均值和 p95。标签层会拒绝 `session_id`、Cookie、SESSDATA 和 CSRF；每个 HTTP 请求生成或校验 `X-Request-ID`，响应回传该 ID，并在上下文中关联不可逆 `session_hash` 和推荐 `batch_id`。

已覆盖的核心指标：

- API：请求数、状态码、路由和耗时。
- 画像：通道 success/degraded、429、认证失败、schema error、同步次数和延迟。
- 实体链接：请求、链接/拒识原因、歧义次数、每次选择数、每视频概念数。
- RAG：结果/无结果、低置信度、查询证据覆盖不足、引用错误、引用数和检索耗时。
- 推荐：召回源候选数、过滤率、重复曝光率、排序/总耗时、列表主题多样性和最终状态。

当前 registry 是单进程、内存有界实现，适合本地应用和 smoke test；多 worker 或长期生产部署应把同名指标导出至 Prometheus/OpenTelemetry。日志过滤器会清除 Cookie envelope、凭据赋值、`session_id` 和 UUID 会话标识。
