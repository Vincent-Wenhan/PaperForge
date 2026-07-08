# PaperForge - Backend API Design

## 1. FastAPI 应用结构

```
api/
├── main.py                  # FastAPI app + lifespan
├── deps.py                  # 依赖注入
└── routes/
    ├── runs.py              # Run CRUD
    ├── messages.py          # 发送消息
    ├── events.py            # SSE 事件流
    ├── library.py           # 论文库
    ├── sandboxes.py         # 沙箱管理
    ├── preview.py           # Preview 代理
    ├── files.py             # 文件读写
    └── settings.py          # LLM/Docker 配置
```

## 2. 应用入口

```python
# api/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paperforge.storage import init_db
from paperforge.sandbox import DockerSandboxManager
from .routes import runs, messages, events, library, sandboxes, preview, files, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动:初始化数据库 + Docker 客户端
    init_db()
    app.state.sandbox_manager = DockerSandboxManager()
    # 启动沙箱监控后台任务
    asyncio.create_task(monitor_sandboxes(app.state.sandbox_manager))
    yield
    # 关闭:停止所有运行中的沙箱
    await app.state.sandbox_manager.shutdown_all()


app = FastAPI(
    title="PaperForge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(messages.router, prefix="/api/runs", tags=["messages"])
app.include_router(events.router, prefix="/api/runs", tags=["events"])
app.include_router(library.router, prefix="/api/library", tags=["library"])
app.include_router(sandboxes.router, prefix="/api/sandboxes", tags=["sandboxes"])
app.include_router(preview.router, prefix="/api/preview", tags=["preview"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
```

## 3. 依赖注入

```python
# api/deps.py

from fastapi import Depends, Request, HTTPException, Header
from paperforge.llm import get_llm_client
from paperforge.orchestrator import Orchestrator
from paperforge.storage import Storage


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def get_sandbox_manager(request: Request):
    return request.app.state.sandbox_manager


def get_llm():
    return get_llm_client()
```

## 4. Runs 路由

```python
# api/routes/runs.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
import uuid

router = APIRouter()


class RunCreate(BaseModel):
    title: str | None = None


class Run(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


@router.post("", response_model=Run)
async def create_run(req: RunCreate, storage: Storage = Depends(get_storage)):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    run = {
        "id": run_id,
        "title": req.title or "Untitled Run",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    storage.create_run(run)
    return run


@router.get("", response_model=list[Run])
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    storage: Storage = Depends(get_storage),
):
    return storage.list_runs(limit=limit, offset=offset)


@router.get("/{run_id}", response_model=Run)
async def get_run(run_id: str, storage: Storage = Depends(get_storage)):
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.delete("/{run_id}")
async def delete_run(run_id: str, storage: Storage = Depends(get_storage)):
    storage.delete_run(run_id)
    return {"status": "deleted"}
```

## 5. Messages 路由

```python
# api/routes/messages.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()


class MessageCreate(BaseModel):
    content: str


@router.post("/{run_id}/messages")
async def send_message(
    run_id: str,
    req: MessageCreate,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    storage: Storage = Depends(get_storage),
):
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    
    # 保存用户消息
    storage.add_message(run_id, {"role": "user", "content": req.content})
    
    # 异步启动 orchestrator(不阻塞 HTTP 响应)
    asyncio.create_task(orchestrator.run(run_id, req.content))
    
    return {"status": "queued", "run_id": run_id}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str, storage: Storage = Depends(get_storage)):
    return storage.list_messages(run_id)
```

## 6. Events 路由(SSE)

```python
# api/routes/events.py

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
):
    # 验证 run 存在
    if not storage.get_run(run_id):
        raise HTTPException(404, "Run not found")
    
    async def event_stream():
        # 创建事件队列
        queue = asyncio.Queue()
        event_manager.register(run_id, queue)
        
        try:
            # 先发送现有消息(支持断线重连)
            for msg in storage.list_messages(run_id):
                yield f"data: {json.dumps({'type': 'message', 'data': msg})}\n\n"
            
            # 持续推送新事件
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 发心跳保持连接
                    yield ": ping\n\n"
        finally:
            event_manager.unregister(run_id, queue)
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
```

