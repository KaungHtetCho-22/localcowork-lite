import React, { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { SystemInfoChart } from "./components/SystemInfoChart";
import {
  Brain, Zap, FileText, FolderOpen, Shield,
  ChevronDown, ChevronRight, CheckCircle, XCircle,
  Loader2, RefreshCw, Activity, Terminal, AlertTriangle
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

type ToolCallEvent = {
  type: "tool_call";
  tool: string;
  arguments: Record<string, unknown>;
};
type ToolResultEvent = {
  type: "tool_result";
  tool: string;
  success: boolean;
  result: unknown;
  error?: string;
  latency_ms: number;
};
type ToolConfirmEvent = {
  type: "tool_confirm";
  tool: string;
  arguments: Record<string, unknown>;
  tool_call_id: string;
  risk: "safe" | "write" | "destructive";
};
type TextDeltaEvent = { type: "text_delta"; content: string };
type DoneEvent     = { type: "done" };
type ErrorEvent    = { type: "error"; message: string };

type AgentEvent =
  | ToolCallEvent
  | ToolResultEvent
  | ToolConfirmEvent
  | TextDeltaEvent
  | DoneEvent
  | ErrorEvent;

type ToolTrace = {
  tool: string;
  server: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  success?: boolean;
  error?: string;
  latency_ms?: number;
  pending: boolean;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  traces: ToolTrace[];
  streaming: boolean;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const SESSION_ID = crypto.randomUUID();
const WS_URL = `ws://localhost:8000/ws/chat/${SESSION_ID}`;

function serverColor(server: string) {
  const map: Record<string, string> = {
    knowledge:  "#6ee7b7",
    filesystem: "#93c5fd",
    document:   "#fcd34d",
    audit:      "#c4b5fd",
    system:     "#f9a8d4",
    google:     "#86efac",
  };
  return map[server] || "#94a3b8";
}

function serverIcon(server: string) {
  const map: Record<string, React.ReactNode> = {
    knowledge:  <Brain size={12} />,
    filesystem: <FolderOpen size={12} />,
    document:   <FileText size={12} />,
    audit:      <Shield size={12} />,
    system:     <Activity size={12} />,
    google:     <Zap size={12} />,
  };
  return map[server] || <Zap size={12} />;
}

function parseServer(toolName: string) {
  return toolName.split(".")[0] || "unknown";
}

// ── ConfirmationDialog ────────────────────────────────────────────────────────

function ConfirmationDialog({
  event,
  onDecide,
}: {
  event: ToolConfirmEvent;
  onDecide: (approved: boolean) => void;
}) {
  const risk = event.risk;

  const riskBorder = {
    safe:        "border-emerald-500/40",
    write:       "border-yellow-500/40",
    destructive: "border-red-500/40",
  }[risk];

  const riskMeta = {
    safe:        { label: "Read-only",    color: "text-emerald-400",  icon: <CheckCircle size={14} /> },
    write:       { label: "Write action", color: "text-yellow-400",   icon: <AlertTriangle size={14} /> },
    destructive: { label: "Destructive",  color: "text-red-400",      icon: <XCircle size={14} /> },
  }[risk];

  const server = parseServer(event.tool);
  const color  = serverColor(server);

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 px-4 backdrop-blur-sm">
      <div className={`bg-[#0d1117] border ${riskBorder} rounded-2xl p-6 max-w-md w-full shadow-2xl`}>

        {/* Risk badge */}
        <div className={`flex items-center gap-2 mb-5 ${riskMeta.color}`}>
          {riskMeta.icon}
          <span className="text-xs font-mono uppercase tracking-widest">
            {riskMeta.label} — confirmation required
          </span>
        </div>

        {/* Tool name */}
        <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">Tool</div>
        <div className="flex items-center gap-2 mb-4">
          <span style={{ color }} className="flex items-center gap-1.5 font-mono text-sm">
            {serverIcon(server)} {server}
          </span>
          <span className="font-mono text-sm text-slate-200">
            .{event.tool.split(".").slice(1).join(".")}
          </span>
        </div>

        {/* Arguments */}
        <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">Arguments</div>
        <pre className="text-[11px] text-slate-300 bg-black/40 rounded-lg p-3 overflow-x-auto mb-6 max-h-40">
          {JSON.stringify(event.arguments, null, 2)}
        </pre>

        {/* Approve / Reject */}
        <div className="flex gap-3">
          <button
            onClick={() => onDecide(true)}
            className="flex-1 py-2.5 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 text-sm font-semibold hover:bg-emerald-500/30 transition-all"
          >
            Approve
          </button>
          <button
            onClick={() => onDecide(false)}
            className="flex-1 py-2.5 rounded-xl bg-red-500/20 border border-red-500/40 text-red-400 text-sm font-semibold hover:bg-red-500/30 transition-all"
          >
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

// ── ToolTraceCard ──────────────────────────────────────────────────────────────

function ToolTraceCard({ trace }: { trace: ToolTrace }) {
  const [open, setOpen] = useState(false);
  const server = parseServer(trace.tool);
  const color  = serverColor(server);

  return (
    <div
      style={{ borderLeft: `2px solid ${color}` }}
      className="bg-[#0d1117] rounded-r-md mb-1 overflow-hidden"
    >
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-white/5 transition-colors"
      >
        {trace.pending ? (
          <Loader2 size={12} className="animate-spin text-slate-400 shrink-0" />
        ) : trace.success ? (
          <CheckCircle size={12} className="text-emerald-400 shrink-0" />
        ) : (
          <XCircle size={12} className="text-red-400 shrink-0" />
        )}
        <span style={{ color }} className="flex items-center gap-1 text-xs font-mono shrink-0">
          {serverIcon(server)} {server}
        </span>
        <span className="text-xs text-slate-300 font-mono truncate flex-1">
          .{trace.tool.split(".").slice(1).join(".")}
        </span>
        {trace.latency_ms !== undefined && (
          <span className="text-[10px] text-slate-500 shrink-0 ml-auto">
            {trace.latency_ms}ms
          </span>
        )}
        {open
          ? <ChevronDown size={11} className="text-slate-500 shrink-0" />
          : <ChevronRight size={11} className="text-slate-500 shrink-0" />
        }
      </button>

      {open && (
        <div className="px-3 pb-2 space-y-1.5">
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Args</div>
            <pre className="text-[11px] text-slate-300 bg-black/40 rounded p-2 overflow-x-auto">
              {JSON.stringify(trace.arguments, null, 2)}
            </pre>
          </div>
          {!trace.pending && (
            <div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                {trace.success ? "Result" : "Error"}
              </div>
              <pre className="text-[11px] text-slate-300 bg-black/40 rounded p-2 overflow-x-auto max-h-32">
                {JSON.stringify(trace.success ? trace.result : trace.error, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── MessageBubble ──────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div className={`max-w-[80%] ${isUser ? "order-2" : "order-1"}`}>

        {!isUser && msg.traces.length > 0 && (
          <div className="mb-2">
            {msg.traces.map((t, i) =>
              t.tool === "system.get_system_info" && t.result && !t.pending ? (
                <SystemInfoChart key={i} data={t.result as any} />
              ) : (
                <ToolTraceCard key={i} trace={t} />
              )
            )}
          </div>
        )}

        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? "bg-[#1a8cff] text-white rounded-tr-sm"
              : "bg-[#161b22] text-slate-200 rounded-tl-sm border border-white/5"
          }`}
        >
          <ReactMarkdown
            components={{
              a: ({ href, children }) => (
                <a
                  href={href}
                  className="text-[#1a8cff] underline hover:text-[#6ee7b7] transition-colors"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {children}
                </a>
              ),
              table: ({ node, ...props }) => (
                <table className="text-xs border-collapse w-full my-2" {...props} />
              ),
              th: ({ node, ...props }) => (
                <th className="border border-white/20 px-2 py-1 text-left text-slate-300 bg-white/5" {...props} />
              ),
              td: ({ node, ...props }) => (
                <td className="border border-white/20 px-2 py-1 text-slate-400" {...props} />
              ),
              ul: ({ node, ...props }) => (
                <ul className="list-disc list-inside space-y-0.5 my-1" {...props} />
              ),
              ol: ({ node, ...props }) => (
                <ol className="list-decimal list-inside space-y-0.5 my-1" {...props} />
              ),
              code: ({ node, ...props }) => (
                <code className="bg-black/40 px-1 rounded text-[#6ee7b7] text-xs" {...props} />
              ),
              strong: ({ node, ...props }) => (
                <strong className="text-white font-semibold" {...props} />
              ),
            }}
          >
            {msg.content}
          </ReactMarkdown>

          {msg.streaming && (
            <span className="inline-block w-1.5 h-4 bg-[#1a8cff] ml-1 animate-pulse rounded-sm" />
          )}
        </div>

      </div>
    </div>
  );
}

// ── StatusBar ─────────────────────────────────────────────────────────────────

function StatusBar({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-2 px-4 py-1.5 bg-[#0d1117] border-b border-white/5 text-xs text-slate-500">
      <div className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`} />
      <span>{connected ? "Agent connected" : "Connecting..."}</span>
      <span className="ml-auto font-mono opacity-50">session:{SESSION_ID.slice(0, 8)}</span>
    </div>
  );
}

// ── Suggestions ───────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  { label: "List Documents folder",         prompt: "List what's in my Documents folder" },
  { label: "Ingest PDFs to knowledge base", prompt: "Ingest all PDFs in ~/Documents/localcowork" },
  { label: "Search knowledge base",         prompt: "Search my knowledge base for 'attention mechanism'" },
  { label: "Show audit trail",              prompt: "Show me the audit trail" },
  { label: "System status",                 prompt: "Show me my system status" },
  { label: "Check Gmail inbox",             prompt: "Check my Gmail inbox" },
  { label: "Google Calendar this week",     prompt: "What's on my Google Calendar this week?" },
  { label: "Find free slots tomorrow",      prompt: "Find free slots on my calendar tomorrow" },
];

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [messages, setMessages]           = useState<Message[]>([]);
  const [input, setInput]                 = useState("");
  const [connected, setConnected]         = useState(false);
  const [busy, setBusy]                   = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ToolConfirmEvent | null>(null);
  const wsRef    = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);

  // ── WebSocket ────────────────────────────────────────────────────────────

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen  = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 3000);
    };

    ws.onmessage = (e) => {
      const event: AgentEvent = JSON.parse(e.data);

      // HITL confirmation — pause agent, show dialog
      if (event.type === "tool_confirm") {
        setPendingConfirm(event as ToolConfirmEvent);
        setBusy(false);
        return;
      }

      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (!last || last.role !== "assistant" || !last.streaming) return prev;

        const updated = { ...last };

        if (event.type === "tool_call") {
          updated.traces = [
            ...updated.traces,
            {
              tool:      event.tool,
              server:    parseServer(event.tool),
              arguments: event.arguments,
              pending:   true,
            },
          ];
        } else if (event.type === "tool_result") {
          updated.traces = updated.traces.map(t =>
            t.tool === event.tool && t.pending
              ? {
                  ...t,
                  pending:    false,
                  success:    event.success,
                  result:     event.result,
                  error:      event.error,
                  latency_ms: event.latency_ms,
                }
              : t
          );
        } else if (event.type === "text_delta") {
          updated.content += event.content;
        } else if (event.type === "done") {
          updated.streaming = false;
          setBusy(false);
        } else if (event.type === "error") {
          updated.content   = `⚠️ ${event.message}`;
          updated.streaming = false;
          setBusy(false);
        }

        return [...prev.slice(0, -1), updated];
      });
    };
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => connect(), 500);
    return () => {
      clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── HITL decision ─────────────────────────────────────────────────────────

  const handleConfirm = (approved: boolean) => {
    if (!pendingConfirm) return;
    wsRef.current?.send(JSON.stringify({
      type:         "confirm",
      tool_call_id: pendingConfirm.tool_call_id,
      approved,
    }));
    setPendingConfirm(null);
    setBusy(true);
  };

  // ── Send ─────────────────────────────────────────────────────────────────

  const send = (text: string) => {
    const msg = text.trim();
    if (!msg || !connected || busy) return;

    setMessages(prev => [
      ...prev,
      { id: crypto.randomUUID(), role: "user",      content: msg, traces: [], streaming: false },
      { id: crypto.randomUUID(), role: "assistant",  content: "",  traces: [], streaming: true  },
    ]);
    setBusy(true);
    wsRef.current?.send(JSON.stringify({ message: msg }));
    setInput("");
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="h-screen bg-[#010409] text-white flex flex-col font-['IBM_Plex_Mono',monospace]">

      {/* HITL confirmation dialog — rendered above everything */}
      {pendingConfirm && (
        <ConfirmationDialog event={pendingConfirm} onDecide={handleConfirm} />
      )}

      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-white/5 bg-[#0d1117]">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#1a8cff] to-[#6ee7b7] flex items-center justify-center">
            <Terminal size={14} className="text-black" />
          </div>
          <span className="text-sm font-bold tracking-tight">
            LocalCowork <span className="text-[#1a8cff]">Lite</span>
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-slate-500 flex-wrap justify-end">
          <span className="flex items-center gap-1.5"><Brain size={11} /> knowledge</span>
          <span className="flex items-center gap-1.5"><FolderOpen size={11} /> filesystem</span>
          <span className="flex items-center gap-1.5"><FileText size={11} /> document</span>
          <span className="flex items-center gap-1.5"><Shield size={11} /> audit</span>
          <span className="flex items-center gap-1.5"><Activity size={11} /> system</span>
          <span className="flex items-center gap-1.5"><Zap size={11} /> google</span>
        </div>
      </div>

      <StatusBar connected={connected} />

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div>
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[#1a8cff]/20 to-[#6ee7b7]/20 flex items-center justify-center mx-auto mb-4 border border-white/10">
                <Activity size={20} className="text-[#6ee7b7]" />
              </div>
              <h2 className="text-lg font-bold text-slate-200 mb-1">On-device agent</h2>
              <p className="text-sm text-slate-500 max-w-sm">
                Files · Documents · Knowledge Base · Gmail · Google Calendar · System Info
                <br />
                <span className="text-[11px] opacity-60">100% local — nothing leaves your machine</span>
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 max-w-lg w-full">
              {SUGGESTIONS.map(s => (
                <button
                  key={s.prompt}
                  onClick={() => send(s.prompt)}
                  className="text-left text-xs text-slate-400 bg-[#0d1117] border border-white/5 rounded-xl px-3 py-2.5 hover:border-[#1a8cff]/40 hover:text-slate-200 transition-all"
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => <MessageBubble key={msg.id} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-white/5 bg-[#0d1117]">
        <div className="flex gap-3 items-end max-w-4xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={!connected || busy}
            rows={1}
            placeholder={connected ? "Ask anything about your files…" : "Connecting to agent…"}
            className="flex-1 bg-[#161b22] border border-white/5 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-[#1a8cff]/50 resize-none disabled:opacity-40 transition-colors"
            style={{ minHeight: "44px", maxHeight: "120px" }}
          />
          <button
            onClick={() => send(input)}
            disabled={!connected || busy || !input.trim()}
            className="w-11 h-11 rounded-xl bg-[#1a8cff] flex items-center justify-center hover:bg-[#1a8cff]/80 disabled:opacity-30 disabled:cursor-not-allowed transition-all shrink-0"
          >
            {busy
              ? <Loader2 size={16} className="animate-spin" />
              : <Zap size={16} />
            }
          </button>
          <button
            title="Reset session"
            onClick={() => {
              setMessages([]);
              fetch("http://localhost:8000/session/reset", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: SESSION_ID }),
              });
            }}
            className="w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center hover:bg-white/10 transition-all shrink-0"
          >
            <RefreshCw size={14} className="text-slate-400" />
          </button>
        </div>
        <p className="text-center text-[10px] text-slate-600 mt-2">
          ⌨ Enter to send · Shift+Enter for newline · 100% local, zero cloud
        </p>
      </div>

    </div>
  );
}