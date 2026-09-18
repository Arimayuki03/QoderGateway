# 鉴权机制

QoderGate 有两层鉴权：管理控制台鉴权，以及外部 API 调用鉴权。它们服务于不同场景，不应该混用。

## 管理控制台 Token

你在登录页输入的密钥会作为管理密钥使用。前端请求管理接口时会发送：

```http
X-Gateway-Token: <gateway-token>
```

它保护这些接口：

- `/ui/status`
- `/ui/accounts`
- `/ui/config`
- `/ui/logs`

### 首次启动

首次建库时若未设置 `QODER_ADMIN_PASSWORD`，网关会自动生成随机口令并打印到控制台（仅显示这一次，请妥善保存）。如需重新生成，可设置 `QODER_ADMIN_PASSWORD` 后删除数据库文件再重启。默认口令 `admin` 已不再使用。

## 外部 API Key

OpenAI 兼容接口可以单独开启 Bearer Key 校验。

开启后，客户端必须传入：

```http
Authorization: Bearer <allowed-api-key>
```

## 两种密钥的区别

| 使用场景 | Header | 作用范围 |
| --- | --- | --- |
| 管理后台 | `X-Gateway-Token` | `/ui/*` 管理接口 |
| OpenAI 兼容调用 | `Authorization` | `/v1/chat/completions` |

## 推荐实践

- 不要把管理 Token 写入脚本或分享给外部客户端。
- 如果网关监听非本机地址，建议开启 API Key 鉴权。
- 如果 API Key 出现在日志、截图或脚本中，及时删除并重新生成。
