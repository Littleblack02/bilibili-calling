# V2 数据库迁移与回滚

## 迁移内容

`0001_v2` 是项目采用 Alembic 的首个迁移。它对空库创建完整 metadata；对旧库只做新增操作，包括 `profile_features`、`last_seen_sync_id`、ontology 图、chunk 概念、画像同步审计、推荐批次和带概念证据的推荐事件。

Cookie 列仍是兼容的 TEXT 类型，值由 `EncryptedCookieText` 使用 AES-GCM 透明加解密。先运行 Cookie dry-run，再迁移值，不在结构迁移中接触密钥：

```bash
python scripts/migrate_session_cookies.py /path/to/copy.db
python scripts/migrate_session_cookies.py /path/to/copy.db --apply
```

## 生产步骤

1. 停止写入并备份 SQLite 文件，同时记录 SHA-256。
2. 在备份副本运行 `python scripts/verify_migrations.py` 和 Cookie dry-run。
3. 配置 Cookie 密钥环，先执行 Cookie `--apply`，确认无明文和旧 key。
4. 执行 `alembic upgrade head`。
5. 启动兼容读路径做 smoke test，再按灰度文档启用 V2 flags。
6. 保留迁移前备份，直到观察期结束。

## 回滚

该迁移故意不可逆。删除新表或新列会丢失画像证据、同步审计和反馈，因此 `alembic downgrade` 会明确失败。应用回滚应关闭 V2 Feature Flags 并继续兼容读写；若必须回退数据库，只能停写后恢复迁移前备份。迁移脚本不会自动删除用户数据。
