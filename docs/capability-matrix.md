# PaperForge Capability Matrix

> 六级状态的真实能力清单。任何条目标为 `production-ready` 必须附带测试或真实运行证据链接，禁止仅凭“模块存在”标注完成。

## 六级状态

| 状态 | 含义 |
|---|---|
| `designed` | 有设计文档/契约，尚未实现 |
| `implemented` | 代码已编写 |
| `wired` | 已接入主流程/事件链/接线 |
| `mock-tested` | 有自动化测试通过（mock LLM/内存态） |
| `real-model-verified` | 用真实 LLM + 真实数据验证过 |
| `production-ready` | 可重复验证 + 测试全绿 + 有运行证据 |

## 核心管线

| 能力 | 状态 | 证据 |
|---|---|---|
| PDF 解析 → capability card（PaperParser） | `mock-tested` | `tests/unit/test_agents.py` · `tests/test_parser_chunking.py` |
| 多 card 组合创新（Composer） | `mock-tested` | `tests/unit/test_agents.py` |
| PRD 精炼（ProductPlanner，多轮） | `mock-tested` | `tests/unit/test_agents.py` |
| PRD → Next.js app 生成（NextjsGenerator） | `mock-tested` | `tests/unit/test_generation_v3*.py` |
| App 可 build / 符合 PRD 校验（Verifier） | `mock-tested` | `tests/test_verifier_layers.py` · `tests/unit/test_verification_gates.py` |
| 全链路编排（Orchestrator loop） | `mock-tested` | `tests/unit/test_orchestrator.py` · `tests/e2e/*.py` |

## 实时主链（Task/Message/SSE）

| 能力 | 状态 | 证据 |
|---|---|---|
| POST /messages 原子创建 Message+Task | `mock-tested` | `tests/unit/test_realtime_task_atomic.py` |
| `public_id` 幂等重试不重复 | `mock-tested` | `tests/unit/test_realtime_task_atomic.py` |
| Task 生命周期事件（created/updated/completed/failed/cancelled） | `mock-tested` | `tests/unit/test_realtime_task_atomic.py` · `test_task_lifecycle.py` |
| SSE 事件流 + seq cursor + replay | `mock-tested` | `tests/unit/test_sse_events.py` |
| 免刷新收到回复（真实 SSE + local_test provider） | `real-model-verified` | `web/e2e/realtime.spec.ts` |
| 发送失败保留消息 + 幂等重试 | `mock-tested` | `web/components/__tests__/ComposerSendFailure.test.tsx` |
| 连接状态（connecting/connected/reconnecting/offline/error） | `mock-tested` | `web/lib/__tests__/run-session.test.tsx` |

## 前端 UI

| 能力 | 状态 | 证据 |
|---|---|---|
| 三栏工作台（Sidebar + Chat + Workbench） | `mock-tested` | `web/components/__tests__/*.test.tsx` |
| 流式消息渲染 + 重载不重复 | `mock-tested` | `web/e2e/streaming.spec.ts` |
| Task 状态 / 步骤时间线投影 | `mock-tested` | `web/components/__tests__/TaskTimeline.test.tsx` |
| Monaco 代码编辑 + 文件树 | `mock-tested` | `web/components/__tests__/FileRenameDelete.test.tsx` · `PreviewWorkspace.test.tsx` |
| 审批卡片（HITL） | `mock-tested` | `tests/unit/test_approval_policy.py` · `tests/test_approvals_api.py` · `tests/test_approval_checkpoint.py` |

## 沙箱 / 预览

| 能力 | 状态 | 证据 |
|---|---|---|
| Docker sandbox 启动 / 停止 / 端口分配 | `implemented` | `paperforge/sandbox/`（需 Docker 实机验证） |
| live preview 就绪事件 | `mock-tested` | `web/components/__tests__/PreviewStatusToolbar.test.tsx` |
| HMR / 安全边界 | `designed` | `docs/04-sandbox-preview.md` |

## 限制说明

- Sandbox 条目前停在 `implemented`：CI 环境无 Docker，需本地 Docker 实机跑通后再升级到 `mock-tested`。
- `real-model-verified` 目前仅覆盖实时主链（local_test provider 证明接线真实）；端到端真实 LLM 生成需在后续 PR 中补齐证据。
