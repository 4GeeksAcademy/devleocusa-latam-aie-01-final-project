import Link from "next/link";

export default function OperacionesPage() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-2xl font-bold text-slate-900">Operaciones</h1>
      <p className="mt-2 text-sm text-slate-600">
        Accede a los módulos operativos disponibles para inventario, proveedores e incidencias.
      </p>
      <div className="mt-6 flex flex-wrap gap-2">
        <Link
          href="/operaciones/inventario"
          className="inline-flex rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700"
        >
          Inventario operativo
        </Link>
        <Link
          href="/operaciones/proveedores"
          className="inline-flex rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700"
        >
          Ir a directorio de proveedores
        </Link>
        <Link
          href="/operaciones/incidencias"
          className="inline-flex rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700"
        >
          Ir a gestion de incidencias
        </Link>
        <Link
          href="/reporting"
          className="inline-flex rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700"
        >
          Reporting ejecutivo
        </Link>
      </div>
    </section>
  );
}
