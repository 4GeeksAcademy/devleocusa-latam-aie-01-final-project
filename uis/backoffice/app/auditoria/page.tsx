"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, getCurrentUser } from "@/services/authApi";

type AuditEvent = {
  id: string;
  actor_id: string;
  actor_name: string;
  actor_type: string;
  action: string;
  resource_type: string;
  resource_id: string;
  occurred_at: string;
  department: string;
  country?: string | null;
  warehouse_id?: string | null;
  details: Record<string, unknown>;
  event_hash: string;
};

export default function AuditPage() {
  const [role, setRole] = useState("");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [integrity, setIntegrity] = useState<string | null>(null);

  const load = useCallback(async (nextOffset = 0) => {
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({ limit: "50", offset: String(nextOffset) });
      if (action) query.set("action", action);
      if (actor.trim()) query.set("actor", actor.trim());
      const response = await apiFetch(`/audit-log?${query.toString()}`);
      if (!response.ok) throw new Error(response.status === 403 ? "No tienes permiso para consultar este registro." : "No se pudo cargar el registro de auditoría.");
      const payload = (await response.json()) as { items: AuditEvent[] };
      setEvents(payload.items);
      setOffset(nextOffset);
      setHasMore(payload.items.length === 50);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Error al cargar auditoría.");
    } finally {
      setLoading(false);
    }
  }, [action, actor]);

  useEffect(() => {
    let active = true;
    getCurrentUser().then((user) => { if (active) setRole(user.role); }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  useEffect(() => { queueMicrotask(() => { void load(0); }); }, [load]);

  async function verifyIntegrity() {
    setIntegrity(null);
    const response = await apiFetch("/audit-log/integrity");
    if (!response.ok) {
      setIntegrity("La verificación global está disponible solo para Admin.");
      return;
    }
    const result = (await response.json()) as { valid: boolean; checked: number; reason?: string | null };
    setIntegrity(result.valid ? `Cadena íntegra: ${result.checked} eventos verificados.` : `Integridad no válida: ${result.reason ?? "error desconocido"}.`);
  }

  return (
    <section className="mx-auto max-w-7xl space-y-6 p-4">
      <header>
        <p className="text-sm font-semibold uppercase tracking-wide text-cyan-700">Control y cumplimiento</p>
        <h1 className="mt-1 text-3xl font-bold text-slate-900">Registro de auditoría</h1>
        <p className="mt-2 text-slate-600">Eventos de solo lectura, con atribución del actor y cadena de integridad.</p>
      </header>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</p>}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4">
        <label className="grid gap-1 text-sm">Acción
          <select className="rounded-md border border-slate-300 p-2" value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">Todas las acciones</option>
            <option value="inventory.manual_adjustment">Ajuste de inventario</option>
            <option value="return.approved">Devolución aprobada</option>
            <option value="return.rejected">Devolución rechazada</option>
            <option value="carrier.assignment.changed">Asignación de carrier</option>
            <option value="user.updated">Usuario modificado</option>
            <option value="auth.login.succeeded">Inicio de sesión</option>
            <option value="auth.login.failed">Intento de acceso fallido</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm">ID del actor
          <input className="rounded-md border border-slate-300 p-2" value={actor} onChange={(event) => setActor(event.target.value)} placeholder="Filtrar por ID" />
        </label>
        <button className="rounded-md bg-slate-900 px-4 py-2 text-white" onClick={() => void load(0)}>Aplicar filtros</button>
        {role === "admin" && <button className="rounded-md border border-slate-300 px-4 py-2" onClick={() => void verifyIntegrity()}>Verificar integridad</button>}
        {integrity && <p role="status" className="w-full text-sm text-slate-700">{integrity}</p>}
      </div>
      {loading ? <p className="text-slate-600">Cargando eventos…</p> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full min-w-[1050px] text-left text-sm">
            <thead className="bg-slate-50 text-slate-700"><tr><th className="p-3">Fecha</th><th className="p-3">Actor</th><th className="p-3">Acción</th><th className="p-3">Recurso</th><th className="p-3">Departamento</th><th className="p-3">Almacén</th><th className="p-3">Hash</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{events.map((event) => (
              <tr key={event.id}>
                <td className="whitespace-nowrap p-3">{new Date(event.occurred_at).toLocaleString()}</td>
                <td className="p-3">{event.actor_name}<span className="block text-xs text-slate-500">{event.actor_type}: {event.actor_id}</span></td>
                <td className="p-3 font-medium">{event.action}</td>
                <td className="p-3">{event.resource_type}: {event.resource_id}</td>
                <td className="p-3">{event.department}</td>
                <td className="p-3">{event.warehouse_id ? `${event.warehouse_id} · ${event.country}` : "—"}</td>
                <td className="max-w-48 truncate p-3 font-mono text-xs" title={event.event_hash}>{event.event_hash}</td>
              </tr>
            ))}</tbody>
          </table>
          {!events.length && <p className="p-6 text-slate-600">No hay eventos para mostrar.</p>}
          <div className="flex items-center justify-between border-t border-slate-100 p-3">
            <button disabled={offset === 0 || loading} onClick={() => void load(Math.max(0, offset - 50))} className="rounded border px-3 py-2 disabled:opacity-40">Anterior</button>
            <span className="text-xs text-slate-500">Mostrando {events.length} eventos</span>
            <button disabled={!hasMore || loading} onClick={() => void load(offset + 50)} className="rounded border px-3 py-2 disabled:opacity-40">Siguiente</button>
          </div>
        </div>
      )}
    </section>
  );
}