## 7. Library 路由

```python
# api/routes/library.py

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pathlib import Path

router = APIRouter()


@router.get("")
async def list_library(storage: Storage = Depends(get_storage)):
    """列出论文库"""
    papers = storage.list_papers()
    return {"papers": papers}


@router.post("/upload")
async def upload_paper(
    file: UploadFile = File(...),
    storage: Storage = Depends(get_storage),
):
    """上传 PDF 到论文库"""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")
    
    paper_id = Path(file.filename).stem
    pdf_path = storage.library_dir / f"{paper_id}.pdf"
    
    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    paper = {
        "paper_id": paper_id,
        "title": paper_id,  # 默认用文件名,解析后更新
        "pdf_path": str(pdf_path),
        "status": "uploaded",
    }
    storage.upsert_paper(paper)
    
    return paper


@router.get("/{paper_id}")
async def get_paper(paper_id: str, storage: Storage = Depends(get_storage)):
    """获取单个论文及其 capability card"""
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found")
    
    card = storage.get_capability_card(paper_id)
    return {"paper": paper, "capability_card": card}


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str, storage: Storage = Depends(get_storage)):
    """从论文库删除论文"""
    storage.delete_paper(paper_id)
    return {"status": "deleted"}
```

## 8. Sandboxes 路由

```python
# api/routes/sandboxes.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()


class SandboxStart(BaseModel):
    app_path: str


@router.post("")
async def start_sandbox(
    req: SandboxStart,
    run_id: str = None,
    sandbox_manager = Depends(get_sandbox_manager),
    storage: Storage = Depends(get_storage),
):
    """启动沙箱"""
    try:
        sandbox = await sandbox_manager.start(run_id, req.app_path)
        storage.save_sandbox(sandbox)
        return sandbox
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{sandbox_id}")
async def get_sandbox(
    sandbox_id: str,
    storage: Storage = Depends(get_storage),
):
    """获取沙箱状态"""
    sb = storage.get_sandbox(sandbox_id)
    if not sb:
        raise HTTPException(404, "Sandbox not found")
    return sb


@router.post("/{sandbox_id}/stop")
async def stop_sandbox(
    sandbox_id: str,
    sandbox_manager = Depends(get_sandbox_manager),
    storage: Storage = Depends(get_storage),
):
    """停止沙箱"""
    await sandbox_manager.stop(sandbox_id)
    storage.update_sandbox(sandbox_id, status="stopped")
    return {"status": "stopped"}


@router.post("/{sandbox_id}/restart")
async def restart_sandbox(
    sandbox_id: str,
    sandbox_manager = Depends(get_sandbox_manager),
    storage: Storage = Depends(get_storage),
):
    """重启沙箱"""
    sb = storage.get_sandbox(sandbox_id)
    if not sb:
        raise HTTPException(404, "Sandbox not found")
    
    await sandbox_manager.stop(sb.container_id)
    sandbox = await sandbox_manager.start(sb.run_id, sb.app_path)
    storage.update_sandbox(sandbox_id, container_id=sandbox.container_id, preview_port=sandbox.preview_port, status="running")
    return sandbox


@router.get("/{sandbox_id}/logs")
async def stream_logs(
    sandbox_id: str,
    sandbox_manager = Depends(get_sandbox_manager),
):
    """SSE 流式获取容器日志"""
    async def log_stream():
        async for chunk in sandbox_manager.stream_logs(sandbox_id):
            yield f"data: {chunk}\n\n"
    
    return StreamingResponse(
        log_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

## 9. Preview 代理路由

```python
# api/routes/preview.py

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse, Response
import httpx

router = APIRouter()


