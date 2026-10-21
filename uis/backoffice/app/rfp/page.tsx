"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import RfpStatusBadge from "../components/rfp/RfpStatusBadge";
import {
  listRfpTickets,
  streamRfpTicketEvents,
  uploadRfp,
  type RfpTicketCreatedEvent,
  type RFPTicketSummary,
  type RFPStatus,
} from "../../services/rfpApi";

const FILTERS: Array<{ value: RFPStatus | undefined; label: string }> = [
  { value: undefined, label: "Todos" },
  { value: "analizando", label: "Analizando" },
  { value: "analisis_completo", label: "Análisis completo" },
  { value: "descartado", label: "Descartados" },
];

export default function RfpIntakePage() {
  const router = useRouter();
  const [tickets, setTickets] = useState<RFPTicketSummary[]>([]);
  const [filter, setFilter] = useState<RFPStatus | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [connectionState, setConnectionState] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const [newTicketIds, setNewTicketIds] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const filterRef = useRef(filter);
  const seenTicketIds = useRef(new Set<string>());

  useEffect(() => { filterRef.current = filter; }, [filter]);

  const refresh = useCallback(async () => {
    try {
      const data = await listRfpTickets(filter);
      for (const ticket of data) seenTicketIds.current.add(ticket.id);
      setTickets((current) => mergeTickets(current, data, filter));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar tickets.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await listRfpTickets(filter);
        if (cancelled) return;
        for (const ticket of data) seenTicketIds.current.add(ticket.id);
        setTickets((current) => mergeTickets(current, data, filter));
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Error al cargar tickets.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [filter]);

  // Recover once before the initial connection and before every reconnect.
  // This closes the list-load/stream-subscribe race and covers Redis Pub/Sub gaps.
  useEffect(() => {
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let failures = 0;

    const onTicketCreated = (event: RfpTicketCreatedEvent) => {
      const id = event.ticket_id;
      if (!id || seenTicketIds.current.has(id)) return;
      seenTicketIds.current.add(id);
      const ticket: RFPTicketSummary = {
        id,
        status: "analizando",
        original_filename: `Nueva RFP: ${event.client_name || id}`,
        created_at: event.created_at,
        updated_at: event.created_at,
        classification_reason: null,
        error_detail: null,
      };
      setTickets((current) => mergeTickets(current, [ticket], filterRef.current));
      setNewTicketIds((current) => [id, ...current.filter((item) => item !== id)]);
      setNotice(`Nueva RFP recibida: ${event.client_name || id} — requiere procesamiento.`);
    };

    const connect = async (recover: boolean) => {
      if (stopped) return;
      controller = new AbortController();
      setConnectionState(recover ? "reconnecting" : "connecting");
      try {
        await streamRfpTicketEvents(onTicketCreated, controller.signal, async () => {
          failures = 0;
          setConnectionState("connected");
          // The request is already subscribed. Snapshot now to close the
          // initial-load/reconnect race; SSE frames are consumed immediately
          // after this callback resolves and are deduplicated by ticket id.
          try {
            const recovered = await listRfpTickets(filterRef.current);
            if (stopped) return;
            for (const ticket of recovered) seenTicketIds.current.add(ticket.id);
            setTickets((current) => mergeTickets(current, recovered, filterRef.current));
            setError(null);
          } catch {
            // Continue receiving live events even if the recovery request fails.
          }
        });
        if (!stopped) throw new Error("El stream SSE terminó inesperadamente.");
      } catch {
        if (stopped) return;
        failures += 1;
        setConnectionState("reconnecting");
        const delay = Math.min(1000 * 2 ** (failures - 1), 30000);
        retryTimer = setTimeout(() => void connect(true), delay);
        return;
      }
      if (!stopped) {
        failures = 0;
        setConnectionState("connected");
      }
    };

    void connect(false);
    return () => {
      stopped = true;
      controller?.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, []);

  // Keep the list fresh while any ticket is still being analyzed.
  const hasPending = tickets.some((ticket) => ticket.status === "analizando");
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => void refresh(), 4000);
    return () => clearInterval(timer);
  }, [hasPending, refresh]);

  const handleUpload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setError("Selecciona un archivo PDF.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("El archivo debe tener extensión .pdf.");
      return;
    }

    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const result = await uploadRfp(file);
      setNotice(`Ticket ${result.ticket_id} creado — ${result.detail}`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refresh();
      // Open the detail page right away: the pipeline runs in the background.
      router.push(`/rfp/${result.ticket_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo subir el PDF.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">
          📥 Recepción de RFPs
        </h1>
        <p className="mt-2 text-slate-600">
          Sube el PDF de una propuesta. El flujo agéntico lo convierte a
          Markdown, clasifica si es una RFP real y descompone el trabajo por
          departamento para Ventas.
        </p>
      </div>

      <div className={`mb-4 rounded-lg border px-4 py-2 text-xs ${connectionState === "connected" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`} role="status">
        {connectionState === "connected" ? "Notificaciones en tiempo real conectadas" : connectionState === "reconnecting" ? "Conexión SSE interrumpida; reconectando y recuperando tickets…" : "Conectando notificaciones en tiempo real…"}
      </div>

      <form onSubmit={handleUpload} className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <label
          htmlFor="rfp-pdf"
          className="block text-sm font-semibold text-slate-700"
        >
          Nuevo PDF de RFP
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            id="rfp-pdf"
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="block w-full max-w-md text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-sky-600 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-sky-700"
          />
          <button
            type="submit"
            disabled={uploading}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {uploading ? "Subiendo…" : "Subir y analizar"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Solo PDF · máx. 25 MB · el análisis corre en segundo plano y el ticket
          pasa de «Analizando» a «Análisis completo» o «Descartado».
        </p>
      </form>

      {notice && (
        <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {error && (
        <div className="mb-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map((option) => (
          <button
            key={option.label}
            type="button"
            onClick={() => {
              setLoading(true);
              setFilter(option.value);
            }}
            className={`rounded-full px-3 py-1 text-sm font-medium ${
              filter === option.value
                ? "bg-slate-900 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Cargando tickets…</p>
      ) : tickets.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          No hay tickets con este filtro. Sube un PDF para empezar.
        </p>
      ) : (
        <ul className="space-y-3">
          {tickets.map((ticket) => (
            <li key={ticket.id}>
              <Link
                href={`/rfp/${ticket.id}`}
                className={`block rounded-xl border p-4 shadow-sm transition hover:border-sky-300 hover:shadow ${newTicketIds.includes(ticket.id) ? "border-emerald-400 bg-emerald-50 ring-2 ring-emerald-100" : "border-slate-200 bg-white"}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-slate-800">
                    {ticket.original_filename}
                  </span>
                  <RfpStatusBadge status={ticket.status} />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-4 text-xs text-slate-500">
                  <span>creado {new Date(ticket.created_at).toLocaleString()}</span>
                  {ticket.classification_reason && (
                    <span className="max-w-xl truncate">
                      {ticket.classification_reason}
                    </span>
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function mergeTickets(
  current: RFPTicketSummary[],
  incoming: RFPTicketSummary[],
  activeFilter?: RFPStatus,
): RFPTicketSummary[] {
  const merged = new Map(current.map((ticket) => [ticket.id, ticket]));
  for (const ticket of incoming) {
    if (!activeFilter || ticket.status === activeFilter) merged.set(ticket.id, ticket);
  }
  return [...merged.values()].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}
