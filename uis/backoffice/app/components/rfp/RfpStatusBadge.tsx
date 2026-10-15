import type { RFPStatus } from "../../../services/rfpApi";
import { RFP_STATUS_LABELS } from "../../../services/rfpApi";

const STATUS_STYLES: Record<RFPStatus, string> = {
  analizando: "bg-amber-100 text-amber-800",
  analisis_completo: "bg-emerald-100 text-emerald-800",
  descartado: "bg-rose-100 text-rose-800",
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