@router.get("/{sandbox_id}/{path:path}")
async def proxy_preview(
    sandbox_id: str,
    path: str,
    request: Request,
    storage: Storage = Depends(get_storage),
):
    """代理到沙箱内的 Next.js dev server"""
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox or sandbox.status != "running":
        raise HTTPException(404, "Sandbox not running")
    
    # 构造转发请求
    target_url = f"http://localhost:{sandbox.preview_port}/{path}"
    
    async with httpx.AsyncClient(follow_redirects=False) as client:
        # 转发 query params
        if request.url.query:
            target_url += f"?{request.url.query}"
        
        # 转发 headers(过滤 host)
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "connection", "content-length")
        }
        
        # 转发 body
        body = await request.body()
        
        try:
            upstream_resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body,
                timeout=30.0,
            )
        except httpx.ConnectError:
            raise HTTPException(502, "Sandbox dev server not reachable")
    
    # 过滤响应 headers(避免重复 content-length / transfer-encoding)
    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in ("content-length", "transfer-encoding", "connection")
    }
    
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )
```

## 10. Files 路由(文件读写)

```python
# api/routes/files.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pathlib import Path
import os

router = APIRouter()


class FileWrite(BaseModel):
    content: str


@router.get("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def read_file(
    sandbox_id: str,
    file_path: str,
    storage: Storage = Depends(get_storage),
):
    """读取沙箱内的文件"""
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(404, "Sandbox not found")
    
    full_path = Path(sandbox.app_path) / file_path
    
    # 路径穿越检查
    try:
        full_path.resolve().relative_to(Path(sandbox.app_path).resolve())
    except ValueError:
        raise HTTPException(403, "Path outside sandbox")
    
    if not full_path.exists():
        raise HTTPException(404, "File not found")
    
    return {"path": file_path, "content": full_path.read_text(encoding="utf-8")}


@router.put("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def write_file(
    sandbox_id: str,
    file_path: str,
    req: FileWrite,
    storage: Storage = Depends(get_storage),
):
    """写入沙箱内的文件"""
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(404, "Sandbox not found")
    
    full_path = Path(sandbox.app_path) / file_path
    
    # 路径穿越检查
    try:
        full_path.resolve().relative_to(Path(sandbox.app_path).resolve())
    except ValueError:
        raise HTTPException(403, "Path outside sandbox")
    
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(req.content, encoding="utf-8")
    
    return {"path": file_path, "saved": True}


@router.get("/sandboxes/{sandbox_id}/tree")
async def get_file_tree(
    sandbox_id: str,
    storage: Storage = Depends(get_storage),
):
    """获取沙箱文件树"""
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(404, "Sandbox not found")
    
    tree = build_tree(Path(sandbox.app_path))
    return tree
```

## 11. Settings 路由

```python
# api/routes/settings.py

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Settings(BaseModel):
    llm_provider: str
    llm_model: str
    docker_available: bool
    max_sandboxes: int


@router.get("", response_model=Settings)
async def get_settings():
    from paperforge.config import config
    from paperforge.sandbox import docker_available
    
    return Settings(
        llm_provider=config.LLM_PROVIDER,
        llm_model=config.LLM_MODEL,
        docker_available=docker_available(),
        max_sandboxes=config.MAX_SANDBOXES,
    )
```

## 12. 事件管理器

```python
# paperforge/orchestrator/events.py

import asyncio
from collections import defaultdict
from typing import Any


class EventEmitter:
    """Orchestrator 用这个发事件,SSE 路由消费"""
    
    def __init__(self, run_id: str, queues: list[asyncio.Queue]):
        self.run_id = run_id
        self.queues = queues
    
    async def emit(self, event_type: str, data: Any):
        event = {"type": event_type, "data": data, "run_id": self.run_id}
        for q in self.queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 队列满了就丢


