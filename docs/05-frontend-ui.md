# PaperForge - Frontend Web UI Design

## 1. 整体布局

```
┌─────────────────────────────────────────────────────────────┐
│  Topbar: PaperForge  [Run: attention-app]    [Settings]    │
├──────────┬──────────────────────────────┬───────────────────┤
│          │                              │                   │
│ Sidebar  │   Chat Panel                 │   Preview Panel   │
│          │   (对话 + 事件流)             │   (iframe + 面板) │
│  Runs    │                              │                   │
│  Library │                              │                   │
│          │                              │                   │
│          │                              │                   │
└──────────┴──────────────────────────────┴───────────────────┘
```

侧边栏 240px,Preview Panel 默认 50% 宽度,Chat Panel 占剩余空间。

## 2. Sidebar

```
[+ New Run]

RECENT RUNS
  ◯ attention-app           2 min ago
  ◯ vae-image-editor        1 hour ago
  ◯ clip-search-engine      yesterday

LIBRARY
  📄 Attention Is All You Need    2017
  📄 VAE                           2013
  📄 CLIP                          2021

[+ Add Paper]
```

**组件**:
- `RunsList`:展示最近 runs,点击切换
- `LibraryList`:展示论文库,点击查看 capability card
- `AddPaperButton`:触发文件上传

**数据流**:
- 点击 run → `GET /api/runs/{id}` 加载完整状态
- 点击 library paper → 展示 capability card 详情
- 上传 paper → `POST /api/library` → 自动出现在列表

## 3. Chat Panel

```tsx
<div className="flex flex-col h-full">
  <ChatHeader run={run} />
  
  <ChatMessages className="flex-1 overflow-y-auto">
    {messages.map(m => <MessageView key={m.id} message={m} />)}
    {events.map(e => <EventView event={e} />)}
  </ChatMessages>
  
  <ChatInput onSend={handleSend} disabled={isRunning} />
</div>
```

**消息类型**:
- `user`:用户消息,靠右,蓝色气泡
- `assistant`:AI 回复,靠左,灰色气泡,支持 markdown 渲染
- `tool_call`:tool 调用卡片,展示 tool name + args
- `tool_result`:tool 返回卡片,展示 result
- `artifact`:生成的 artifact 卡片,点击展开

**渲染**:
- 用 `react-markdown` + `react-syntax-highlighter`
- tool_call 卡片折叠/展开
- artifact 卡片支持内嵌预览(capability card 用表格展示)

## 4. Preview Panel

```tsx
<div className="flex flex-col h-full">
  <PreviewToolbar>
    <Tabs>
      <Tab>Preview</Tab>
      <Tab>Code</Tab>
      <Tab>Console</Tab>
      <Tab>Verification</Tab>
    </Tabs>
    <Actions>
      <Button>Restart</Button>
      <Button>Open in new tab</Button>
    </Actions>
  </PreviewToolbar>
  
  <TabContent>
    {tab === 'preview' && <PreviewFrame sandbox={sandbox} />}
    {tab === 'code' && <CodeEditor sandbox={sandbox} />}
    {tab === 'console' && <ConsoleLogs sandbox={sandbox} />}
    {tab === 'verification' && <VerificationReportView report={report} />}
  </TabContent>
</div>
```

**PreviewFrame**:
```tsx
function PreviewFrame({ sandbox }: { sandbox: Sandbox }) {
  if (!sandbox || sandbox.status !== 'running') {
    return <PreviewLoading />;
  }
  return (
    <iframe
      src={`/api/preview/${sandbox.id}/`}
      className="w-full h-full border-0"
      sandbox="allow-scripts allow-same-origin allow-forms"
    />
  );
}
```

**CodeEditor**:
```tsx
function CodeEditor({ sandbox }: { sandbox: Sandbox }) {
  const [currentFile, setCurrentFile] = useState<string>('');
  const [content, setContent] = useState<string>('');
  
  // 文件树
  <FileTree
    rootPath={sandbox.app_path}
    onSelect={async (path) => {
      const c = await api.readFile(sandbox.id, path);
      setCurrentFile(path);
      setContent(c);
    }}
  />
  
  // Monaco editor
  <MonacoEditor
    value={content}
    language={getLanguage(currentFile)}
    onChange={(value) => setContent(value || '')}
    onSave={async () => {
      await api.updateFile(sandbox.id, currentFile, content);
    }}
  />
}
```

**ConsoleLogs**:
```tsx
function ConsoleLogs({ sandbox }: { sandbox: Sandbox }) {
  const [logs, setLogs] = useState<string[]>([]);
  
  useEffect(() => {
    const es = new EventSource(`/api/sandboxes/${sandbox.id}/logs`);
    es.onmessage = (e) => setLogs(prev => [...prev, e.data]);
    return () => es.close();
  }, [sandbox.id]);
  
  return <LogViewer logs={logs} />;
}
```

