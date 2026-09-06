"use client";

import { useEffect, useMemo, useState } from "react";

// The API currently returns the legacy Spanish contract for three KPIs and
// the English fields added by the executive KPI pipeline for the remaining two.
export interface ReportingData {
  fecha_reporte?: string;
  id_corrida?: string;
  timestamp?: string;
  periodo?: string;
  volumen_envios?: {
    total?: number;
    por_almacen?: Record<string, number>;
  };
  tasa_entrega_tiempo?: {
    porcentaje?: number;
    entregas_on_time?: number;
    entregas_totales?: number;
  };
  operational_cost?: {
    total?: number;
    breakdown?: Record<string, number>;
    currency?: string;
  };
  customer_satisfaction?: {
    score?: number;
    level?: string;
    penalties?: {
      late_deliveries?: number;
      returns?: number;
    };
  };
  devoluciones?: {
    volumen?: number;
    tasa_porcentaje?: number;
  };
}

interface ReportingResponse {
  registros?: ReportingData[];
  total?: number;
}

const DEFAULT_PERIOD = "Período: Último mes";

function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

function formatNumber(value: number | undefined, digits = 0): string {
  if (value === undefined || Number.isNaN(value)) return "N/D";
  return new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function formatDate(value: string | undefined): string {
  if (!value) return DEFAULT_PERIOD;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return DEFAULT_PERIOD;
  return `Período: ${date.toLocaleDateString("es-ES", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  })}`;
}

function clamp(value: number, min = 0, max = 100): number {
  return Math.min(max, Math.max(min, value));
}

function LoadingState() {
  return (
    <div className="mx-auto max-w-7xl animate-pulse space-y-6" aria-busy="true">
      <div className="h-36 rounded-2xl bg-slate-200" />
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="h-64 rounded-2xl bg-slate-200" />
        ))}
      </div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-7xl rounded-2xl border border-amber-200 bg-amber-50 p-8 text-center">
      <p className="text-sm font-semibold text-amber-900">No hay datos de reporting disponibles</p>
      <p className="mt-2 text-sm text-amber-800">{message}</p>
    </div>
  );
}

function CardHeader({ title, period }: { title: string; period: string }) {
  return (
    <div className="mb-6">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 text-xs text-slate-500">{period}</p>
    </div>
  );
}

function MetricCard({
  title,
  period,
  value,
  unit,
  children,
  accent,
}: {
  title: string;
  period: string;
  value: string;
  unit?: string;
  children?: React.ReactNode;
  accent: string;
}) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className={`mb-5 h-1 w-12 rounded-full ${accent}`} aria-hidden="true" />
      <CardHeader title={title} period={period} />
      <div className="flex items-end gap-2">
        <p className="text-4xl font-semibold tracking-tight text-slate-950">{value}</p>
        {unit ? <span className="mb-1 text-sm text-slate-500">{unit}</span> : null}
      </div>
      {children ? <div className="mt-6">{children}</div> : null}
    </article>
  );
}

