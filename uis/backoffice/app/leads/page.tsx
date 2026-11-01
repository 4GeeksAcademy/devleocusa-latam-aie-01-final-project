import { LeadValidationPanel } from "../components/LeadValidationPanel";

export default function LeadsPage() {
  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">Comercial</p>
        <h1 className="mt-2 text-2xl font-bold text-slate-900">Gestión de prospectos</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">
          Las solicitudes del sitio web se guardan en el sistema. Consulta sus datos, filtra prospectos y registra el
          estado de seguimiento comercial.
        </p>
      </header>
      <LeadValidationPanel />
    </div>
  );
}
