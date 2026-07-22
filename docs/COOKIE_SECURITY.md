# Bilibili session credential security

`UserSession.sessdata` and `UserSession.bili_jct` use an AES-256-GCM envelope
while keeping the existing SQL `TEXT` columns. New authenticated writes fail
closed when no valid key is configured; legacy plaintext remains readable only
so it can be migrated.

Generate a 32-byte URL-safe Base64 key outside source control, then configure:

```dotenv
BILIBILI_COOKIE_ENCRYPTION_KEYS=v2=<base64-key>,v1=<previous-base64-key>
BILIBILI_COOKIE_ACTIVE_KEY_ID=v2
```

Key IDs are stored in `enc:v1:<key-id>:<ciphertext>` envelopes. To rotate keys:

1. Add the new key while retaining old decrypt keys and change the active ID.
2. Back up the database and run `python scripts/migrate_session_cookies.py`.
3. Review the secret-free dry-run counts.
4. Run `python scripts/migrate_session_cookies.py --apply`.
5. Run the dry-run again; plaintext and stale-key counts must both be zero.
6. Remove old keys only after all running instances and backups have passed the
   retention window.

Logout revokes the durable session and erases both encrypted credential fields.
The migration command never prints plaintext or ciphertext. Application log
sinks redact Cookie/CSRF assignments and encrypted envelopes before output.

Database backups contain credential ciphertext and must still be access
controlled. If the active key is lost, encrypted sessions cannot be recovered;
users must log in again.
