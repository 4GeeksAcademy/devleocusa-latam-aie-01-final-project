"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import RfpStatusBadge from "../../components/rfp/RfpStatusBadge";
import RfpKeyAspectsCard from "../../components/rfp/RfpKeyAspectsCard";
import {
  departmentLabel,
  getRfpTicket,
  type RFPTicketDetail,
} from "../../../services/rfpApi";

const POLL_MS = 3000;

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="text-sm text-slate-800">{value}</dd>
    </div>
  );
}

export default function RfpTicketDetailPage() {
  const params = useParams<{ id: string }>();
  const ticketId = params?.id;

  const [ticket, setTicket] = useState<RFPTicketDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!ticketId) return;
    try {
      const data = await getRfpTicket(ticketId);
      setTicket(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el ticket.");
    }
  }, [ticketId]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!ticketId) return;
      try {
        const data = await getRfpTicket(ticketId);
        if (cancelled) return;
        setTicket(data);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "No se pudo cargar el ticket.");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [ticketId, refresh]);

  // Poll while the background pipeline is still running.
  useEffect(() => {
    if (!ticket || !["analizando", "generando_borrador", "en_evaluación"].includes(ticket.status)) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [ticket, refresh]);

  if (error) {
    return (
      <div className="mx-auto max-w-4xl">
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </div>
        <Link href="/rfp" className="mt-4 inline-block text-sm text-sky-700 underline">
          ← Volver a la bandeja de RFPs
        </Link>
      </div>
    );
  }

  if (!ticket) {
    return <p className="text-sm text-slate-500">Cargando ticket…</p>;
  }

  const { document: doc, sections } = ticket;

  return (
    <div className="mx-auto max-w-4xl">
      <Link href="/rfp" className="text-sm text-sky-700 underline">
        ← Bandeja de RFPs
      </Link>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900">
          {ticket.original_filename}
        </h1>
        <RfpStatusBadge status={ticket.status} />
      </div>
      <p className="mt-1 text-xs text-slate-500">
        ticket <span className="font-mono">{ticket.id}</span> ·{" "}
        {new Date(ticket.created_at).toLocaleString()}
        {ticket.is_rfp !== null && (
          <>
            {" · "}confianza del clasificador{" "}
            <strong>{Math.round((ticket.classification_confidence ?? 0) * 100)}%</strong>
          </>
        )}
      </p>

      {["analizando", "generando_borrador", "en_evaluación"].includes(ticket.status) && (
        <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {ticket.status === "analizando"
            ? "El flujo analiza la RFP y prepara el handoff por departamento."
            : ticket.status === "generando_borrador"
              ? "Los agentes departamentales están generando borradores."
              : "Los evaluadores revisan legibilidad, pertinencia y cumplimiento."} Esta página se actualiza sola.
        </div>
      )}

      {ticket.classification_reason && (
        <div
          className={`mt-6 rounded-lg border px-4 py-3 text-sm ${
            ticket.status === "descartado"
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : "border-slate-200 bg-slate-50 text-slate-700"
          }`}
        >
          <span className="font-semibold">Clasificación:</span>{" "}
          {ticket.classification_reason}
        </div>
      )}

      {ticket.status === "descartado" && ticket.error_detail && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          <span className="font-semibold">Detalle:</span> {ticket.error_detail}
        </div>
      )}

      {["analisis_completo", "generando_borrador", "en_evaluación", "needs_human_review"].includes(ticket.status) && (
        <>
          {doc && (
            <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="mb-3 text-lg font-semibold text-slate-900">
                📄 Documento detectado
              </h2>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
                <Field label="Título" value={doc.title} />
                <Field label="Organización emisora" value={doc.issuing_organization} />
                <Field label="Referencia RFP" value={doc.rfp_reference} />
                <Field label="Fecha límite de propuesta" value={doc.proposal_due_date} />
                <Field label="Contacto del cliente" value={doc.contact_name} />
                <Field label="Email de contacto" value={doc.contact_email} />
                <Field label="Idioma detectado" value={doc.detected_language} />
                <Field label="Palabras" value={doc.word_count} />
                <Field
                  label="Legibilidad (Flesch-Kincaid)"
                  value={doc.flesch_kincaid_grade}
                />
                <Field label="Gunning Fog" value={doc.gunning_fog_index} />
                <Field label="Coleman-Liau" value={doc.coleman_liau_index} />
                <Field
                  label="Coste estimado de tokens"
                  value={doc.estimated_token_cost}
                />
              </dl>
            </section>
          )}

          {ticket.synthesis_summary && (
            <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="mb-2 text-lg font-semibold text-slate-900">
                🧠 Resumen para Ventas
              </h2>
              <p className="text-sm leading-relaxed text-slate-800">
                {ticket.synthesis_summary}
              </p>
            </section>
          )}

          <section className="mt-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">
              🗂️ Aspectos clave por departamento ({sections.length})
            </h2>
            {sections.length === 0 ? (
              <p className="text-sm text-slate-500">
                El synthesizer no produjo workstreams.
              </p>
            ) : (
              <div className="space-y-4">
                {sections.map((section) => (
                  <article
                    key={section.department}
                    className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
                  >
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-semibold text-slate-900">
                        {departmentLabel(section.department)}
                        {section.key_aspects?.prioridad && (
                          <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase text-slate-600">
                            prioridad {section.key_aspects.prioridad}
                          </span>
                        )}
                      </h3>
                      {section.status === "needs_human_review" ? (
                        <span className="rounded-full bg-orange-100 px-2.5 py-0.5 text-xs font-semibold text-orange-900">revisión humana</span>
                      ) : section.status === "generando_borrador" ? (
                        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-800">generando borrador</span>
                      ) : section.status === "en_evaluación" ? (
                        <span className="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-800">en evaluación</span>
                      ) : section.status === "error" ? (
                        <span className="rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-800">
                          error del worker
                        </span>
                      ) : (
                        <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                          completado
                        </span>
                      )}
                    </div>

                    {section.contact_name && (
                      <p className="mb-3 text-sm text-slate-600">
                        Pedir a{" "}
                        <span className="font-semibold">{section.contact_name}</span>
                        {section.contact_role && ` — ${section.contact_role}`}
                      </p>
                    )}

                    {section.worker_error && (
                      <p className="mb-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                        {section.worker_error}
                      </p>
                    )}

                    <RfpKeyAspectsCard aspects={section.key_aspects} />

                    {section.proposal_draft && (
                      <div className={`mt-4 rounded-lg border p-4 ${section.status === "needs_human_review" ? "border-orange-300 bg-orange-50" : "border-slate-200 bg-slate-50"}`}>
                        {section.status === "needs_human_review" && (
                          <p className="mb-2 font-semibold text-orange-900">Borrador provisional — requiere revisión humana; se agotó el límite de intentos.</p>
                        )}
                        <h4 className="mb-2 font-semibold text-slate-900">Borrador de propuesta · intento {section.iteration_count}</h4>
                        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{section.proposal_draft}</p>
                        {section.evaluation_result && (
                          <div className="mt-3 border-t border-slate-200 pt-3 text-sm">
                            <p className="font-semibold">Evaluación: {section.evaluation_result.overall_pass ? "Aprobada" : "No aprobada"}</p>
                            <ul className="mt-1 list-disc pl-5 text-slate-700">
                              <li>Legibilidad: {section.evaluation_result.readability.pass ? "aprobada" : "requiere cambios"} — {section.evaluation_result.readability.details}</li>
                              <li>Pertinencia: {section.evaluation_result.relevance.pass ? "aprobada" : `faltan ${section.evaluation_result.relevance.missing_aspects.join(", ") || "aspectos"}`}</li>
                              <li>Cumplimiento: {section.evaluation_result.compliance.pass ? "aprobado" : `reglas ${section.evaluation_result.compliance.rule_ids.join(", ")}`}</li>
                            </ul>
                            {!section.evaluation_result.overall_pass && <p className="mt-2 text-rose-800">{section.evaluation_result.feedback_for_generator}</p>}
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          {ticket.handoff_payload && (
            <section className="mt-6 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-xs text-slate-600">
              <span className="font-semibold">
                Handoff hacia la generación de propuesta (Parte 2):
              </span>{" "}
              payload persistido en <code className="font-mono">rfp_tickets.handoff_payload</code>
              {ticket.dispatched_at
                ? ` · despachado el ${new Date(ticket.dispatched_at).toLocaleString()}`
                : " · pendiente de despacho (dispatched_at IS NULL)"}
            </section>
          )}
        </>
      )}
    </div>
  );
}
