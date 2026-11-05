"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Spinner } from "../ui/Spinner";
import {
  Incident,
  IncidentBranch,
  IncidentOrigin,
  IncidentStatus,
  listIncidents,
  patchIncidentStatus,
} from "../../../services/incidentsApi";
import {
  getIncidentCategoryLabel,
  getIncidentOriginLabel,
  getIncidentStatusLabel,
} from "../../../lib/incidentsMappings";

type ToastKind = "success" | "error";

interface IncidentsListPanelProps {
  refreshToken: number;
  onChanged: () => void;
  onNotify: (kind: ToastKind, message: string) => void;
}

const statusOptions: IncidentStatus[] = ["open", "in_progress", "resolved", "discarded"];
const originOptions: IncidentOrigin[] = ["customer", "branch", "internal"];
const branchOptions: IncidentBranch[] = ["Los Ángeles", "Zaragoza", "Central"];

/**
 * Estados que el backend considera terminales: no admiten ninguna transición.
 * Una vez que una incidencia queda "resolved" o "discarded", el estado es fijo.
 */
const TERMINAL_STATUSES: ReadonlySet<IncidentStatus> = new Set(["resolved", "discarded"]);

/** Transiciones permitidas por el backend (espejo de ALLOWED_STATUS_TRANSITIONS). */
const ALLOWED_TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  open: ["open", "in_progress", "discarded"],
  in_progress: ["in_progress", "resolved", "discarded"],
  resolved: [],
  discarded: [],
};

const TERMINAL_BADGE_CLASSES: Record<IncidentStatus, string> = {
  open: "",
  in_progress: "",
  resolved: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  discarded: "bg-rose-100 text-rose-900 ring-rose-200",
};

