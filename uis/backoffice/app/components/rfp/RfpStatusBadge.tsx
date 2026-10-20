import type { RFPStatus } from "../../../services/rfpApi";
import { RFP_STATUS_LABELS } from "../../../services/rfpApi";

const STATUS_STYLES: Record<RFPStatus, string> = {
  analizando: "bg-amber-100 text-amber-800",
  analisis_completo: "bg-emerald-100 text-emerald-800",
  descartado: "bg-rose-100 text-rose-800",
  generando_borrador: "bg-blue-100 text-blue-800",
  "en_evaluación": "bg-violet-100 text-violet-800",
  needs_human_review: "bg-orange-100 text-orange-900",
  "esperando_aprobación": "bg-indigo-100 text-indigo-900",
  terminado: "bg-emerald-100 text-emerald-900",
};

export default function RfpStatusBadge({ status }: { status: RFPStatus }) {
  const label = RFP_STATUS_LABELS[status] ?? status;
  const style = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${style}`}
    >
      {status === "analizando" && (
        <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
      )}
      {label}
    </span>
  );
}
