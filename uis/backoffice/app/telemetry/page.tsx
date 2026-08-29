"use client";

import { useEffect, useMemo, useState } from "react";

// ─── Types ───────────────────────────────────────────────────────────────

type ReportPeriod = {
  from: string;
  to: string;
};

type DayCount = {
  date: string;
  count: number;
};

type ErrorByType = {
  event_type: string;
  total: number;
  error_count: number;
  error_rate_pct: number;
};

type ReportData = {
  period: ReportPeriod;
  metrics: {
    events_per_day: DayCount[];
    error_rate_by_type: ErrorByType[];
  };
};

// ─── Helpers ─────────────────────────────────────────────────────────────

function fmtISO(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("es-ES", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("es-ES", {
    timeZone: "UTC",
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function pctWidth(pct: number): string {
  // Clamp to 5% minimum so even 0% bars are visible
  const clamped = Math.max(pct, 5);
  return `${Math.min(clamped, 100)}%`;
}

// ─── Components ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* period skeleton */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="h-4 w-24 bg-slate-200 rounded mb-3" />
        <div className="h-5 w-72 bg-slate-200 rounded" />
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="h-4 w-32 bg-slate-200 rounded mb-4" />
          <div className="space-y-2">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="h-4 w-full bg-slate-200 rounded" />
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="h-4 w-36 bg-slate-200 rounded mb-4" />
          <div className="space-y-2">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="h-4 w-full bg-slate-200 rounded" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      className="rounded-xl border border-red-300 bg-red-50 p-6 text-center"
      role="alert"
    >
      <span className="text-3xl" aria-hidden>⚠</span>
      <p className="mt-2 text-sm font-medium text-red-800">
        No se pudieron cargar los datos de telemetría
      </p>
      <p className="mt-1 text-xs text-red-600">{message}</p>
    </div>
  );
}

// ─── Main Dashboard ──────────────────────────────────────────────────────

export default function TelemetryPage() {
  const [data, setData] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const apiBase =
      (
        process.env as Record<string, string | undefined>
      ).NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

    let cancelled = false;

    setLoading(true);
    setError(null);

    fetch(`${apiBase}/telemetry/report`)
      .then<ReportData>((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status} — ${res.statusText}`);
        }
        return res.json();
      })
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : "Error desconocido";
          setError(msg);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // ── Derived data ────────────────────────────────────────────────────

  const maxDayCount = useMemo(
    () => Math.max(...(data?.metrics.events_per_day.map((d) => d.count) ?? [0]), 1),
    [data],
  );

  const sortedErrors = useMemo(
    () =>
      (data?.metrics.error_rate_by_type ?? []).sort(
        (a, b) => b.error_rate_pct - a.error_rate_pct,
      ),
    [data],
  );

  // ── Render ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
            TrackFlow Tech
          </p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">
            Radar de Telemetría
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Monitor técnico del sistema — salud de endpoints y servicios
          </p>
        </header>
        <Skeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-5xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
            TrackFlow Tech
          </p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">
            Radar de Telemetría
          </h1>
        </header>
        <ErrorBanner message={error} />
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="mx-auto max-w-5xl">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
          TrackFlow Tech
        </p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">
          Radar de Telemetría
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Monitor técnico del sistema — salud de endpoints y servicios
        </p>
      </header>

      {/* ── Period Banner ───────────────────────────────────────────── */}
      <section className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">
          Ventana evaluada
        </p>
        <p className="mt-2 text-base font-medium text-slate-900">
          {fmtISO(data.period.from)} &rarr; {fmtISO(data.period.to)}{" "}
          <span className="text-xs text-slate-400">UTC</span>
        </p>
      </section>

      {/* ── Grid: Events per day + Error rate by type ───────────────── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* ── Events per day ────────────────────────────────────────── */}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-semibold text-slate-900">
            Eventos por día
          </h2>
          <p className="mb-4 text-xs text-slate-400">
            Volumen de telemetría registrada
          </p>

          <div className="space-y-1">
            {/* Header row */}
            <div className="flex items-center gap-3 border-b border-slate-100 pb-1 text-xs font-medium text-slate-500">
              <span className="w-28 shrink-0">Fecha</span>
              <span className="w-12 shrink-0 text-right">Vol.</span>
              <span className="flex-1" />
            </div>

            {data.metrics.events_per_day.map((day) => {
              const w = (day.count / maxDayCount) * 100;
              return (
                <div
                  key={day.date}
                  className="flex items-center gap-3 py-1 text-sm"
                >
                  <span className="w-28 shrink-0 font-mono text-xs text-slate-600">
                    {fmtDate(day.date)}
                  </span>
                  <span className="w-12 shrink-0 text-right font-mono font-bold text-slate-900 tabular-nums">
                    {day.count}
                  </span>
                  <div className="flex-1">
                    <div
                      className="h-5 rounded-r bg-cyan-500"
                      style={{ width: `${w}%` }}
                      title={`${day.count} eventos`}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* ── Error rate by type ────────────────────────────────────── */}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-semibold text-slate-900">
            Tasa de error por tipo
          </h2>
          <p className="mb-4 text-xs text-slate-400">
            Porcentaje de eventos con severidad <code>error</code>
          </p>

          <div className="space-y-1">
            {/* Header row */}
            <div className="flex items-center gap-3 border-b border-slate-100 pb-1 text-xs font-medium text-slate-500">
              <span className="w-28 shrink-0">Tipo</span>
              <span className="w-10 shrink-0 text-right">%</span>
              <span className="flex-1" />
            </div>

            {sortedErrors.map((e) => (
              <div
                key={e.event_type}
                className="flex items-center gap-3 py-1 text-sm"
              >
                <span className="w-28 shrink-0 truncate font-mono text-xs text-slate-700">
                  {e.event_type}
                </span>
                <span className="w-10 shrink-0 text-right font-mono text-xs font-bold tabular-nums text-slate-900">
                  {e.error_rate_pct.toFixed(0)}
                </span>
                <div className="flex-1">
                  <div
                    className={`h-5 rounded-r ${
                      e.error_rate_pct >= 80
                        ? "bg-red-500"
                        : e.error_rate_pct >= 50
                          ? "bg-amber-400"
                          : "bg-emerald-400"
                    }`}
                    style={{ width: pctWidth(e.error_rate_pct) }}
                    title={`${e.event_type}: ${e.error_rate_pct}% error (${e.error_count}/${e.total})`}
                  />
                </div>
                <div className="w-16 shrink-0 text-right">
                  <span className="text-xs text-slate-400 tabular-nums">
                    {e.error_count}/{e.total}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}