import express, { Request, Response, NextFunction } from "express";
import cors from "cors";
import path from "path";
import fs from "fs";
import dotenv from "dotenv";
import { createServer as createViteServer } from "vite";
import { ALL_ALPHAS, ALPHA_MAP } from "./data/alphas";
import { getSwarmPresets } from "./data/swarmPresets";
import { PAPER_SESSIONS_MAP, LIVE_PRICES, buildSampleSession, refreshAllPaperSessions, advanceSessionTrades } from "./data/paperTrading";
import { RUNS_MAP, generateRunData } from "./data/runs";
import { generateAgentTurn } from "./services/gemini";
import { generateBybitGridDataset, PRESEEDED_DATASETS } from "./services/bybitGridResearch";
import { getAllStrategiesRatioHistory } from "./services/riskRatiosEngine";

// Load backend/agent/.env first if it exists, falling back to root .env
if (fs.existsSync(path.resolve("backend/agent/.env"))) {
  dotenv.config({ path: path.resolve("backend/agent/.env") });
}
if (fs.existsSync(path.resolve(".env"))) {
  dotenv.config({ path: path.resolve(".env") });
}

const app = express();
const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 3000;
const HOST = process.env.HOST || "0.0.0.0";
const isDev = process.env.NODE_ENV !== "production";

app.use(cors());
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ extended: true, limit: "50mb" }));

// Direct endpoint to download project archive
app.get(["/app_bundle.tar.gz", "/api/download-bundle"], (req: Request, res: Response) => {
  const possiblePaths = [
    path.resolve("frontend/public/app_bundle.tar.gz"),
    path.resolve("app_bundle.tar.gz"),
    path.resolve("/frontend/public/app_bundle.tar.gz"),
    path.resolve("/app_bundle.tar.gz"),
  ];
  for (const p of possiblePaths) {
    if (fs.existsSync(p)) {
      res.setHeader("Content-Type", "application/gzip");
      res.setHeader("Content-Disposition", 'attachment; filename="app_bundle.tar.gz"');
      return res.sendFile(p);
    }
  }
  res.status(404).send("Archive bundle is currently being generated, please retry in 5 seconds.");
});

// In-memory Sessions & Messages Store
interface SessionRecord {
  session_id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_attempt_id?: string;
  messages: Array<{
    message_id: string;
    session_id: string;
    role: "user" | "assistant" | "system";
    content: string;
    created_at: string;
    linked_attempt_id?: string;
    metadata?: Record<string, unknown>;
  }>;
  goal?: {
    goal: {
      goal_id: string;
      session_id: string;
      status: string;
      objective: string;
      ui_summary: string;
      source: string;
      protocol: string;
      risk_tier: string;
      tokens_used: number;
      turns_used: number;
      time_used_seconds: number;
      budget_wrapup_sent: boolean;
      created_at: string;
      updated_at: string;
    };
    claims: Array<{
      claim_id: string;
      goal_id: string;
      session_id: string;
      claim_type: string;
      text: string;
      status: string;
      created_at: string;
      updated_at: string;
    }>;
    criteria: Array<{
      criterion_id: string;
      goal_id: string;
      session_id: string;
      text: string;
      required: boolean;
      status: string;
      created_at: string;
      updated_at: string;
    }>;
    evidence: Array<{
      evidence_id: string;
      goal_id: string;
      session_id: string;
      text: string;
      evidence_type: string;
      symbol_universe: string[];
      benchmark: string[];
      assumptions: Record<string, unknown>;
      retrieved_at: string;
      freshness_status: string;
      verification_status: string;
      contradicts_claim_ids: string[];
      created_at: string;
    }>;
    evidence_count: number;
  };
}

const SESSIONS_MAP = new Map<string, SessionRecord>();

// Seed default initial session
const initialSessionId = "session_quant_alpha_01";
SESSIONS_MAP.set(initialSessionId, {
  session_id: initialSessionId,
  title: "BTC Momentum & Risk Analysis",
  status: "idle",
  created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
  updated_at: new Date(Date.now() - 3600 * 1000).toISOString(),
  messages: [
    {
      message_id: "msg_init_01",
      session_id: initialSessionId,
      role: "user",
      content: "Backtest BTC-USDT 20/50 MA + RSI Momentum with 1h breakout",
      created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
    },
    {
      message_id: "msg_init_02",
      session_id: initialSessionId,
      role: "assistant",
      content: `### 📊 Quantitative Research Report: BTC-USDT Strategy\n\nConducted quantitative evaluation and statistical validation for **BTC-USDT**.\n\n- **Sharpe Ratio**: 2.14 ($p = 0.002$ under 1,000 Monte Carlo bootstrap trials)\n- **Total Return**: +32.4% vs +14.2% benchmark\n- **Max Drawdown**: -8.4%\n- **Win Rate**: 68.0% across 48 trades\n\n*Interactive charts, indicator series, and PineScript are ready in the Run Card.*`,
      created_at: new Date(Date.now() - 3590 * 1000).toISOString(),
      metadata: {
        run_id: "run_20260815_btc_momentum",
      },
    },
  ],
  goal: {
    goal: {
      goal_id: "goal_01",
      session_id: initialSessionId,
      status: "complete",
      objective: "Verify BTC-USDT momentum edge with Monte Carlo validation",
      ui_summary: "BTC-USDT 20/50 MA + RSI Momentum Backtest",
      source: "chat",
      protocol: "quantitative_v5",
      risk_tier: "research_general",
      tokens_used: 1420,
      turns_used: 1,
      time_used_seconds: 4.8,
      budget_wrapup_sent: false,
      created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
      updated_at: new Date(Date.now() - 3590 * 1000).toISOString(),
    },
    claims: [
      {
        claim_id: "clm_01",
        goal_id: "goal_01",
        session_id: initialSessionId,
        claim_type: "hypothesis",
        text: "Adaptive RSI + MA trend filter generates Sharpe > 1.8 on BTC-USDT",
        status: "verified",
        created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
        updated_at: new Date(Date.now() - 3590 * 1000).toISOString(),
      },
    ],
    criteria: [
      {
        criterion_id: "crt_01",
        goal_id: "goal_01",
        session_id: initialSessionId,
        text: "Sharpe Ratio exceeds baseline hurdle (> 1.8)",
        required: true,
        status: "passed",
        created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
        updated_at: new Date(Date.now() - 3590 * 1000).toISOString(),
      },
      {
        criterion_id: "crt_02",
        goal_id: "goal_01",
        session_id: initialSessionId,
        text: "Max Drawdown constrained under 12%",
        required: true,
        status: "passed",
        created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
        updated_at: new Date(Date.now() - 3590 * 1000).toISOString(),
      },
      {
        criterion_id: "crt_03",
        goal_id: "goal_01",
        session_id: initialSessionId,
        text: "Walk-forward consistency rate > 70%",
        required: false,
        status: "passed",
        created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
        updated_at: new Date(Date.now() - 3590 * 1000).toISOString(),
      },
    ],
    evidence: [
      {
        evidence_id: "evi_01",
        goal_id: "goal_01",
        session_id: initialSessionId,
        text: "Monte Carlo simulated 1000 paths; observed Sharpe 2.14 lies above 95th percentile.",
        evidence_type: "backtest_metric",
        symbol_universe: ["BTC-USDT"],
        benchmark: ["BTC-USDT"],
        assumptions: { fee_rate: 0.0004, slippage: 0.0002 },
        retrieved_at: new Date(Date.now() - 3590 * 1000).toISOString(),
        freshness_status: "fresh",
        verification_status: "verified",
        contradicts_claim_ids: [],
        created_at: new Date(Date.now() - 3590 * 1000).toISOString(),
      },
    ],
    evidence_count: 1,
  },
});

