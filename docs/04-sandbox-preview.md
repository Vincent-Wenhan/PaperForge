# PaperForge - Sandbox & Preview Design

生成的 Next.js app 必须能实际跑起来,用户在前端 iframe 里看到 live preview。这是整个产品最关键的 wow moment。

## 1. Docker 容器策略

**每个生成的 app = 一个独立 Docker 容器**

```python
# paperforge/sandbox/docker_runner.py

class Sandbox:
    def __init__(self, run_id: str, app_path: str):
        self.run_id = run_id
        self.app_path = app_path  # 宿主机路径
        self.container_id: str | None = None
        self.preview_port: int | None = None
        self.status: str = "pending"  # pending / running / stopped / error
```

**容器配置**:
```python
CONTAINER_CONFIG = {
    "image": "node:20-alpine",
    "command": "sh -c 'npm install && npm run dev -- --port {port} --hostname 0.0.0.0'",
    "volumes": {
        "{app_path}": {"bind": "/app", "mode": "rw"}
    },
    "working_dir": "/app",
    "ports": None,  # 动态分配
    "environment": [
        "NODE_ENV=development",
        "WATCHPACK_POLLING=true",  # Windows 文件监听
    ],
    "detach": True,
    "auto_remove": False,  # 失败时保留容器看日志
    "mem_limit": "1g",
    "cpu_period": 100000,
    "cpu_quota": 50000,  # 50% CPU
}
```

**端口分配**:
```python
# paperforge/sandbox/docker_runner.py

import socket

def find_free_port() -> int:
    """找一个可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

async def start_sandbox(run_id: str, app_path: str) -> Sandbox:
    port = find_free_port()
    
    config = deepcopy(CONTAINER_CONFIG)
    config["ports"] = {"3000/tcp": port}
    config["command"] = config["command"].format(port=3000)
    
    container = docker_client.containers.create(**config)
    container.start()
    
    sandbox = Sandbox(
        run_id=run_id,
        app_path=app_path,
        container_id=container.id,
        preview_port=port,
        status="running",
    )
    
    storage.save_sandbox(sandbox)
    return sandbox
```

## 2. 容器生命周期

```python
class SandboxManager:
    async def start(self, run_id: str, app_path: str) -> Sandbox:
        """启动新容器"""
        ...
    
    async def stop(self, container_id: str) -> None:
        """停止并删除容器"""
        container = docker_client.containers.get(container_id)
        container.stop()
        container.remove()
    
    async def restart(self, container_id: str) -> Sandbox:
        """重启容器(代码改动后)"""
        ...
    
    async def get_logs(self, container_id: str, tail: int = 100) -> str:
        """获取容器日志"""
        container = docker_client.containers.get(container_id)
        return container.logs(tail=tail).decode()
    
    async def health_check(self, sandbox: Sandbox) -> bool:
        """检查 Next.js dev server 是否就绪"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://localhost:{sandbox.preview_port}",
                    timeout=2.0,
                )
            return resp.status_code == 200
        except Exception:
            return False
```

## 3. Preview URL 流程

```
1. Orchestrator 调用 generate_nextjs_app → app 文件落到 generated_apps/app_xxx/
2. Orchestrator 调用 run_in_sandbox(app_path)
3. SandboxManager 启动 Docker 容器,分配端口 34567
4. 后端轮询 health_check 直到 Next.js dev server 就绪(最多 60s)
5. emit preview.ready {url: "http://localhost:34567"}
6. 前端 iframe src = preview URL
```

**注意**:这里有一个 localhost 问题。如果 PaperForge 后端在 server A,用户在浏览器,浏览器访问 `localhost:34567` 是访问不到的(那是 server A 的端口)。

**解决方案**:
- 开发期:同一台机器,直接 `localhost:port`
- 生产期:通过 PaperForge 后端代理 `/api/preview/{sandbox_id}/{path}` → 容器

```python
# api/routes/preview.py

@router.get("/preview/{sandbox_id}/{path:path}")
async def proxy_preview(sandbox_id: str, path: str):
    sandbox = storage.get_sandbox_by_id(sandbox_id)
    if not sandbox or sandbox.status != "running":
        raise HTTPException(404)
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"http://localhost:{sandbox.preview_port}/{path}",
            timeout=10.0,
        )
    
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"Content-Type": resp.headers.get("Content-Type", "text/html")},
    )
```

但这里还有 Next.js 的 HMR WebSocket 问题(Next.js dev 用 WS 做 hot reload)。这个先不管,如果用户需要 HMR,可以独立解决。

## 4. 沙箱健康监控

**后台任务**:每 10s 扫描所有 running 的 sandbox
- 容器已死 → 标记为 error,emit `sandbox.error`
- 容器健康 → 继续
- 容器超时(2 小时) → 自动 stop

```python
# paperforge/sandbox/monitor.py

async def monitor_sandboxes():
    while True:
        sandboxes = storage.list_sandboxes(status="running")
        for sb in sandboxes:
            try:
                container = docker_client.containers.get(sb.container_id)
                if container.status != "running":
                    sb.status = "error"
                    storage.update_sandbox(sb)
                    emit_event(sb.run_id, "sandbox.error", {"reason": "Container died"})
            except docker.errors.NotFound:
                sb.status = "stopped"
                storage.update_sandbox(sb)
        
        await asyncio.sleep(10)
```

## 5. 代码热重载

