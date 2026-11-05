"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/services/authApi";

interface HomeUser {
  email: string;
  role: string;
  name: string;
}

/* ── Iconos SVG inline ──────────────────────────────── */

function IconCandidaturas() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-7 w-7">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z" />
    </svg>
  );
}

function IconLeads() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-7 w-7">
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 0 4.5 6h7.5a.75.75 0 0 0 .75-.75v-.75m0 0v-.75a.75.75 0 0 0-.75-.75H4.5a.75.75 0 0 0-.75.75v.75Zm0 0H3.75" />
    </svg>
  );
}

function IconRFP() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-7 w-7">
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  );
}

function IconReporting() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-7 w-7">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
    </svg>
  );
}

function IconKnowledge() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-7 w-7">
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 1-.825-.242m9.345-8.334a2.126 2.126 0 0 0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
    </svg>
  );
}

function IconOperaciones() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-7 w-7">
      <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607ZM10.5 7.5v6m3-3h-6" />
    </svg>
  );
}

/* ── Tarjetas ───────────────────────────────────────── */

interface DashboardCard {
  href: string;
  label: string;
  description: string;
  icon: JSX.Element;
  color: string;
  managerOnly?: boolean;
}

const cards: DashboardCard[] = [
  {
    href: "/candidaturas",
    label: "Candidaturas",
    description: "Gestiona procesos de selección y revisa postulaciones.",
    icon: <IconCandidaturas />,
    color: "text-indigo-600 bg-indigo-50",
  },
  {
    href: "/leads",
    label: "Leads",
    description: "Consulta y administra prospectos comerciales.",
    icon: <IconLeads />,
    color: "text-cyan-600 bg-cyan-50",
    managerOnly: true,
  },
  {
    href: "/operaciones/inventario",
    label: "Operaciones",
    description: "Inventario, proveedores e incidencias del día a día.",
    icon: <IconOperaciones />,
    color: "text-emerald-600 bg-emerald-50",
  },
  {
    href: "/rfp",
    label: "Recepción de RFPs",
    description: "Sube solicitudes de propuesta y sigue su análisis.",
    icon: <IconRFP />,
    color: "text-amber-600 bg-amber-50",
  },
  {
    href: "/reporting",
    label: "Reporting ejecutivo",
    description: "KPIs de volumen, entregas, costos y satisfacción.",
    icon: <IconReporting />,
    color: "text-rose-600 bg-rose-50",
  },
  {
    href: "/knowledge",
    label: "Base de conocimiento",
    description: "Consulta documentación del operador logístico.",
    icon: <IconKnowledge />,
    color: "text-violet-600 bg-violet-50",
  },
];

/* ── Página ─────────────────────────────────────────── */

export default function Home() {
  const [user, setUser] = useState<HomeUser | null>(null);

  useEffect(() => {
    apiFetch("/auth/me")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data) return;
        setUser({
          email: data.email ?? "",
          role: data.role ?? "",
          name: data.profile?.name?.trim() || (data.email?.split("@")[0] ?? ""),
        });
      })
      .catch(() => { /* sin sesión — ProtectedRoute redirige */ });
  }, []);

  const visibleCards = cards.filter(
    (card) => !card.managerOnly || user?.role === "manager"
  );

  return (
    <div className="space-y-6">
      {/* Bienvenida */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">Dashboard</p>
        <h1 className="mt-2 text-2xl font-bold text-slate-900">
          Bienvenido{user?.name ? `, ${user.name}` : ""}
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600 sm:text-base">
          Panel central de TrackFlow. Accede rápidamente a las herramientas del sistema.
        </p>
      </section>

      {/* Grid de tarjetas */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {visibleCards.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md hover:border-slate-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-600"
          >
            <div className={`mb-4 inline-flex rounded-xl p-3 ${card.color}`}>
              {card.icon}
            </div>
            <h3 className="text-base font-semibold text-slate-900 group-hover:text-cyan-800 transition-colors">
              {card.label}
            </h3>
            <p className="mt-1.5 text-sm text-slate-600">{card.description}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