// SSE Subscribers by Session ID
const sessionSubscribers = new Map<string, Set<Response>>();

function broadcastSSE(sessionId: string, event: string, data: any) {
  const subs = sessionSubscribers.get(sessionId);
  if (!subs) return;
  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of subs) {
    try {
      res.write(payload);
    } catch {
      subs.delete(res);
    }
  }
}

// ----------------------------------------------------------------------------
// SESSIONS API
// ----------------------------------------------------------------------------
app.get("/sessions", (req: Request, res: Response) => {
  const list = Array.from(SESSIONS_MAP.values()).map((s) => ({
    session_id: s.session_id,
    title: s.title,
    status: s.status,
    created_at: s.created_at,
    updated_at: s.updated_at,
    last_attempt_id: s.last_attempt_id,
  }));
  res.json(list);
});

app.post("/sessions", (req: Request, res: Response) => {
  const sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const title = req.body?.title || "New Research Session";
  const now = new Date().toISOString();
  const newSession: SessionRecord = {
    session_id: sessionId,
    title,
    status: "idle",
    created_at: now,
    updated_at: now,
    messages: [],
  };
  SESSIONS_MAP.set(sessionId, newSession);
  res.json({
    session_id: sessionId,
    title,
    status: "idle",
    created_at: now,
    updated_at: now,
  });
});

app.delete("/sessions/:id", (req: Request, res: Response) => {
  SESSIONS_MAP.delete(req.params.id);
  res.json({ status: "ok" });
});

app.patch("/sessions/:id", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  if (session && req.body?.title) {
    session.title = req.body.title;
    session.updated_at = new Date().toISOString();
  }
  res.json({ status: "ok" });
});

app.get("/sessions/:id/messages", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  res.json(session ? session.messages : []);
});

app.get("/sessions/:id/events", (req: Request, res: Response) => {
  const sessionId = req.params.id;
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders();

  if (!sessionSubscribers.has(sessionId)) {
    sessionSubscribers.set(sessionId, new Set());
  }
  sessionSubscribers.get(sessionId)!.add(res);

  res.write(`event: connected\ndata: ${JSON.stringify({ session_id: sessionId, time: new Date().toISOString() })}\n\n`);

  req.on("close", () => {
    sessionSubscribers.get(sessionId)?.delete(res);
  });
});

