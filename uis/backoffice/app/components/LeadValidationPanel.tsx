"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteLead, LeadRecord, LeadStatus, listLeads, updateLeadStatus } from "../../services/leadsApi";

const statusLabels: Record<LeadStatus, string> = {
  new: "Nuevo",
  contacted: "Contactado",
  qualified: "Calificado",
  disqualified: "Descartado",
};

export function LeadValidationPanel() {
  const [leads, setLeads] = useState<LeadRecord[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<LeadStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingStatus, setPendingStatus] = useState<Partial<Record<string, LeadStatus>>>({});

  const loadLeads = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setLeads(await listLeads());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "No se pudieron cargar los prospectos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    listLeads().then((records) => {
      if (active) setLeads(records);
    }).catch((loadError: unknown) => {
      if (active) setError(loadError instanceof Error ? loadError.message : "No se pudieron cargar los prospectos.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const filteredLeads = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return leads.filter((lead) => {
      const matchesStatus = statusFilter === "all" || lead.status === statusFilter;
      const matchesQuery = !normalizedQuery || [lead.companyName, lead.contactPerson, lead.corporateEmail]
        .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
      return matchesStatus && matchesQuery;
    });
  }, [leads, query, statusFilter]);

  const hasPendingChanges = useMemo(() => {
    return Object.entries(pendingStatus).some(([leadId, status]) => {
      const lead = leads.find((item) => item.id === leadId);
      return lead ? status !== undefined && status !== lead.status : false;
    });
  }, [leads, pendingStatus]);

  const handleDraftChange = (lead: LeadRecord, status: LeadStatus) => {
    setPendingStatus((current) => {
      const next = { ...current };
      if (status === lead.status) {
        delete next[lead.id];
      } else {
        next[lead.id] = status;
      }
      return next;
    });
  };

  const handleApplyAll = async () => {
    const entries = Object.entries(pendingStatus).filter(([leadId, status]) => {
      const lead = leads.find((item) => item.id === leadId);
      return lead ? status !== undefined && status !== lead.status : false;
    });
    if (entries.length === 0) return;
    setApplying(true);
    setError("");
    setNotice("");
    try {
      let appliedCount = 0;
      for (const [leadId, status] of entries) {
        if (status === undefined) continue;
        await updateLeadStatus(leadId, status);
        appliedCount += 1;
      }
      setPendingStatus({});
      await loadLeads();
      setNotice(`${appliedCount} cambio(s) aplicado(s). La lista se actualizó.`);
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : "No se pudieron aplicar los cambios.");
    } finally {
      setApplying(false);
    }
  };

  const handleDelete = async (lead: LeadRecord) => {
    if (!window.confirm(`¿Eliminar el prospecto de ${lead.companyName}? Esta acción no se puede deshacer.`)) return;
    setBusyId(lead.id);
    setError("");
    setNotice("");
    try {
      await deleteLead(lead.id);
      setPendingStatus((current) => {
        const next = { ...current };
        delete next[lead.id];
        return next;
      });
      setLeads((current) => current.filter((item) => item.id !== lead.id));
      setNotice("Prospecto eliminado.");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "No se pudo eliminar el prospecto.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Prospectos recibidos</h2>
          <p className="mt-1 text-sm text-slate-600">Consulta solicitudes y registra su avance comercial.</p>
        </div>
        <button type="button" onClick={() => void handleApplyAll()} disabled={!hasPendingChanges || applying || loading}
          className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700 disabled:opacity-60">
          {applying ? "Aplicando…" : "Aplicar cambios"}
        </button>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium text-slate-700">
          Buscar empresa, contacto o email
          <input value={query} onChange={(event) => setQuery(event.target.value)} type="search"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700" />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Filtrar por estado
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as LeadStatus | "all")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700">
            <option value="all">Todos los estados</option>
            {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
      </div>

      {error ? <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
      {notice ? <p role="status" className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}

      {loading ? <p className="mt-6 text-sm text-slate-600" role="status">Cargando prospectos…</p> : null}
      {!loading && !error && filteredLeads.length === 0 ? (
        <p className="mt-6 rounded-lg bg-slate-50 p-5 text-sm text-slate-600">{leads.length ? "No hay prospectos que coincidan con los filtros." : "Aún no se han recibido solicitudes de contacto."}</p>
      ) : null}

      {filteredLeads.length > 0 ? (
        <div className="mt-6 space-y-4">
          {filteredLeads.map((lead) => (
            <article key={lead.id} className="rounded-xl border border-slate-200 p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-slate-900">{lead.companyName}</h3>
                  <p className="text-sm text-slate-700">{lead.contactPerson} · <a className="text-cyan-800 underline" href={`mailto:${lead.corporateEmail}`}>{lead.corporateEmail}</a></p>
                  <p className="mt-1 text-sm text-slate-600">{lead.phone} · {lead.countryOperation} · {lead.monthlyVolume} envíos/mes</p>
                </div>
                <time className="text-xs text-slate-500" dateTime={lead.createdAt}>{new Date(lead.createdAt).toLocaleString()}</time>
              </div>
              <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                <div><dt className="font-medium text-slate-600">Producto</dt><dd className="text-slate-900">{lead.productType}</dd></div>
                <div><dt className="font-medium text-slate-600">Servicios</dt><dd className="text-slate-900">{lead.services.join(", ")}</dd></div>
                <div><dt className="font-medium text-slate-600">Proveedor 3PL</dt><dd className="text-slate-900">{lead.other3pl}</dd></div>
                {lead.website ? <div><dt className="font-medium text-slate-600">Sitio web</dt><dd><a href={lead.website} target="_blank" rel="noreferrer" className="text-cyan-800 underline">{lead.website}</a></dd></div> : null}
                {lead.comments ? <div className="sm:col-span-2"><dt className="font-medium text-slate-600">Comentarios</dt><dd className="whitespace-pre-wrap text-slate-900">{lead.comments}</dd></div> : null}
              </dl>
              <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
                <label className="text-sm font-medium text-slate-700">Estado
                  <select value={pendingStatus[lead.id] ?? lead.status} disabled={applying || busyId === lead.id} onChange={(event) => handleDraftChange(lead, event.target.value as LeadStatus)}
                    className="ml-2 rounded-lg border border-slate-300 px-3 py-2 text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700 disabled:opacity-60">
                    {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <button type="button" disabled={applying || busyId === lead.id} onClick={() => void handleDelete(lead)}
                  className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60">
                  Eliminar
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