## 5. 状态管理

用 Zustand(比 Redux 轻,比 Context 强):

```typescript
// web/lib/store.ts

interface AppState {
  // 当前 run
  currentRun: Run | null;
  messages: Message[];
  events: Event[];
  
  // Sandbox
  sandbox: Sandbox | null;
  
  // UI
  activeTab: 'preview' | 'code' | 'console' | 'verification';
  sidebarCollapsed: boolean;
  
  // Actions
  setCurrentRun: (run: Run) => void;
  addMessage: (msg: Message) => void;
  addEvent: (event: Event) => void;
  setSandbox: (sb: Sandbox) => void;
  setActiveTab: (tab: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentRun: null,
  messages: [],
  events: [],
  sandbox: null,
  activeTab: 'preview',
  sidebarCollapsed: false,
  
  setCurrentRun: (run) => set({ currentRun: run, messages: [], events: [] }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  addEvent: (event) => set((s) => ({ events: [...s.events, event] })),
  setSandbox: (sb) => set({ sandbox: sb }),
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
```

## 6. SSE 客户端

```typescript
// web/lib/sse.ts

export class SSEClient {
  private es: EventSource | null = null;
  private handlers: Record<string, (data: any) => void> = {};
  
  connect(runId: string) {
    this.es = new EventSource(`/api/runs/${runId}/events`);
    
    this.es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      const handler = this.handlers[event.type];
      if (handler) handler(event.data);
    };
    
    this.es.onerror = () => {
      // 重连逻辑
    };
  }
  
  on(eventType: string, handler: (data: any) => void) {
    this.handlers[eventType] = handler;
  }
  
  disconnect() {
    this.es?.close();
    this.es = null;
  }
}
```

## 7. API 客户端

