# Authentication

QoderGate has two authentication layers: one for the management console and one for external API clients.

## Management Console Token

The WebUI uses the gateway token you enter on login. Frontend requests send it as:

```http
X-Gateway-Token: <gateway-token>
```

This protects routes such as:

- `/ui/status`
- `/ui/accounts`
- `/ui/config`
- `/ui/logs`

### First Startup

If `QODER_ADMIN_PASSWORD` is left empty when the database is first created, the gateway generates a strong random password and prints it to stdout once. Save it immediately - it will not be shown again. To regenerate, set `QODER_ADMIN_PASSWORD` and delete the database file, then restart. The legacy default password `admin` is no longer used.

### Brute-force Protection

All `/ui/*` management routes share the same brute-force guard (applied inside the shared token check, including `/ui/verify`): after a failed attempt there is a 5-second cooldown, and 5 failures within a 15-minute window lock the source out for 15 minutes (`429`). A successful authentication resets the counters.

## External API Keys

The OpenAI-compatible API can optionally require Bearer keys.

When enabled, clients must send:

```http
Authorization: Bearer <allowed-api-key>
```

## Which Token Should I Use?

| Use case | Header | Scope |
| --- | --- | --- |
| WebUI management | `X-Gateway-Token` | `/ui/*` routes |
| OpenAI-compatible calls | `Authorization` | `/v1/chat/completions` |

## Recommended Setup

- Keep the management token private.
- Enable API key auth before exposing the gateway to other machines.
- Rotate API keys if they are shared in logs or scripts.