class EventManager:
    """管理每个 run 的事件订阅者"""
    
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
    
    def register(self, run_id: str, queue: asyncio.Queue):
        self._subscribers[run_id].append(queue)
    
    def unregister(self, run_id: str, queue: asyncio.Queue):
        if queue in self._subscribers[run_id]:
            self._subscribers[run_id].remove(queue)
    
    def get_queues(self, run_id: str) -> list[asyncio.Queue]:
        return self._subscribers.get(run_id, [])


event_manager = EventManager()
```

## 13. Orchestrator 整合

```python
# paperforge/orchestrator/loop.py

class Orchestrator:
    def __init__(
        self,
        llm: LLMClient,
        storage: Storage,
        sandbox_manager: DockerSandboxManager,
        event_manager: EventManager,
    ):
        self.llm = llm
        self.storage = storage
        self.sandbox_manager = sandbox_manager
        self.event_manager = event_manager
    
    async def run(self, run_id: str, user_message: str):
        """主循环"""
        queues = self.event_manager.get_queues(run_id)
        emit = EventEmitter(run_id, queues)
        
        await emit.emit("run.started", {"run_id": run_id})
        
        # 加载历史
        history = self.storage.list_messages(run_id)
        
        # 调用 LLM
        messages = history + [{"role": "user", "content": user_message}]
        
        while True:
            try:
                response = await self.llm.chat(
                    model=config.ORCHESTRATOR_MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                )
            except Exception as e:
                await emit.emit("run.error", {"error": str(e)})
                return
            
            if response.tool_calls:
                # 执行 tool
                for call in response.tool_calls:
                    await emit.emit("tool.call", {"name": call.name, "args": call.args})
                    
                    result = await self._dispatch_tool(call, run_id, emit)
                    
                    await emit.emit("tool.result", {"name": call.name, "result": result})
                    
                    messages.append({"role": "assistant", "tool_calls": [call]})
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
                continue
            
            # 普通消息
            await emit.emit("assistant.message", {"content": response.content})
            self.storage.add_message(run_id, {"role": "assistant", "content": response.content})
            
            await emit.emit("run.finished", {"run_id": run_id})
            return
```

## 14. 后端 API 关键决策

1. **SSE 而非 WebSocket**:SSE 更简单,HTTP/2 下足够实时
2. **事件管理器**:每个 run 一个 subscriber 列表,orchestrator 发事件给所有订阅者
3. **Preview 代理**:通过后端代理避免 localhost 问题,同时支持 HMR
4. **路径穿越检查**:所有文件操作都检查路径不超出 sandbox.app_path
5. **异步 orchestrator**:用 `asyncio.create_task` 启动,不阻塞 HTTP 响应

---

## 15. 完整的 API 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/runs | 创建 run |
| GET | /api/runs | 列出 runs |
| GET | /api/runs/{id} | 获取 run 详情 |
| DELETE | /api/runs/{id} | 删除 run |
| POST | /api/runs/{id}/messages | 发送消息(异步启动 orchestrator) |
| GET | /api/runs/{id}/messages | 列出消息历史 |
| GET | /api/runs/{id}/events | SSE 事件流 |
| GET | /api/library | 列出论文库 |
| POST | /api/library/upload | 上传 PDF |
| GET | /api/library/{paper_id} | 获取论文及 capability card |
| DELETE | /api/library/{paper_id} | 删除论文 |
| POST | /api/sandboxes | 启动沙箱 |
| GET | /api/sandboxes/{id} | 获取沙箱状态 |
| POST | /api/sandboxes/{id}/stop | 停止沙箱 |
| POST | /api/sandboxes/{id}/restart | 重启沙箱 |
| GET | /api/sandboxes/{id}/logs | SSE 容器日志流 |
| GET | /api/preview/{sandbox_id}/{path} | 代理 preview 请求 |
| GET | /api/files/sandboxes/{id}/tree | 获取文件树 |
| GET | /api/files/sandboxes/{id}/files/{path} | 读取文件 |
| PUT | /api/files/sandboxes/{id}/files/{path} | 写入文件 |
| GET | /api/settings | 获取设置(LLM provider、Docker 状态) |