```typescript
// web/lib/api.ts

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api';

export const api = {
  // Runs
  createRun: async (title?: string): Promise<Run> => {
    const resp = await fetch(`${API_BASE}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    return resp.json();
  },
  
  listRuns: async (): Promise<Run[]> => {
    const resp = await fetch(`${API_BASE}/runs`);
    return resp.json();
  },
  
  getRun: async (id: string): Promise<Run> => {
    const resp = await fetch(`${API_BASE}/runs/${id}`);
    return resp.json();
  },
  
  // Messages
  sendMessage: async (runId: string, content: string): Promise<{ messageId: string }> => {
    const resp = await fetch(`${API_BASE}/runs/${runId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    return resp.json();
  },
  
  // SSE
  streamEvents: (runId: string): EventSource => {
    return new EventSource(`${API_BASE}/runs/${runId}/events`);
  },
  
  // Sandbox
  startSandbox: async (runId: string, appPath: string): Promise<Sandbox> => { ... },
  stopSandbox: async (sandboxId: string): Promise<void> => { ... },
  updateFile: async (sandboxId: string, path: string, content: string): Promise<void> => { ... },
  readFile: async (sandboxId: string, path: string): Promise<string> => { ... },
  
  // Library
  listLibrary: async (): Promise<Paper[]> => { ... },
  uploadPaper: async (file: File): Promise<Paper> => { ... },
  getCapabilityCard: async (paperId: string): Promise<CapabilityCard> => { ... },
  
  // Preview
  getPreviewUrl: (sandboxId: string) => `${API_BASE}/preview/${sandboxId}/`,
};
```

## 8. 路由结构

```
web/app/
├── layout.tsx                  # RootLayout,加载全局样式和 providers
├── page.tsx                    # 首页,重定向到 /runs 或显示 empty state
├── runs/
│   ├── page.tsx                # Runs 列表页
│   └── [id]/
│       ├── page.tsx            # 单个 run 的工作台
│       └── loading.tsx         # Loading skeleton
├── library/
│   ├── page.tsx                # 论文库列表
│   └── [paperId]/
│       └── page.tsx            # 单个 paper 的 capability card 详情
├── settings/
│   └── page.tsx                # 设置页(LLM provider、Docker config)
```

## 9. 关键交互流程

### 流程 1:上传论文并生成 app

```
1. 用户点击 [+ Add Paper] → 文件选择器
2. 前端上传 PDF → POST /api/library/upload
3. 后端返回 paper_id
4. 用户进入 /runs/new
5. 用户输入:"把这个论文产品化"
6. 前端 POST /api/runs + POST /api/runs/{id}/messages
7. 前端订阅 SSE → /api/runs/{id}/events
8. 后端启动 orchestrator
9. orchestrator 调用 parse_paper → emit tool.call + tool.result
10. orchestrator 调用 generate_nextjs_app → emit artifact.created
11. orchestrator 调用 run_in_sandbox → emit sandbox.started + preview.ready
12. 前端收到 preview.ready → iframe 加载 preview URL
13. orchestrator 返回总结 → emit assistant.message + run.finished
```

### 流程 2:编辑代码并查看效果

```
1. 用户切换到 Code tab
2. 前端加载文件树 + 默认打开 app/page.tsx
3. 用户在 Monaco 编辑器里修改代码
4. 用户按 Ctrl+S → 前端 PUT /api/sandboxes/{id}/files/{path}
5. 后端写文件到 sandbox.app_path
6. Next.js dev server HMR 自动刷新 iframe
7. 前端切回 Preview tab 看效果
```

### 流程 3:查看 verification report

```
1. 用户切换到 Verification tab
2. 前端从 storage.get_verification_report(run_id) 拉数据
3. 渲染:
   - 构建状态(成功/失败)
   - PRD 覆盖率(进度条)
   - Mock/Real 边界检查(清单)
   - 整体评分(大数字)
   - 改进建议(列表)
```

## 10. UI 组件库

用 **shadcn/ui**(基于 Radix UI + Tailwind):

- `Button`, `Input`, `Textarea`, `Select`, `Checkbox`, `Switch`
- `Dialog`, `Sheet`, `Popover`, `Tooltip`
- `Tabs`, `Accordion`, `Collapsible`
- `Toast`, `Alert`, `Badge`, `Card`

**为什么 shadcn/ui**:
- 复制粘贴的组件,不是 npm 依赖
- 完全可定制(代码在你项目里)
- Tailwind 原生支持
- 社区活跃,生态丰富

## 11. 样式系统

```typescript
// web/tailwind.config.ts

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'hsl(0 0% 100%)',
        foreground: 'hsl(240 10% 3.9%)',
        muted: 'hsl(240 4.8% 95.9%)',
        primary: 'hsl(240 5.9% 10%)',
        // ... shadcn/ui 标准
      },
    },
  },
};
```

## 12. 关键组件清单

| 组件 | 路径 | 职责 |
|---|---|---|
| `RootLayout` | `app/layout.tsx` | 全局 provider、字体、元数据 |
| `Workbench` | `app/runs/[id]/page.tsx` | 三栏布局主容器 |
| `Sidebar` | `components/Sidebar.tsx` | Runs + Library 列表 |
| `ChatPanel` | `components/ChatPanel.tsx` | 对话区 |
| `MessageView` | `components/MessageView.tsx` | 单条消息渲染 |
| `ToolCallCard` | `components/ToolCallCard.tsx` | Tool 调用卡片 |
| `ArtifactCard` | `components/ArtifactCard.tsx` | Artifact 卡片 |
| `PreviewPanel` | `components/PreviewPanel.tsx` | 预览区主容器 |
| `PreviewFrame` | `components/PreviewFrame.tsx` | iframe 预览 |
| `CodeEditor` | `components/CodeEditor.tsx` | Monaco 代码编辑器 |
| `FileTree` | `components/FileTree.tsx` | 文件树 |
| `ConsoleLogs` | `components/ConsoleLogs.tsx` | 控制台日志 |
| `VerificationReportView` | `components/VerificationReportView.tsx` | Verification report 渲染 |
| `CapabilityCardView` | `components/CapabilityCardView.tsx` | Capability card 渲染 |
| `ComposerView` | `components/ComposerView.tsx` | Composition 渲染 |
| `PrdView` | `components/PrdView.tsx` | PRD 渲染 |

## 13. 错误处理

**全局 Error Boundary**:
```tsx
// web/app/error.tsx

'use client';

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex items-center justify-center h-screen">
      <Card>
        <CardHeader>出错了</CardHeader>
        <CardContent>
          <p>{error.message}</p>
          <Button onClick={reset}>重试</Button>
        </CardContent>
      </Card>
    </div>
  );
}
```

**SSE 断线重连**:
```typescript
private reconnect() {
  setTimeout(() => {
    if (this.es) this.connect(this.currentRunId);
  }, 1000);
}
```

## 14. 响应式

- 桌面(>=1024px):三栏布局
- 平板(768-1023px):侧边栏折叠,Chat + Preview 两栏
- 手机(<768px):单栏,底部 tab 切换

---

## 关键决策总结

1. **三栏 IDE 风布局**(Sidebar + Chat + Preview)
2. **Next.js App Router + shadcn/ui + Zustand**
3. **SSE 事件流**
4. **Monaco 代码编辑器**
5. **iframe sandbox 预览**
