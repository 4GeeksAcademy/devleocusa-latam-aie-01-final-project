"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getSessionToken } from "@/services/authApi";

interface ChatMessage {
  message_id: string;
  role: "user" | "assistant";
  text: string;
  status?: string;
  sequence?: number;
}

export default function KnowledgePage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef("");
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const mountedRef = useRef(false);
  const connectSocketRef = useRef<() => void>(() => {});

  const connectSocket = useCallback(() => {
    const token = getSessionToken();
    if (!token) {
      setError("Inicia sesión para abrir el chat.");
      return;
    }
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    const url = new URL(`/chat/ws/${sessionIdRef.current}`, baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("token", token);
    const socket = new WebSocket(url.toString());
    socketRef.current = socket;

    socket.onopen = () => {
      reconnectAttemptRef.current = 0;
      setConnected(true);
      setError(null);
    };
    socket.onmessage = (messageEvent) => {
      try {
        const event = JSON.parse(messageEvent.data) as { event: string; data: Record<string, unknown> };
        const data = event.data;
        if (event.event === "session_snapshot") {
          const restored = (data.messages as ChatMessage[]) || [];
          setMessages(restored);
          setGenerating(restored.some((item) => item.role === "assistant" && item.status === "streaming"));
        } else if (event.event === "user_message") {
          const incoming: ChatMessage = {
            message_id: String(data.message_id), role: "user", text: String(data.text),
          };
          setMessages((current) => current.some((item) => item.message_id === incoming.message_id)
            ? current : [...current, incoming]);
          setGenerating(true);
        } else if (event.event === "token_chunk") {
          const messageId = String(data.message_id);
          const token = String(data.token);
          const sequence = Number(data.sequence || 0);
          setMessages((current) => {
            const index = current.findIndex((item) => item.message_id === messageId);
            if (index < 0) {
              return [...current, { message_id: messageId, role: "assistant", text: token, status: "streaming", sequence }];
            }
            return current.map((item) => item.message_id === messageId
              ? sequence <= (item.sequence || 0) && !data.replace
                ? item
                : { ...item, text: data.replace ? token : item.text + token, status: "streaming", sequence }
              : item);
          });
          setGenerating(true);
        } else if (event.event === "generation_interrupted") {
          const messageId = String(data.message_id);
          setMessages((current) => current.map((item) => item.message_id === messageId
            ? { ...item, status: "interrupted" } : item));
          setGenerating(false);
        } else if (event.event === "generation_completed") {
          const messageId = String(data.message_id);
          setMessages((current) => current.map((item) => item.message_id === messageId
            ? { ...item, status: "completed" } : item));
          setGenerating(false);
        } else if (event.event === "chat_error") {
          setError(String(data.message || "Error de chat."));
          setGenerating(false);
        }
      } catch {
        setError("El servidor envió un evento de chat inválido.");
      }
    };
    socket.onerror = () => setError("No fue posible mantener la conexión del chat.");
    socket.onclose = (event) => {
      setConnected(false);
      if (!mountedRef.current || event.code === 1008) {
        if (event.code === 1008) setError("La sesión del chat no está autorizada; vuelve a iniciar sesión.");
        return;
      }
      const attempt = reconnectAttemptRef.current++;
      const delay = Math.min(1000 * 2 ** attempt, 15000);
      reconnectTimerRef.current = setTimeout(() => connectSocketRef.current(), delay);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connectSocketRef.current = connectSocket;
    sessionIdRef.current = window.localStorage.getItem("trackflow_chat_session_id") || `chat_${crypto.randomUUID()}`;
    window.localStorage.setItem("trackflow_chat_session_id", sessionIdRef.current);
    queueMicrotask(() => connectSocketRef.current());
    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      socketRef.current?.close();
    };
  }, [connectSocket]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || !socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;
    const activeGeneration = generating;
    socketRef.current.send(JSON.stringify({
      event: activeGeneration ? "interrupt_requested" : "user_message",
      data: activeGeneration
        ? { session_id: sessionIdRef.current, new_input: text }
        : { session_id: sessionIdRef.current, text },
    }));
    setQuestion("");
    setError(null);
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">
          📚 Base de Conocimiento TrackFlow
        </h1>
        <p className="mt-2 text-slate-600">
          Consulta la base de conocimiento de TrackFlow en lenguaje natural.
          Recibe respuestas sobre políticas, procedimientos, servicios y más.
        </p>
      </div>

      {/* Question Form */}
      <form onSubmit={handleSubmit} className="mb-8">
        <div className="flex gap-3">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ej: ¿Cuál es la política de devoluciones de TrackFlow?"
            disabled={!connected}
            className="flex-1 rounded-lg border border-slate-300 px-4 py-3 text-slate-900 placeholder:text-slate-400 focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!connected || !question.trim()}
            className="rounded-lg bg-cyan-600 px-6 py-3 font-medium text-white transition hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? (
              <span className="flex items-center gap-2">
                <svg
                  className="h-5 w-5 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Respondiendo...
              </span>
            ) : (
              "Enviar"
            )}
          </button>
        </div>
      </form>

      {/* Error State */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
          <p className="font-medium">⚠️ Error</p>
          <p className="mt-1 text-sm">{error}</p>
        </div>
      )}

      {/* Answer */}
      {messages.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Conversación</h2>
          <div className="space-y-4">
            {messages.map((message) => (
              <div key={message.message_id} className={`rounded-lg p-4 ${message.role === "user" ? "ml-10 bg-cyan-50" : "mr-10 bg-slate-50"}`}>
                <p className="mb-1 text-xs font-semibold uppercase text-slate-500">{message.role === "user" ? "Tú" : "Agente"}</p>
                <p className="whitespace-pre-wrap text-slate-800">{message.text}{message.status === "interrupted" ? <span className="ml-2 text-xs font-semibold text-amber-700">(interrumpido)</span> : null}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {messages.length === 0 && !error && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <p className="text-slate-500">
            Escribe una pregunta sobre las políticas, procedimientos o servicios
            de TrackFlow para recibir una respuesta.
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {[
              "¿Cómo funciona el proceso de devoluciones?",
              "¿Qué transportistas usa TrackFlow en España?",
              "¿Cuáles son los SLAs de entrega?",
              "¿Cómo se calcula el almacenaje?",
            ].map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setQuestion(example)}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-600 transition hover:border-cyan-300 hover:text-cyan-700"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