export function IncidentsListPanel({ refreshToken, onChanged, onNotify }: IncidentsListPanelProps) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<IncidentStatus | "">("");
  const [originFilter, setOriginFilter] = useState<IncidentOrigin | "">("");
  const [branchFilter, setBranchFilter] = useState<IncidentBranch | "">("");
  const [pendingStatusById, setPendingStatusById] = useState<Record<string, boolean>>({});

  const activeFilters = useMemo(
    () => ({
      status: statusFilter || undefined,
      origin: originFilter || undefined,
      branch: branchFilter || undefined,
    }),
    [branchFilter, originFilter, statusFilter],
  );

  const loadIncidents = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const data = await listIncidents(activeFilters);
      setIncidents(data);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "No se pudo cargar el listado de incidencias.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [activeFilters]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadIncidents();
  }, [loadIncidents, refreshToken]);

  const handleStatusChange = async (incidentId: string, nextStatus: IncidentStatus) => {
    const previousItems = incidents;

    setPendingStatusById((prev) => ({ ...prev, [incidentId]: true }));
    setIncidents((prev) =>
      prev.map((item) => (item.id === incidentId ? { ...item, status: nextStatus } : item)),
    );

    try {
      const updated = await patchIncidentStatus(incidentId, nextStatus);
      setIncidents((prev) => prev.map((item) => (item.id === incidentId ? updated : item)));
      onChanged();
      onNotify("success", "Estado actualizado correctamente.");
    } catch (error) {
      setIncidents(previousItems);
      const message = error instanceof Error ? error.message : "No se pudo actualizar el estado.";
      onNotify("error", message);
    } finally {
      setPendingStatusById((prev) => {
        const next = { ...prev };
        delete next[incidentId];
        return next;
      });
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">Listado</p>
          <h2 className="mt-2 text-2xl font-bold text-slate-900">Panel de incidencias</h2>
          <p className="mt-2 text-sm text-slate-600">Filtra y actualiza estados desde esta vista operativa.</p>
        </div>
      </header>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
          Estado
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as IncidentStatus | "")}
            className="rounded-lg border border-slate-300 px-3 py-2"
          >
            <option value="">Todos</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {getIncidentStatusLabel(status)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
          Origen
          <select
            value={originFilter}
            onChange={(event) => setOriginFilter(event.target.value as IncidentOrigin | "")}
            className="rounded-lg border border-slate-300 px-3 py-2"
          >
            <option value="">Todos</option>
            {originOptions.map((origin) => (
              <option key={origin} value={origin}>
                {getIncidentOriginLabel(origin)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
          Sede
          <select
            value={branchFilter}
            onChange={(event) => setBranchFilter(event.target.value as IncidentBranch | "")}
            className="rounded-lg border border-slate-300 px-3 py-2"
          >
            <option value="">Todas</option>
            {branchOptions.map((branch) => (
              <option key={branch} value={branch}>
                {branch}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-5">
        {isLoading ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center">
            <Spinner size="md" label="Cargando incidencias" />
          </div>
        ) : null}

        {!isLoading && error ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-4">
            <p className="text-sm text-rose-700">{error}</p>
            <button
              type="button"
              onClick={() => void loadIncidents()}
              className="mt-3 rounded-lg border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-100"
            >
              Reintentar
            </button>
          </div>
        ) : null}

        {!isLoading && !error && incidents.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center">
            <svg className="mx-auto h-8 w-8 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5h18v11.25A2.25 2.25 0 0 1 18.75 21h-13.5A2.25 2.25 0 0 1 3 18.75V7.5Zm0 0 2.25-4.5h13.5L21 7.5m-18 0h5.25l1.5 3h4.5l1.5-3H21" />
            </svg>
            <h3 className="mt-3 text-lg font-semibold text-slate-800">No hay incidencias que coincidan con estos filtros</h3>
            <p className="mt-2 text-sm text-slate-600">Ajusta los filtros o registra una nueva incidencia.</p>
          </div>
        ) : null}

        {!isLoading && !error && incidents.length > 0 ? (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-full border-collapse text-left text-sm">
              <caption className="sr-only">Listado operativo de incidencias</caption>
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-[0.08em] text-slate-500">
                  <th className="px-3 py-3 font-semibold">Título</th>
                  <th className="px-3 py-3 font-semibold">Categoría</th>
                  <th className="px-3 py-3 font-semibold">Origen</th>
                  <th className="px-3 py-3 font-semibold">Sede</th>
                  <th className="px-3 py-3 font-semibold">Estado</th>
                  <th className="px-3 py-3 font-semibold">Actualizado</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((incident) => (
                  <tr key={incident.id} className="border-b border-slate-100 last:border-b-0">
                    <td className="px-3 py-3">
                      <p className="font-medium text-slate-900">{incident.title || 'Sin título'}</p>
                      <p className="mt-1 text-xs text-slate-500 line-clamp-2">{incident.description || 'Sin descripción'}</p>
                    </td>
                    <td className="px-3 py-3 text-slate-700">
                      {incident.category ? getIncidentCategoryLabel(incident.category) : "Sin categoría"}
                    </td>
                    <td className="px-3 py-3 text-slate-700">
                      {incident.origin ? getIncidentOriginLabel(incident.origin) : "Sin origen"}
                    </td>
                    <td className="px-3 py-3 text-slate-700">{incident.branch || 'Sin sede'}</td>
                    <td className="px-3 py-3">
                      {TERMINAL_STATUSES.has(incident.status) ? (
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${TERMINAL_BADGE_CLASSES[incident.status]}`}
                        >
                          {getIncidentStatusLabel(incident.status)}
                        </span>
                      ) : (
                        <select
                          value={incident.status}
                          onChange={(event) => void handleStatusChange(incident.id, event.target.value as IncidentStatus)}
                          disabled={Boolean(pendingStatusById[incident.id])}
                          className="rounded-md border border-slate-300 px-2 py-1 text-sm text-slate-800 disabled:opacity-60"
                        >
                          {ALLOWED_TRANSITIONS[incident.status].map((option) => (
                            <option key={option} value={option}>
                              {getIncidentStatusLabel(option)}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-500">
                      {incident.updated_at ? new Date(incident.updated_at).toLocaleString("es-ES") : 'Sin fecha'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}