export default function ReportingPage() {
  const [report, setReport] = useState<ReportingData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();

    async function loadReport() {
      try {
        const response = await fetch(`${getApiBaseUrl()}/reporting/kpis?limit=1`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const payload = (await response.json()) as ReportingResponse | ReportingData;
        const latest: ReportingData | null =
          "registros" in payload ? payload.registros?.[0] ?? null : (payload as ReportingData);
        setReport(latest);
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(requestError instanceof Error ? requestError.message : "Error desconocido");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    void loadReport();
    return () => controller.abort();
  }, []);

  const warehouseEntries = useMemo(() => {
    return Object.entries(report?.volumen_envios?.por_almacen ?? {}).sort(
      ([, first], [, second]) => second - first,
    );
  }, [report]);

  const maxWarehouseVolume = Math.max(...warehouseEntries.map(([, value]) => value), 1);
  const deliveryRate = clamp(report?.tasa_entrega_tiempo?.porcentaje ?? 0);
  const satisfactionScore = clamp(report?.customer_satisfaction?.score ?? 0);
  const costBreakdown = Object.entries(report?.operational_cost?.breakdown ?? {});

  if (loading) return <LoadingState />;
  if (error) return <EmptyState message={`No se pudo cargar el reporte: ${error}`} />;
  if (!report) return <EmptyState message="Ejecuta el pipeline para generar el primer reporte ejecutivo." />;

  const period = report.periodo ? formatDate(report.periodo) : DEFAULT_PERIOD;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="rounded-2xl bg-slate-950 px-6 py-7 text-white shadow-sm sm:px-8">
        <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">TrackFlow Executive Reporting</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight">Resumen de operaciones</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-300">
              Indicadores clave para supervisar el rendimiento de envíos, costes y experiencia del cliente.
            </p>
          </div>
          <div className="text-left md:text-right">
            <p className="text-xs uppercase tracking-[0.12em] text-slate-400">Última actualización</p>
            <p className="mt-1 text-sm font-medium text-white">
              {report.timestamp ? new Date(report.timestamp).toLocaleString("es-ES") : "N/D"}
            </p>
          </div>
        </div>
      </header>

      <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3" aria-label="KPIs ejecutivos">
        <MetricCard
          title="Volumen de envíos por almacén"
          period={period}
          value={formatNumber(report.volumen_envios?.total)}
          unit="envíos"
          accent="bg-cyan-500"
        >
          <div className="space-y-3">
            {warehouseEntries.length > 0 ? warehouseEntries.map(([warehouse, volume]) => (
              <div key={warehouse}>
                <div className="mb-1 flex justify-between text-xs text-slate-600">
                  <span className="capitalize">{warehouse.replaceAll("-", " ")}</span>
                  <span className="font-semibold">{formatNumber(volume)}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-cyan-500" style={{ width: `${(volume / maxWarehouseVolume) * 100}%` }} />
                </div>
              </div>
            )) : <p className="text-sm text-slate-500">Desglose por almacén no disponible.</p>}
          </div>
        </MetricCard>

        <MetricCard
          title="Tasa de entregas a tiempo"
          period={period}
          value={formatNumber(report.tasa_entrega_tiempo?.porcentaje, 1)}
          unit="%"
          accent="bg-emerald-500"
        >
          <div className="h-3 overflow-hidden rounded-full bg-slate-100" aria-label={`${deliveryRate}% de entregas a tiempo`}>
            <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${deliveryRate}%` }} />
          </div>
          <div className="mt-3 flex justify-between text-xs text-slate-500">
            <span>Objetivo operativo</span>
            <span className="font-semibold text-slate-700">{formatNumber(report.tasa_entrega_tiempo?.entregas_on_time)} / {formatNumber(report.tasa_entrega_tiempo?.entregas_totales)}</span>
          </div>
        </MetricCard>

        <MetricCard
          title="Coste operativo"
          period={period}
          value={report.operational_cost?.total === undefined ? "N/D" : formatNumber(report.operational_cost.total, 2)}
          unit={report.operational_cost?.currency ?? ""}
          accent="bg-amber-500"
        >
          <div className="space-y-2">
            {costBreakdown.length > 0 ? costBreakdown.map(([category, amount]) => (
              <div key={category} className="flex items-center justify-between border-b border-slate-100 pb-2 text-xs last:border-0">
                <span className="capitalize text-slate-500">{category.replaceAll("_", " ")}</span>
                <span className="font-semibold text-slate-700">{formatNumber(amount, 2)}</span>
              </div>
            )) : <p className="text-sm text-slate-500">Desglose de costes no disponible.</p>}
          </div>
        </MetricCard>

        <MetricCard
          title="Devoluciones"
          period={period}
          value={formatNumber(report.devoluciones?.volumen)}
          unit="casos"
          accent="bg-rose-500"
        >
          <div className="flex items-center justify-between rounded-xl bg-rose-50 px-4 py-3">
            <span className="text-xs text-rose-700">Tasa sobre envíos</span>
            <span className="text-lg font-semibold text-rose-800">{formatNumber(report.devoluciones?.tasa_porcentaje, 1)}%</span>
          </div>
        </MetricCard>

        <MetricCard
          title="Satisfacción del cliente"
          period={period}
          value={report.customer_satisfaction?.score === undefined ? "N/D" : formatNumber(report.customer_satisfaction.score, 1)}
          unit="/ 100"
          accent="bg-violet-500"
        >
          <div className="flex items-center gap-4">
            <div className="relative h-16 w-16 shrink-0 rounded-full" style={{ background: `conic-gradient(#8b5cf6 ${satisfactionScore}%, #ede9fe 0)` }}>
              <div className="absolute inset-2 flex items-center justify-center rounded-full bg-white text-xs font-semibold text-violet-700">{formatNumber(satisfactionScore, 0)}</div>
            </div>
            <div>
              <p className="text-sm font-semibold capitalize text-slate-800">Nivel {report.customer_satisfaction?.level ?? "no disponible"}</p>
              <p className="mt-1 text-xs text-slate-500">Índice compuesto por entregas tardías y devoluciones.</p>
            </div>
          </div>
        </MetricCard>
      </section>

      <footer className="flex flex-col gap-1 border-t border-slate-200 pt-4 text-xs text-slate-500 sm:flex-row sm:justify-between">
        <span>Reporte generado por TrackFlow ETL</span>
        <span>ID de corrida: {report.id_corrida ?? "N/D"}</span>
      </footer>
    </div>
  );
}
