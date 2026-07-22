# 画像与账户隐私控制

## 能力

- `GET /privacy/{session_id}/controls`：查看通道证据数量和启停状态。
- `DELETE /privacy/{session_id}/evidence/{signal_id}?confirmed=true`：删除一条属于该会话的画像证据，并立即重算画像。
- `PUT /privacy/{session_id}/channels/{channel}`：以 `{ "enabled": false }` 暂停某通道参与画像；原始证据保留以便恢复，但不会进入新画像。
- `POST /privacy/{session_id}/delete`：删除 Cookie、画像或全部会话数据。

删除请求必须携带与范围完全对应的确认短语：`DELETE COOKIES`、`DELETE PROFILE` 或 `DELETE ALL`。Cookie 删除会清空持久化凭据和进程缓存并使会话失效；全量删除会遍历所有带 `session_id` 的会话表，并额外删除收藏夹关联。共享的视频缓存与公共 ontology 不会因单个用户删除而被破坏。

API 删除摘要只返回不可逆的短 session hash 和逐表计数，不回显 Cookie 或原始 session ID。数据库删除无法撤销；生产操作前应按迁移文档保留备份，但不能用备份规避用户的删除请求。