用户在前端 CodeEditor 里改了 `app/page.tsx`,如何让 preview 刷新?

**方案 A:文件监听 + 容器内重启**
- 改文件后写回宿主机 `app_path/app/page.tsx`
- 容器内 Next.js dev server 自带 HMR,会自动刷新

这个方案最简单。Next.js dev server 的 HMR 本来就监听文件变化。只要宿主机的文件改了,容器内挂载的 `/app` 目录也会同步,Next.js 自动 reload。

```python
async def update_file(sandbox_id: str, file_path: str, content: str):
    sandbox = storage.get_sandbox_by_id(sandbox_id)
    full_path = Path(sandbox.app_path) / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    
    # Next.js dev server 会自动 HMR
    return {"success": True, "message": "File updated, HMR should refresh"}
```

## 6. 安全边界

**容器隔离**:
- 不挂载宿主机的敏感目录(只挂 `/app`)
- 容器内用 `node` 用户,不用 root
- 网络限制:容器只能访问外网,不能访问宿主机其他服务
- 资源限制:1GB 内存,50% CPU

**文件系统**:
- `generated_apps/` 目录下,每个 app 一个子目录
- 不允许路径穿越(`..` 检查)

**生成的代码安全**:
- Verifier 检查生成的代码里有没有硬编码的 secrets
- 生成的 app 不能执行系统命令(用 Next.js 的 Route Handlers,不让用 child_process)

## 7. 容器启动失败的降级

如果 Docker 不可用(比如用户在没装 Docker 的环境),怎么办?

**降级策略**:
1. 检测 Docker 是否可用
2. 不可用 → 直接在宿主机 `npm run dev`(需要 Node.js 环境)
3. 仍不可用 → 仅展示代码,不提供 preview

```python
async def start_sandbox(run_id: str, app_path: str) -> Sandbox:
    if not docker_available():
        return await start_local_dev_server(run_id, app_path)
    return await start_docker_container(run_id, app_path)
```

## 8. 多并发沙箱

用户可能同时开多个 run,每个 run 一个 app,每个 app 一个容器。

**限制**:
- 最多 3 个并发容器(可通过 `MAX_SANDBOXES` 配置)
- 超过限制时排队或拒绝

```python
async def start_sandbox(run_id: str, app_path: str) -> Sandbox:
    running = storage.count_sandboxes(status="running")
    if running >= config.MAX_SANDBOXES:
        raise SandboxError(f"Max {config.MAX_SANDBOXES} sandboxes reached")
    ...
```

## 9. Sandbox 与 Orchestrator 的集成

Orchestrator 通过两个 tool 控制沙箱:

```python
# paperforge/orchestrator/tools.py

async def handle_run_sandbox(args: dict, ctx: ToolContext) -> dict:
    """启动 sandbox,返回 preview URL"""
    app_path = args["app_path"]
    sandbox = await sandbox_manager.start(ctx.run_id, app_path)
    
    # 等待 Next.js dev server 就绪
    for _ in range(60):
        if await sandbox_manager.health_check(sandbox):
            break
        await asyncio.sleep(1)
    else:
        return {"error": "Sandbox failed to start in 60s"}
    
    return {
        "sandbox_id": sandbox.container_id,
        "preview_url": f"/api/preview/{sandbox.id}/",
        "status": "running",
    }

async def handle_stop_sandbox(args: dict, ctx: ToolContext) -> dict:
    """停止 sandbox"""
    sandbox_id = args["sandbox_id"]
    await sandbox_manager.stop(sandbox_id)
    return {"status": "stopped"}
```

## 10. 数据模型扩展

```sql
CREATE TABLE sandboxes (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    container_id TEXT,
    app_path TEXT,
    preview_port INTEGER,
    preview_url TEXT,
    status TEXT,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    stopped_at TIMESTAMP
);
```

## 11. 容器镜像预构建

第一次启动会拉 `node:20-alpine` 镜像,可能很慢。可以在安装时预拉:

```bash
docker pull node:20-alpine
```

或者提供一个 `docker-compose.yml` 预配置好。

## 12. Windows 文件监听问题

Windows 上 Docker Desktop 的文件挂载监听有问题(Next.js HMR 可能不工作)。

**解决方案**:
- 容器内设置 `WATCHPACK_POLLING=true`(已在 config 里)
- 或者用 WSL2 后端的 Docker Desktop

## 13. 沙箱日志流

用户可能想看 Next.js dev server 的输出(console.log、build error)。

**方案**:
- 后端有一个 `/api/sandboxes/{id}/logs` SSE 端点
- 持续推容器日志给前端

```python
@router.get("/sandboxes/{sandbox_id}/logs")
async def stream_logs(sandbox_id: str):
    async def event_stream():
        container = docker_client.containers.get(sandbox_id)
        for chunk in container.logs(stream=True, follow=True):
            yield f"data: {chunk.decode()}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

---

## 关键决策总结

1. **Docker 容器**:每个 app 一个容器,`node:20-alpine` 镜像
2. **端口动态分配**:避免冲突
3. **Preview 代理**:通过 PaperForge 后端代理,避免 localhost 问题
4. **HMR**:Next.js dev server 自带,文件改动自动刷新
5. **降级**:Docker 不可用时降级到本地 dev server
6. **并发限制**:最多 3 个并发沙箱
7. **安全**:容器隔离、文件路径检查、代码安全扫描
