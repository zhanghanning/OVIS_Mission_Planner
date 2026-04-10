# 前端公网联调说明

当前项目已经内置两种公网暴露方式：

- 临时或免公网 IP 联调：Cloudflare Tunnel
- 需要真实公网 IP 和固定端口：FRP TCP 转发

如果前端只是浏览器联调，Cloudflare Tunnel 依然是最省事的方案。
如果你明确需要“公网 IP:端口”这种地址，就需要一台已经部署 `frps` 的公网服务器。

## 1. 结论先说

- Cloudflare Tunnel 可以直接给你一个公网 HTTPS URL，但不是公网 IP。
- FRP 可以给你一个真实公网 IP 和端口，但这个公网 IP 来自你的 `frps` 服务器，不是当前这台内网开发机自动生成的。
- 当前仓库已经补好了 `frpc` 客户端的 compose 服务、客户端配置模板和服务端示例配置。

## 2. FRP 需要你准备什么

至少需要下面两项：

- 一台有公网 IP 的 Linux 服务器，用来运行 `frps`
- 该服务器上放行两个端口

端口含义：

- `7000`：`frps` 控制连接端口
- `18081`：对外暴露给前端访问 mission_planner 的 HTTP 端口

当前默认约定：

- `frps` 公网 IP：你提供
- `frps` bind 端口：`7000`
- 转发后的公网访问地址：`http://你的公网IP:18081`

## 3. 服务端如何部署 frps

仓库里已经提供了一个最小示例：

- `/home/techno/mission_planner/deploy/docker/frps.toml.example`

示例内容对应官方最基础的 token 认证模式，只需要在公网服务器上保存为例如：

- `/etc/frp/frps.toml`

然后在公网服务器上运行：

```bash
./frps -c /etc/frp/frps.toml
```

或你也可以自己用 systemd / Docker 部署，只要配置等价即可。

## 4. 当前项目里已经加好的 FRP 客户端支持

已新增内容：

- `deploy/docker/Dockerfile.frpc`
- `deploy/docker/start_frpc.sh`
- `deploy/docker/frpc.toml`
- `docker-compose.yml` 中的 `public-frp-tcp` 服务
- `.env` 中的 FRP 相关配置项

默认转发关系是：

- 本地后端：`planner-api-lite:8081`
- 公网暴露：`公网IP:18081`

## 5. 你现在需要填写哪些配置

编辑：

- `/home/techno/mission_planner/deploy/docker/.env`

把下面这些值填上：

```env
FRP_SERVER_ADDR=你的frps公网IP
FRP_SERVER_PORT=7000
FRP_AUTH_TOKEN=你的frp认证token
FRP_REMOTE_PORT=18081
FRP_PROXY_NAME=mission-planner-api
```

如果你希望后端返回给前端的链接也是公网地址，还要把：

```env
PUBLIC_BASE_URL=http://你的frps公网IP:18081
```

一起改掉。

如果你的前端页面本身部署在其他域名或地址上，还需要同步更新：

```env
BACKEND_CORS_ALLOW_ORIGINS=http://前端页面地址
```

如果前端不是固定一个地址，就按你的实际来源补 `BACKEND_CORS_ALLOW_ORIGIN_REGEX`。

## 6. 如何启动 FRP 公网转发

先启动后端和 FRP 客户端：

```bash
cd /home/techno/mission_planner/deploy/docker
docker-compose --env-file /home/techno/mission_planner/deploy/docker/.env up -d planner-api-lite public-frp-tcp
```

查看 FRP 客户端日志：

```bash
docker logs -f planner-public-frp-tcp
```

如果连通成功，前端就可以访问：

- API 基地址：`http://你的公网IP:18081`
- 控制台页面：`http://你的公网IP:18081/api/planner/interactive/console`

## 7. 为什么我现在不能直接“给你一个公网 IP”

因为 FRP 模式下，公网 IP 不属于当前这台开发机，而属于你要连接的那台 `frps` 公网服务器。

也就是说：

- 如果你已经有公网服务器，把它的 IP 发我，我就能继续帮你把 `.env` 直接填完
- 如果你还没有公网服务器，我现在只能先把 FRP 接入能力补好，但不能凭空生成一个真实公网 IP

## 8. 如果你没有公网服务器

那当前项目里已经能直接用的替代方案是 Cloudflare Tunnel。

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

## 9. 前端最常用接口

详见：

- `docs/frontend_api_contract.md`

常用接口：

- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
- `GET /api/planner/interactive/plans/{plan_id}`
