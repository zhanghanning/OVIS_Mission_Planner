# 前端公网联调说明

当前推荐把 `mission_planner` 通过 Cloudflare Tunnel 暴露给前端同学。

## 推荐结论

- 临时联调：使用 Cloudflare Quick Tunnel
- 长期联调：使用 Cloudflare Managed Tunnel

公网访问对前端同学来说最重要的是一个稳定可访问的 HTTPS URL，而不一定是“真实公网 IP”。

## 1. 临时联调

启动：

```bash
cd /home/techno/mission_planner/deploy/docker
docker-compose --env-file /home/techno/mission_planner/deploy/docker/.env up -d planner-api-lite public-tunnel-quick
```

查看公网 URL：

```bash
docker logs -f planner-public-tunnel-quick
```

拿到日志里的 `https://xxxxx.trycloudflare.com` 后：

- 页面地址：`https://xxxxx.trycloudflare.com/api/planner/interactive/console`
- API 基地址：`https://xxxxx.trycloudflare.com`

## 2. 长期联调

在 Cloudflare 后台创建 Managed Tunnel，然后把 token 写进：

- `/home/techno/mission_planner/deploy/docker/.env`

```env
CLOUDFLARE_TUNNEL_TOKEN=你的token
```

启动：

```bash
cd /home/techno/mission_planner/deploy/docker
docker-compose --env-file /home/techno/mission_planner/deploy/docker/.env up -d planner-api-lite public-tunnel-managed
```

## 3. 前端应该调用哪些接口

详见：

- `docs/frontend_api_contract.md`

最常用接口：

- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
- `GET /api/planner/interactive/plans/{plan_id}`