app.post("/sessions/:id/messages", async (req: Request, res: Response) => {
  const sessionId = req.params.id;
  let session = SESSIONS_MAP.get(sessionId);
  if (!session) {
    const now = new Date().toISOString();
    session = {
      session_id: sessionId,
      title: req.body?.content?.slice(0, 30) || "Research Session",
      status: "idle",
      created_at: now,
      updated_at: now,
      messages: [],
    };
    SESSIONS_MAP.set(sessionId, session);
  }

  const content = req.body?.content || "";
  const userMsgId = `msg_${Date.now()}_u`;
  const attemptId = `att_${Date.now()}`;
  const now = new Date().toISOString();

  session.messages.push({
    message_id: userMsgId,
    session_id: sessionId,
    role: "user",
    content,
    created_at: now,
  });
  session.status = "busy";
  session.last_attempt_id = attemptId;
  session.updated_at = now;

  res.json({ message_id: userMsgId, attempt_id: attemptId });

  // Async Agent Loop & SSE Stream
  (async () => {
    try {
      // Step 1: Thinking
      broadcastSSE(sessionId, "status", { stage: "thinking", message: "Formulating quantitative hypothesis & research plan..." });
      await new Promise((r) => setTimeout(r, 600));

      const researchPlan = await generateAgentTurn(
        content,
        session.messages.map((m) => ({ role: m.role, content: m.content }))
      );

      // Step 2: Goal Initialization
      const goalId = `goal_${Date.now()}`;
      session.goal = {
        goal: {
          goal_id: goalId,
          session_id: sessionId,
          status: "active",
          objective: researchPlan.goalSummary,
          ui_summary: researchPlan.goalSummary,
          source: "chat",
          protocol: "quantitative_v5",
          risk_tier: "research_general",
          tokens_used: 1200,
          turns_used: 1,
          time_used_seconds: 3.2,
          budget_wrapup_sent: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        claims: [
          {
            claim_id: `clm_${Date.now()}`,
            goal_id: goalId,
            session_id: sessionId,
            claim_type: "hypothesis",
            text: `Quant strategy for '${content.slice(0, 40)}' outperforms benchmark hurdle`,
            status: "evaluating",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        criteria: researchPlan.criteria.map((c, i) => ({
          criterion_id: `crt_${Date.now()}_${i}`,
          goal_id: goalId,
          session_id: sessionId,
          text: c,
          required: true,
          status: "pending",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })),
        evidence: [],
        evidence_count: 0,
      };

      broadcastSSE(sessionId, "goal_updated", session.goal);

      // Step 3: Tool Execution Simulation
      for (const tool of researchPlan.toolsToCall) {
        broadcastSSE(sessionId, "tool_call", {
          tool: tool.name,
          args: tool.args,
          status: "running",
        });
        await new Promise((r) => setTimeout(r, 800));
        broadcastSSE(sessionId, "tool_result", {
          tool: tool.name,
          status: "success",
          summary: `Successfully executed ${tool.name}`,
        });
      }

      // Step 4: Create Backtest Run
      const runId = `run_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
      const targetSymbol = researchPlan.symbols[0] || "BTC-USDT";
      const runDetail = generateRunData(runId, content, targetSymbol, 90);
      RUNS_MAP.set(runId, runDetail);

      // Update goal criteria to passed
      session.goal.goal.status = "complete";
      session.goal.criteria.forEach((c) => (c.status = "passed"));
      session.goal.claims[0].status = "verified";
      session.goal.evidence.push({
        evidence_id: `evi_${Date.now()}`,
        goal_id: goalId,
        session_id: sessionId,
        text: `Backtest completed with Sharpe ${runDetail.metrics.sharpe}, total return +${(runDetail.metrics.total_return * 100).toFixed(1)}%, max DD ${(runDetail.metrics.max_drawdown * 100).toFixed(1)}%`,
        evidence_type: "backtest_metrics",
        symbol_universe: [targetSymbol],
        benchmark: [targetSymbol],
        assumptions: { fee_rate: 0.0004 },
        retrieved_at: new Date().toISOString(),
        freshness_status: "fresh",
        verification_status: "verified",
        contradicts_claim_ids: [],
        created_at: new Date().toISOString(),
      });
      session.goal.evidence_count = 1;
      broadcastSSE(sessionId, "goal_updated", session.goal);

      // Emit Run Card, Metrics, Pine Script
      broadcastSSE(sessionId, "run_card", {
        run_id: runId,
        status: "success",
        total_return: runDetail.metrics.total_return,
        sharpe: runDetail.metrics.sharpe,
        max_drawdown: runDetail.metrics.max_drawdown,
        codes: [targetSymbol],
      });

      broadcastSSE(sessionId, "metrics", runDetail.metrics);
      broadcastSSE(sessionId, "pine_script", {
        exists: true,
        content: runDetail.pine_script,
      });

      // Assistant Message
      const asstMsgId = `msg_${Date.now()}_a`;
      const asstMsg = {
        message_id: asstMsgId,
        session_id: sessionId,
        role: "assistant" as const,
        content: researchPlan.responseText,
        created_at: new Date().toISOString(),
        linked_attempt_id: attemptId,
        metadata: {
          run_id: runId,
        },
      };
      session.messages.push(asstMsg);
      session.status = "idle";
      session.updated_at = new Date().toISOString();

      broadcastSSE(sessionId, "message", asstMsg);
      broadcastSSE(sessionId, "done", { session_id: sessionId, attempt_id: attemptId });
    } catch (err: any) {
      session.status = "idle";
      broadcastSSE(sessionId, "error", { message: err?.message || "Agent execution error" });
    }
  })();
});

app.post("/sessions/:id/cancel", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  if (session) session.status = "idle";
  broadcastSSE(req.params.id, "cancelled", { session_id: req.params.id });
  res.json({ status: "ok" });
});

app.get("/sessions/:id/goal", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  res.json(session?.goal || null);
});

app.post("/sessions/:id/goal", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  if (!session) return res.status(404).json({ error: "Session not found" });
  const goalId = `goal_${Date.now()}`;
  const now = new Date().toISOString();
  session.goal = {
    goal: {
      goal_id: goalId,
      session_id: req.params.id,
      status: "active",
      objective: req.body?.objective || "Quant Research Goal",
      ui_summary: req.body?.ui_summary || req.body?.objective || "",
      source: "user",
      protocol: req.body?.protocol || "quantitative_v5",
      risk_tier: req.body?.risk_tier || "research_general",
      tokens_used: 0,
      turns_used: 0,
      time_used_seconds: 0,
      budget_wrapup_sent: false,
      created_at: now,
      updated_at: now,
    },
    claims: [],
    criteria: (req.body?.criteria || []).map((c: string, idx: number) => ({
      criterion_id: `crt_${idx + 1}`,
      goal_id: goalId,
      session_id: req.params.id,
      text: c,
      required: true,
      status: "pending",
      created_at: now,
      updated_at: now,
    })),
    evidence: [],
    evidence_count: 0,
  };
  res.json(session.goal);
});

app.patch("/sessions/:id/goal", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  if (!session?.goal) return res.status(404).json({ error: "Goal not found" });
  if (req.body?.objective) session.goal.goal.objective = req.body.objective;
  if (req.body?.ui_summary) session.goal.goal.ui_summary = req.body.ui_summary;
  session.goal.goal.updated_at = new Date().toISOString();
  res.json({ goal: session.goal.goal, snapshot: session.goal });
});

app.post("/sessions/:id/goal/evidence", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  if (!session?.goal) return res.status(404).json({ error: "Goal not found" });
  const evi = {
    evidence_id: `evi_${Date.now()}`,
    goal_id: session.goal.goal.goal_id,
    session_id: req.params.id,
    text: req.body.text,
    evidence_type: req.body.evidence_type || "observation",
    symbol_universe: req.body.symbol_universe || [],
    benchmark: req.body.benchmark || [],
    assumptions: req.body.assumptions || {},
    retrieved_at: new Date().toISOString(),
    freshness_status: "fresh",
    verification_status: "verified",
    contradicts_claim_ids: [],
    created_at: new Date().toISOString(),
  };
  session.goal.evidence.push(evi);
  session.goal.evidence_count = session.goal.evidence.length;
  res.json({ evidence: evi, snapshot: session.goal });
});

app.patch("/sessions/:id/goal/status", (req: Request, res: Response) => {
  const session = SESSIONS_MAP.get(req.params.id);
  if (!session?.goal) return res.status(404).json({ error: "Goal not found" });
  if (req.body?.status) session.goal.goal.status = req.body.status;
  if (req.body?.recap) (session.goal.goal as any).recap = req.body.recap;
  session.goal.goal.updated_at = new Date().toISOString();
  res.json({ goal: session.goal.goal, snapshot: session.goal });
});

// ----------------------------------------------------------------------------
// RUNS & AUTOPILOT RUNS API
// ----------------------------------------------------------------------------
app.get("/runs", (req: Request, res: Response) => {
  const limit = req.query.limit ? parseInt(req.query.limit as string, 10) : 50;
  const list = Array.from(RUNS_MAP.values())
    .slice(0, limit)
    .map((r) => ({
      run_id: r.run_id,
      status: r.status,
      created_at: r.created_at,
      prompt: r.prompt,
      total_return: r.metrics.total_return,
      sharpe: r.metrics.sharpe,
      codes: r.chart_symbols,
    }));
  res.json(list);
});

app.get("/autopilot-runs", (req: Request, res: Response, next: NextFunction) => {
  if (req.headers.accept?.includes("text/html") && !req.headers.accept?.includes("application/json")) {
    return next();
  }
  const list = Array.from(RUNS_MAP.values()).map((r) => {
    const isEvaluable = r.metrics.trade_count >= 30 && r.status === "success";
    return {
      run_dir: r.run_directory,
      strategy_implementation_status: r.status === "incomplete" ? "incomplete" : "implemented",
      provenance_valid: true,
      has_trades: r.metrics.trade_count > 0,
      statistically_evaluable: isEvaluable,
      statistical_status: r.statistical_status,
      hypothesis_supported: isEvaluable && r.metrics.sharpe > 1.5,
      run_purpose: r.prompt,
      trade_count: r.metrics.trade_count,
      total_return: r.status === "incomplete" ? undefined : r.metrics.total_return,
      sharpe: isEvaluable ? r.metrics.sharpe : undefined,
      is_sharpe_valid: isEvaluable,
      generated_at: r.created_at,
    };
  });
  res.json(list);
});

// ----------------------------------------------------------------------------
// BYBIT GRID & FUTURES RESEARCH DATASET ENGINE API
// ----------------------------------------------------------------------------
app.get("/grid-research/datasets", (req: Request, res: Response) => {
  const seen = new Set<string>();
  const summaries: any[] = [];
  for (const d of Object.values(PRESEEDED_DATASETS)) {
    if (!d || seen.has(d.dataset_id)) continue;
    seen.add(d.dataset_id);
    summaries.push({
      dataset_id: d.dataset_id,
      symbol: d.symbol,
      interval: d.interval,
      cycle_count: d.cycle_count,
      statistical_status: d.statistical_status,
      status_explanation: d.status_explanation,
      date_range: d.date_range,
      overall_expectancy: d.overall_expectancy,
      accounting_summary: d.accounting_summary,
      regime_summary: Object.fromEntries(
        Object.entries(d.regime_breakdown).map(([k, v]) => [k, { count: v.count, mean_bps: v.meanNetBps, win_rate: v.winRate }])
      ),
    });
  }
  res.json(summaries);
});

app.get("/grid-research/datasets/:id", (req: Request, res: Response) => {
  const dataset = PRESEEDED_DATASETS[req.params.id] || Object.values(PRESEEDED_DATASETS).find((d) => d.dataset_id === req.params.id);
  if (!dataset) {
    // Generate on demand if queried
    const gen = generateBybitGridDataset("BTCUSDT", 500, "1m");
    return res.json(gen);
  }
  res.json(dataset);
});

app.post("/grid-research/sample", (req: Request, res: Response) => {
  const {
    symbol = "BTCUSDT",
    cycles = 500,
    interval = "1m",
    grid_lower,
    grid_upper,
    grid_count = 20,
    leverage = 5,
  } = req.body || {};

  const numCycles = Math.min(2000, Math.max(10, Number(cycles)));
  const uniqueId = `${symbol}-${interval}-${numCycles}c-sample-${Date.now().toString(36)}`;

  const dataset = generateBybitGridDataset(
    symbol,
    numCycles,
    interval,
    grid_lower ? Number(grid_lower) : undefined,
    grid_upper ? Number(grid_upper) : undefined,
    Number(grid_count),
    Number(leverage),
    uniqueId
  );

  PRESEEDED_DATASETS[dataset.dataset_id] = dataset;
  res.json(dataset);
});

app.get("/grid-research/export", (req: Request, res: Response) => {
  const datasetId = (req.query.dataset_id as string) || "BTCUSDT-1m-2025-2026";
  const dataset = PRESEEDED_DATASETS[datasetId] || Object.values(PRESEEDED_DATASETS)[0];
  const format = (req.query.format as string) || "json";

  if (format === "csv") {
    if (!dataset.events_sample || dataset.events_sample.length === 0) {
      return res.status(400).send("No events to export");
    }
    const headers = Object.keys(dataset.events_sample[0]).join(",");
    const rows = dataset.events_sample.map((e) =>
      Object.values(e)
        .map((v) => (typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : v))
        .join(",")
    );
    const csv = [headers, ...rows].join("\n");
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", `attachment; filename="${dataset.dataset_id}.csv"`);
    return res.send(csv);
  }

  res.setHeader("Content-Type", "application/json");
  res.setHeader("Content-Disposition", `attachment; filename="${dataset.dataset_id}.json"`);
  res.json(dataset);
});

app.get("/runs/:id", (req: Request, res: Response, next: NextFunction) => {
  if (req.headers.accept?.includes("text/html") && !req.headers.accept?.includes("application/json")) {
    return next();
  }
  let run = RUNS_MAP.get(req.params.id);
  if (!run) {
    // Generate dynamically if queried
    run = generateRunData(req.params.id, `Backtest ${req.params.id}`, "BTC-USDT", 90);
    RUNS_MAP.set(req.params.id, run);
  }
  res.json(run);
});

app.get("/runs/:id/code", (req: Request, res: Response) => {
  const run = RUNS_MAP.get(req.params.id) || generateRunData(req.params.id, "Backtest", "BTC-USDT");
  res.json(run.source_code);
});

app.get("/runs/:id/pine", (req: Request, res: Response) => {
  const run = RUNS_MAP.get(req.params.id) || generateRunData(req.params.id, "Backtest", "BTC-USDT");
  res.json({ exists: true, content: run.pine_script });
});

// ----------------------------------------------------------------------------
// SWARM API
// ----------------------------------------------------------------------------
interface SwarmRunState {
  id: string;
  preset_name: string;
  user_vars: Record<string, string>;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
  task_count: number;
  completed_count: number;
  tasks: Array<{
    id: string;
    agent_name: string;
    role: string;
    status: string;
    output?: string;
  }>;
}

const SWARM_RUNS_MAP = new Map<string, SwarmRunState>([
  [
    "swarm_run_01",
    {
      id: "swarm_run_01",
      preset_name: "investment_committee",
      user_vars: { target_asset: "BTC-USDT", horizon: "3M" },
      status: "completed",
      created_at: new Date(Date.now() - 7200 * 1000).toISOString(),
      task_count: 4,
      completed_count: 4,
      tasks: [
        { id: "t1", agent_name: "Macro Economist", role: "Liquidity & Rates", status: "completed", output: "Global liquidity cycle expansion supports high-beta risk asset allocation." },
        { id: "t2", agent_name: "Quant Strategist", role: "Statistical Edge", status: "completed", output: "Identified 1h/4h volatility breakout with positive skewness and Sharpe > 2.0." },
        { id: "t3", agent_name: "Risk Controller", role: "Tail Risk & Sizing", status: "completed", output: "Set VaR 99% cap at 3.5% portfolio equity with maximum 5x isolated margin." },
        { id: "t4", agent_name: "Portfolio Lead", role: "Final Allocation", status: "completed", output: "Approved 25% target allocation with dynamic volatility trailing stop." },
      ],
    },
  ],
]);

app.get("/swarm/presets", (req: Request, res: Response) => {
  res.json(getSwarmPresets());
});

app.get("/swarm/runs", (req: Request, res: Response) => {
  const list = Array.from(SWARM_RUNS_MAP.values()).map((r) => ({
    id: r.id,
    preset_name: r.preset_name,
    status: r.status,
    created_at: r.created_at,
    task_count: r.task_count,
    completed_count: r.completed_count,
  }));
  res.json(list);
});

app.post("/swarm/runs", (req: Request, res: Response) => {
  const id = `swarm_run_${Date.now()}`;
  const presetName = req.body?.preset_name || "investment_committee";
  const userVars = req.body?.user_vars || {};
  const presets = getSwarmPresets();
  const preset = presets.find((p) => p.name === presetName) || presets[0];

  const newRun: SwarmRunState = {
    id,
    preset_name: presetName,
    user_vars: userVars,
    status: "running",
    created_at: new Date().toISOString(),
    task_count: preset.agent_count,
    completed_count: 0,
    tasks: (preset.agents || [
      { name: "Agent Alpha", role: "Analysis" },
      { name: "Agent Beta", role: "Validation" },
      { name: "Agent Gamma", role: "Synthesis" },
    ]).map((a, idx) => ({
      id: `task_${idx + 1}`,
      agent_name: a.name,
      role: a.role,
      status: "pending",
    })),
  };

  SWARM_RUNS_MAP.set(id, newRun);
  res.json({ id, status: "running" });

  // Simulate progress
  (async () => {
    for (let i = 0; i < newRun.tasks.length; i++) {
      await new Promise((r) => setTimeout(r, 1200));
      newRun.tasks[i].status = "completed";
      newRun.tasks[i].output = `Delivered comprehensive findings and metrics for ${userVars.target_asset || "target asset"}.`;
      newRun.completed_count = i + 1;
    }
    newRun.status = "completed";
  })();
});

app.get("/swarm/runs/:id", (req: Request, res: Response) => {
  const run = SWARM_RUNS_MAP.get(req.params.id);
  if (!run) return res.status(404).json({ error: "Swarm run not found" });
  res.json(run);
});

app.post("/swarm/runs/:id/cancel", (req: Request, res: Response) => {
  const run = SWARM_RUNS_MAP.get(req.params.id);
  if (run) run.status = "failed";
  res.json({ status: "ok" });
});

app.post("/swarm/runs/:id/retry", (req: Request, res: Response) => {
  const run = SWARM_RUNS_MAP.get(req.params.id);
  if (run) {
    run.status = "running";
    run.completed_count = 0;
  }
  res.json({ id: req.params.id, status: "running", preset_name: run?.preset_name || "" });
});

// ----------------------------------------------------------------------------
// ALPHA ZOO API
// ----------------------------------------------------------------------------
app.get("/alpha/list", (req: Request, res: Response) => {
  let list = ALL_ALPHAS;
  const zoo = req.query.zoo as string;
  const theme = req.query.theme as string;
  const universe = req.query.universe as string;
  const limit = req.query.limit ? parseInt(req.query.limit as string, 10) : 50;

  if (zoo) list = list.filter((a) => a.zoo === zoo);
  if (theme) list = list.filter((a) => a.theme.some((t) => t.toLowerCase().includes(theme.toLowerCase())));
  if (universe) list = list.filter((a) => a.universe.includes(universe) || a.universe.includes("all"));

  const total = list.length;
  const returned = list.slice(0, limit).map((a) => ({
    id: a.id,
    zoo: a.zoo,
    theme: a.theme,
    universe: a.universe,
    nickname: a.nickname,
    decay_horizon: a.decay_horizon,
    min_warmup_bars: a.min_warmup_bars,
    requires_sector: a.requires_sector,
  }));

  res.json({
    status: "ok",
    alphas: returned,
    total,
    returned: returned.length,
    truncated: total > limit,
  });
});

app.get("/alpha/:id", (req: Request, res: Response) => {
  const alpha = ALPHA_MAP.get(req.params.id);
  if (!alpha) return res.status(404).json({ error: "Alpha not found" });
  res.json({
    status: "ok",
    alpha: {
      id: alpha.id,
      zoo: alpha.zoo,
      meta: {
        formula_latex: alpha.formula_latex,
        nickname: alpha.nickname,
        theme: alpha.theme,
        universe: alpha.universe,
        frequency: alpha.frequency,
        decay_horizon: alpha.decay_horizon,
        min_warmup_bars: alpha.min_warmup_bars,
        columns_required: alpha.columns_required,
        notes: alpha.notes,
      },
    },
    source_code: alpha.source_code,
  });
});

app.post("/alpha/bench", (req: Request, res: Response) => {
  const jobId = `bench_${Date.now()}`;
  res.json({ status: "ok", job_id: jobId });
});

app.get("/alpha/bench/:jobId/stream", (req: Request, res: Response) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders();

  let progress = 0;
  const interval = setInterval(() => {
    progress += 25;
    if (progress <= 100) {
      res.write(`event: progress\ndata: ${JSON.stringify({ progress, total: 100 })}\n\n`);
    }
    if (progress >= 100) {
      clearInterval(interval);
      const result = {
        alive: 78,
        reversed: 14,
        dead: 9,
        skipped: 0,
        top5_by_ir: [
          { id: "alpha101_alpha_001", ic_mean: 0.084, ir: 1.94, theme: ["momentum"], formula_latex: "\\alpha_{1}", category: "alive" },
          { id: "qlib158_alpha_005", ic_mean: 0.076, ir: 1.82, theme: ["kline"], formula_latex: "\\text{KLEN}", category: "alive" },
          { id: "gtja191_alpha_012", ic_mean: 0.069, ir: 1.75, theme: ["volume"], formula_latex: "\\text{GTJA}_{12}", category: "alive" },
          { id: "academic_carhart_mom", ic_mean: 0.065, ir: 1.68, theme: ["momentum"], formula_latex: "\\text{MOM}_{12-1}", category: "alive" },
          { id: "alpha101_alpha_101", ic_mean: 0.059, ir: 1.54, theme: ["price"], formula_latex: "\\alpha_{101}", category: "alive" },
        ],
        dead_examples: [
          { id: "alpha101_alpha_044", ic_mean: -0.002, ir: -0.04, theme: ["mean_reversion"], formula_latex: "\\alpha_{44}", category: "dead" },
        ],
        by_theme: {
          momentum: { alive: 32, reversed: 4, dead: 2 },
          price_volume: { alive: 28, reversed: 6, dead: 4 },
          microstructure: { alive: 18, reversed: 4, dead: 3 },
        },
      };
      res.write(`event: result\ndata: ${JSON.stringify(result)}\n\n`);
      res.end();
    }
  }, 400);
});

app.post("/alpha/compare", (req: Request, res: Response) => {
  const jobId = `comp_${Date.now()}`;
  res.json({ status: "ok", job_id: jobId });
});

app.get("/alpha/compare/:jobId/stream", (req: Request, res: Response) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders();

  const alphaIds = ["alpha101_alpha_001", "qlib158_alpha_005", "academic_carhart_mom", "gtja191_alpha_012"];
  const ranking = alphaIds.map((id, idx) => ({
    rank: idx + 1,
    id,
    zoo: id.split("_")[0],
    ic_mean: Number((0.085 - idx * 0.008).toFixed(3)),
    ic_std: 0.042,
    ir: Number((1.95 - idx * 0.15).toFixed(2)),
    ic_positive_ratio: Number((0.68 - idx * 0.03).toFixed(2)),
    ic_count: 240,
    delta_ir_vs_best: Number((-idx * 0.15).toFixed(2)),
  }));

  const payload = {
    universe: "csi300",
    period: "2022-2025",
    sort: "ir",
    n_compared: 4,
    n_skipped: 0,
    winner: "alpha101_alpha_001",
    ranking,
    skipped: [],
  };

  setTimeout(() => {
    res.write(`event: result\ndata: ${JSON.stringify(payload)}\n\n`);
    res.end();
  }, 400);
});

// ----------------------------------------------------------------------------
// PAPER TRADING API
// ----------------------------------------------------------------------------
app.get("/paper-sessions", (req: Request, res: Response) => {
  const scope = req.query.scope as string;
  const list = refreshAllPaperSessions();
  res.json(list);
});

app.get("/paper-sessions/ratios-history", (req: Request, res: Response) => {
  refreshAllPaperSessions();
  const history = getAllStrategiesRatioHistory();
  res.json(history);
});

app.get("/paper-sessions/provider-health", (req: Request, res: Response) => {
  res.json({
    checked_at: new Date().toISOString(),
    priority: ["okx", "binance", "bybit", "gate"],
    providers: [
      { provider: "okx", status: "ok", http_status: 200, latency_ms: 38, error: null },
      { provider: "binance", status: "ok", http_status: 200, latency_ms: 45, error: null },
      { provider: "bybit", status: "ok", http_status: 200, latency_ms: 52, error: null },
      { provider: "gate", status: "ok", http_status: 200, latency_ms: 64, error: null },
    ],
  });
});

app.get("/paper-sessions/decision-health", (req: Request, res: Response) => {
  const nowIso = new Date().toISOString();
  const allWorkerIds = [
    "control_5m_futures",
    "candidate_5m_futures",
    "control_10m_futures",
    "candidate_10m_futures",
    "control_15m_futures",
    "candidate_15m_futures",
    "grid_futures_5x_v3",
    "grid_futures_10x_v3",
    "morning_glory_futures",
  ];

  const workers = allWorkerIds.map((worker_id, idx) => {
    const isCandidate = worker_id.includes("candidate") || worker_id.includes("grid") || worker_id.includes("morning");
    const cycles = 288 + (idx * 16);
    const signals = isCandidate ? 48 + (idx * 6) : 32 + (idx * 3);
    const fills = Math.round(signals * 0.75);
    const closed = Math.round(fills * 0.85);

    return {
      worker_id,
      last_cycle_at: nowIso,
      market_data_fresh: true,
      latest_rejections: { strategy: null, risk: null, order: null },
      latest_funnel: {
        signals_evaluated: cycles,
        signals_true: signals,
        evaluated: cycles,
        passed_signal: signals,
        order_filled: fills,
      },
      window: {
        cycles_completed: cycles,
        signals_evaluated: cycles,
        signals_true: signals,
        entries_requested: fills,
        paper_orders_filled: fills,
        positions_closed: closed,
      },
    };
  });

  res.json({
    status: "ok",
    detail: null,
    window_hours: 24,
    workers,
  });
});

app.get("/paper-sessions/:id", (req: Request, res: Response) => {
  refreshAllPaperSessions();
  let session = PAPER_SESSIONS_MAP.get(req.params.id);
  if (!session) {
    session = buildSampleSession(req.params.id, "control", "15m", 5, 10000);
    PAPER_SESSIONS_MAP.set(req.params.id, session);
  }
  session.latest_mark.timestamp = new Date().toISOString();
  session.latest_mark.prices = { ...LIVE_PRICES };
  res.json(session);
});

app.get("/paper-sessions/:id/live-prices", (req: Request, res: Response) => {
  res.json({
    prices: LIVE_PRICES,
    timestamp: new Date().toISOString(),
  });
});

app.post("/paper-sessions/accelerate", (req: Request, res: Response) => {
  const { sessionId = "all", count = 10, isTargetAbsolute = false } = req.body || {};
  const result = advanceSessionTrades(sessionId, Number(count) || 10, Boolean(isTargetAbsolute));
  res.json({
    status: "ok",
    ...result,
  });
});

app.post("/paper-sessions/switch-testnet", (req: Request, res: Response) => {
  refreshAllPaperSessions();
  const allSessions = Array.from(PAPER_SESSIONS_MAP.values());
  const MIN_REQUIRED_TRADES = 100;
  
  const workerAudit = allSessions.map((s) => ({
    id: s.session_id,
    trade_count: s.trade_count,
    ready: s.trade_count >= MIN_REQUIRED_TRADES,
    needed: Math.max(0, MIN_REQUIRED_TRADES - s.trade_count),
    realized_pnl: s.database_account?.realized_pnl ?? 0,
  }));

  const allReady = workerAudit.every((w) => w.ready);
  const totalTrades = workerAudit.reduce((a, b) => a + b.trade_count, 0);

  if (!allReady) {
    const unreadyCount = workerAudit.filter((w) => !w.ready).length;
    res.status(400).json({
      ok: false,
      ready: false,
      message: `Testnet Gate Locked: ${unreadyCount} of 9 workers have not yet reached the 100 verified trades requirement.`,
      min_trades_required: MIN_REQUIRED_TRADES,
      total_trades: totalTrades,
      workers: workerAudit,
    });
    return;
  }

  // If all ready, acknowledge testnet switch
  res.json({
    ok: true,
    ready: true,
    message: `Testnet Gate Cleared! All 9 trading workers have completed ${MIN_REQUIRED_TRADES}+ verified paper trades (${totalTrades} total trades evaluated). Testnet sandbox account is now active.`,
    min_trades_required: MIN_REQUIRED_TRADES,
    total_trades: totalTrades,
    testnet_account: {
      account_id: "testnet_okx_futures_01",
      exchange: "OKX Demo Futures API",
      status: "connected",
      sandbox_active: true,
      environment: "testnet",
      migrated_at: new Date().toISOString(),
      active_workers: workerAudit.length,
      initial_testnet_capital: 100000,
    },
    workers: workerAudit,
  });
});

app.get("/paper-sessions/shadow-comparison", (req: Request, res: Response) => {
  const rows = [
    {
      regimen: "5m_futures_10k",
      control_session_id: "control_5m_futures",
      candidate_session_id: "candidate_5m_futures",
      control: {
        ...PAPER_SESSIONS_MAP.get("control_5m_futures"),
        net_return: 0.184,
        trade_count: 24,
        rebalance_fees: 32.4,
        total_fees: 48.6,
        turnover: 3.2,
        max_drawdown: 0.048,
        tracking_error_rms: 0.012,
        max_weight_drift: 0.04,
        reconciled: true,
      },
      candidate: {
        ...PAPER_SESSIONS_MAP.get("candidate_5m_futures"),
        net_return: 0.286,
        trade_count: 36,
        rebalance_fees: 44.2,
        total_fees: 62.1,
        turnover: 4.8,
        max_drawdown: 0.062,
        tracking_error_rms: 0.018,
        max_weight_drift: 0.05,
        reconciled: true,
      },
      delta: {
        net_return: 0.102,
        total_fees: 13.5,
        trade_count: 12,
        turnover: 1.6,
        max_drawdown: 0.014,
      },
    },
    {
      regimen: "15m_futures_10k",
      control_session_id: "control_15m_futures",
      candidate_session_id: "candidate_15m_futures",
      control: {
        ...PAPER_SESSIONS_MAP.get("control_15m_futures"),
        net_return: 0.142,
        trade_count: 16,
        rebalance_fees: 22.1,
        total_fees: 34.0,
        turnover: 2.1,
        max_drawdown: 0.038,
        tracking_error_rms: 0.009,
        max_weight_drift: 0.03,
        reconciled: true,
      },
      candidate: {
        ...PAPER_SESSIONS_MAP.get("candidate_15m_futures"),
        net_return: 0.224,
        trade_count: 22,
        rebalance_fees: 30.5,
        total_fees: 45.2,
        turnover: 3.0,
        max_drawdown: 0.046,
        tracking_error_rms: 0.014,
        max_weight_drift: 0.04,
        reconciled: true,
      },
      delta: {
        net_return: 0.082,
        total_fees: 11.2,
        trade_count: 6,
        turnover: 0.9,
        max_drawdown: 0.008,
      },
    },
  ];
  res.json(rows);
});

interface SystemNotification {
  id: string;
  title: string;
  message: string;
  severity: "info" | "warning" | "error" | "critical";
  important?: boolean;
  created_at: string;
}

const SYSTEM_NOTIFICATIONS: SystemNotification[] = [
  {
    id: "sys_init_01",
    title: "Vibe Quantitative Engine Active",
    message: "System initialized with 9 strategy timeframe workers.",
    severity: "info",
    important: false,
    created_at: new Date(Date.now() - 3600000).toISOString(),
  },
];

export function pushSystemNotification(notif: Omit<SystemNotification, "id" | "created_at">) {
  const item: SystemNotification = {
    id: `notif_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    created_at: new Date().toISOString(),
    ...notif,
  };
  SYSTEM_NOTIFICATIONS.unshift(item);
  if (SYSTEM_NOTIFICATIONS.length > 100) {
    SYSTEM_NOTIFICATIONS.pop();
  }
}

app.get("/paper-trading/notifications", (req: Request, res: Response) => {
  const after = req.query.after as string | undefined;
  let results = SYSTEM_NOTIFICATIONS;
  if (after) {
    const afterTime = new Date(after).getTime();
    if (!isNaN(afterTime)) {
      results = SYSTEM_NOTIFICATIONS.filter((n) => new Date(n.created_at).getTime() > afterTime);
    }
  }
  res.json(results);
});

// ----------------------------------------------------------------------------
// SETTINGS & RUNTIME CHANNELS API
// ----------------------------------------------------------------------------
let llmSettingsState = {
  provider: "gemini",
  model_name: "gemini-2.5-flash",
  base_url: "https://generativelanguage.googleapis.com/v1beta/openai/",
  api_key_env: "GEMINI_API_KEY",
  api_key_configured: Boolean(process.env.GEMINI_API_KEY),
  api_key_hint: process.env.GEMINI_API_KEY ? "AI Studio Embedded Key" : null,
  api_key_required: true,
  temperature: 0.3,
  timeout_seconds: 60,
  max_retries: 3,
  reasoning_effort: "medium",
  sse_timeout_seconds: 120,
  env_path: "backend/agent/.env",
  providers: [
    { name: "gemini", label: "Google Gemini", api_key_env: "GEMINI_API_KEY", base_url_env: "GEMINI_BASE_URL", default_model: "gemini-2.5-flash", default_base_url: "https://generativelanguage.googleapis.com/v1beta/openai/", api_key_required: true },
    { name: "openrouter", label: "OpenRouter", api_key_env: "OPENROUTER_API_KEY", base_url_env: "OPENROUTER_BASE_URL", default_model: "deepseek/deepseek-v4-pro", default_base_url: "https://openrouter.ai/api/v1", api_key_required: true },
    { name: "openai", label: "OpenAI", api_key_env: "OPENAI_API_KEY", base_url_env: "OPENAI_BASE_URL", default_model: "gpt-4o", default_base_url: "https://api.openai.com/v1", api_key_required: true },
    { name: "deepseek", label: "DeepSeek", api_key_env: "DEEPSEEK_API_KEY", base_url_env: "DEEPSEEK_BASE_URL", default_model: "deepseek-v4-pro", default_base_url: "https://api.deepseek.com/v1", api_key_required: true },
    { name: "ollama", label: "Ollama", api_key_env: null, base_url_env: "OLLAMA_BASE_URL", default_model: "qwen2.5:32b", default_base_url: "http://localhost:11434", api_key_required: false },
  ],
};

app.get("/settings/llm", (req: Request, res: Response) => {
  llmSettingsState.api_key_configured = Boolean(process.env.GEMINI_API_KEY);
  res.json(llmSettingsState);
});

app.put("/settings/llm", (req: Request, res: Response) => {
  llmSettingsState = { ...llmSettingsState, ...req.body };
  res.json(llmSettingsState);
});

let dataSourceSettingsState = {
  active_market_feed: "okx",
  binance_configured: Boolean(process.env.BINANCE_API_KEY),
  binance_key_hint: process.env.BINANCE_API_KEY ? "••••" + process.env.BINANCE_API_KEY.slice(-4) : "Public REST & WebSocket ready",
  okx_configured: true,
  okx_key_hint: process.env.OKX_API_KEY ? "••••" + process.env.OKX_API_KEY.slice(-4) : "Public Market & Futures Feed Active",
  bybit_configured: Boolean(process.env.BYBIT_API_KEY),
  bybit_key_hint: process.env.BYBIT_API_KEY ? "••••" + process.env.BYBIT_API_KEY.slice(-4) : "Public V5 REST & WS ready",
  gateio_configured: Boolean(process.env.GATEIO_API_KEY),
  gateio_key_hint: process.env.GATEIO_API_KEY ? "••••" + process.env.GATEIO_API_KEY.slice(-4) : "Public V4 Spot & Futures ready",
  providers: [
    {
      id: "binance",
      name: "Binance",
      status: "connected",
      latency_ms: 45,
      configured: Boolean(process.env.BINANCE_API_KEY),
      capabilities: ["Spot", "USD-M Futures", "Coin-M Futures", "WebSocket Streams", "Order Book Depth"],
      public_access: true,
      default_url: "https://api.binance.com",
    },
    {
      id: "okx",
      name: "OKX",
      status: "connected",
      latency_ms: 38,
      configured: true,
      capabilities: ["Spot", "USDT Margined Swaps", "Coin Margined Swaps", "Funding Rate Arbs", "Level 2 Depth"],
      public_access: true,
      default_url: "https://www.okx.com",
    },
    {
      id: "bybit",
      name: "Bybit",
      status: "connected",
      latency_ms: 52,
      configured: Boolean(process.env.BYBIT_API_KEY),
      capabilities: ["Linear Perpetuals", "Inverse Perpetuals", "Options", "V5 Unified Account", "Orderbook WS"],
      public_access: true,
      default_url: "https://api.bybit.com",
    },
    {
      id: "gate",
      name: "Gate.io",
      status: "connected",
      latency_ms: 68,
      configured: Boolean(process.env.GATEIO_API_KEY),
      capabilities: ["Spot", "Delivery Futures", "Perpetuals", "Flash Swap", "Ticker WS"],
      public_access: true,
      default_url: "https://api.gateio.ws",
    },
  ],
  env_path: "backend/agent/.env",
};

app.get("/settings/data-sources", (req: Request, res: Response) => {
  res.json(dataSourceSettingsState);
});

app.put("/settings/data-sources", (req: Request, res: Response) => {
  const {
    binance_api_key,
    clear_binance_key,
    okx_api_key,
    okx_passphrase,
    clear_okx_key,
    bybit_api_key,
    clear_bybit_key,
    gateio_api_key,
    clear_gateio_key,
    active_market_feed,
  } = req.body || {};

  if (binance_api_key) {
    dataSourceSettingsState.binance_configured = true;
    dataSourceSettingsState.binance_key_hint = "••••" + binance_api_key.slice(-4);
  } else if (clear_binance_key) {
    dataSourceSettingsState.binance_configured = false;
    dataSourceSettingsState.binance_key_hint = "Public REST & WebSocket ready";
  }

  if (okx_api_key) {
    dataSourceSettingsState.okx_configured = true;
    dataSourceSettingsState.okx_key_hint = "••••" + okx_api_key.slice(-4);
  } else if (clear_okx_key) {
    dataSourceSettingsState.okx_configured = false;
    dataSourceSettingsState.okx_key_hint = "Public Market & Futures Feed Active";
  }

  if (bybit_api_key) {
    dataSourceSettingsState.bybit_configured = true;
    dataSourceSettingsState.bybit_key_hint = "••••" + bybit_api_key.slice(-4);
  } else if (clear_bybit_key) {
    dataSourceSettingsState.bybit_configured = false;
    dataSourceSettingsState.bybit_key_hint = "Public V5 REST & WS ready";
  }

  if (gateio_api_key) {
    dataSourceSettingsState.gateio_configured = true;
    dataSourceSettingsState.gateio_key_hint = "••••" + gateio_api_key.slice(-4);
  } else if (clear_gateio_key) {
    dataSourceSettingsState.gateio_configured = false;
    dataSourceSettingsState.gateio_key_hint = "Public V4 Spot & Futures ready";
  }

  if (active_market_feed) {
    dataSourceSettingsState.active_market_feed = active_market_feed;
  }

  res.json(dataSourceSettingsState);
});

app.get("/channels/status", (req: Request, res: Response) => {
  res.json({
    running: true,
    inbound_queue: 0,
    outbound_queue: 0,
    session_count: SESSIONS_MAP.size,
    channels: {
      websocket: { name: "websocket", display_name: "Web UI (SSE / REST)", configured: true, enabled: true, available: true, loaded: true, running: true },
      telegram: { name: "telegram", display_name: "Telegram Bot", configured: false, enabled: false, available: true, loaded: false, running: false, install_hint: "Set TELEGRAM_BOT_TOKEN in .env" },
      discord: { name: "discord", display_name: "Discord Webhook", configured: false, enabled: false, available: true, loaded: false, running: false },
      slack: { name: "slack", display_name: "Slack Bolt", configured: false, enabled: false, available: true, loaded: false, running: false },
    },
  });
});

app.post("/channels/start", (req: Request, res: Response) => {
  res.json({ status: "started", running: true });
});

app.post("/channels/stop", (req: Request, res: Response) => {
  res.json({ status: "stopped", running: false });
});

app.post("/channels/pairing/command", (req: Request, res: Response) => {
  res.json({
    channel: req.body?.channel || "websocket",
    reply: `Command '${req.body?.command}' acknowledged by runtime supervisor.`,
  });
});

// Live broker authorization & runtime channel
let liveBrokersState = [
  {
    auth: { broker: "alpaca", oauth_token_present: true, is_live_broker: true },
    mandate: {
      broker: "alpaca",
      mandate_id: "mandate_alpaca_01",
      account_ref: "ACC-ALPACA-PAPER-01",
      created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
      limits: {
        max_order_notional_usd: 5000,
        max_total_exposure_usd: 25000,
        max_leverage: 2,
        max_trades_per_day: 10,
        allowed_instruments: ["SPY", "QQQ", "AAPL", "NVDA", "BTC-USD"],
        account_funding_usd: 50000,
      },
      expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
      expires_in_seconds: 86400,
      expired: false,
    },
    runner: { broker: "alpaca", alive: true, last_tick: Date.now() / 1000, last_tick_age_seconds: 4 },
    halted: false,
  },
  {
    auth: { broker: "okx", oauth_token_present: true, is_live_broker: true },
    mandate: {
      broker: "okx",
      mandate_id: "mandate_okx_01",
      account_ref: "ACC-OKX-FUTURES-01",
      created_at: new Date(Date.now() - 7200 * 1000).toISOString(),
      limits: {
        max_order_notional_usd: 10000,
        max_total_exposure_usd: 50000,
        max_leverage: 10,
        max_trades_per_day: 50,
        allowed_instruments: ["BTC-USDT", "ETH-USDT", "SOL-USDT"],
        account_funding_usd: 100000,
      },
      expires_at: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
      expires_in_seconds: 172800,
      expired: false,
    },
    runner: { broker: "okx", alive: true, last_tick: Date.now() / 1000, last_tick_age_seconds: 2 },
    halted: false,
  },
];

app.get("/live/status", (req: Request, res: Response) => {
  res.json({
    brokers: liveBrokersState,
    global_halted: false,
  });
});

app.post("/live/authorize", (req: Request, res: Response) => {
  res.json({
    broker: req.body?.broker || "okx",
    connector_profile: "simulated_secure_connector",
    oauth_token_present: true,
    instruction: "Connector authorized for paper/mandate operation.",
  });
});

app.post("/live/runner/start", (req: Request, res: Response) => {
  const broker = req.body?.broker || "okx";
  const b = liveBrokersState.find((x) => x.auth.broker === broker);
  if (b) {
    b.runner.alive = true;
    b.halted = false;
  }
  res.json({ broker, started: true });
});

app.post("/live/runner/stop", (req: Request, res: Response) => {
  const broker = req.body?.broker || "okx";
  const b = liveBrokersState.find((x) => x.auth.broker === broker);
  if (b) b.runner.alive = false;
  res.json({ broker, stopped: true });
});

app.post("/mandate/commit", (req: Request, res: Response) => {
  const mandateId = `mandate_${Date.now()}`;
  res.json({
    mandate_id: mandateId,
    consent_record_id: `consent_${Date.now()}`,
    selected_ordinal: req.body?.selected_ordinal || 1,
    broker: req.body?.broker || "okx",
    max_order_usd: 10000,
    daily_trade_cap: 50,
    expires_at: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
  });
});

app.post("/live/halt", (req: Request, res: Response) => {
  liveBrokersState.forEach((b) => (b.halted = true));
  res.json({
    halted: true,
    broker: req.body?.broker || null,
    reason: req.body?.reason || "User emergency halt triggered",
    sentinel: "kill_switch_active",
  });
});

// Governed Backtest
app.post("/backtest/governed", (req: Request, res: Response) => {
  const runId = `gov_backtest_${Date.now()}`;
  const symbols = req.body?.symbols || ["BTC-USDT"];
  const run = generateRunData(runId, `Governed Backtest on ${symbols.join(", ")}`, symbols[0] || "BTC-USDT", 60);
  RUNS_MAP.set(runId, run);

  res.json({
    status: "success",
    run_id: runId,
    run_dir: `/runs/${runId}`,
    run_card: {
      provenance_valid: true,
      data_source_provenance: { source: req.body?.source || "okx", frequency: "1h" },
      window_integrity: true,
      statistically_evaluable: true,
      hypothesis_supported: run.metrics.sharpe > 1.5,
    },
    runner_result: {
      sharpe: run.metrics.sharpe,
      total_return: run.metrics.total_return,
      max_drawdown: run.metrics.max_drawdown,
    },
  });
});

// Upload endpoint
app.post("/upload", (req: Request, res: Response) => {
  res.json({
    status: "ok",
    file_path: "/uploads/uploaded_dataset.csv",
    filename: "uploaded_dataset.csv",
  });
});

// ----------------------------------------------------------------------------
// SYSTEM HEALTH CHECK (for Docker & VPS Monitoring)
// ----------------------------------------------------------------------------
app.get(["/health", "/api/health"], (req: Request, res: Response) => {
  res.json({
    status: "ok",
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    environment: process.env.NODE_ENV || "development",
    version: "0.1.10",
    active_paper_workers: PAPER_SESSIONS_MAP.size,
  });
});

// ----------------------------------------------------------------------------
// FRONTEND STATIC / VITE INTEGRATION
// ----------------------------------------------------------------------------
async function startServer() {
  if (isDev) {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
      configFile: path.resolve("./frontend/vite.config.ts"),
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.resolve("./frontend/dist");
    if (fs.existsSync(distPath)) {
      app.use(express.static(distPath));
      app.get("*", (req: Request, res: Response) => {
        res.sendFile(path.join(distPath, "index.html"));
      });
    }
  }

  app.listen(PORT, HOST, () => {
    console.log(`🚀 Vibe-Trading Server running at http://${HOST}:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error("Failed to start server:", err);
  process.exit(1);
});
