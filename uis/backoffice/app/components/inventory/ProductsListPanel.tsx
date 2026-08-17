"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Spinner } from "@/app/components/ui/Spinner";
import { Alert } from "@/app/components/ui/Alert";
import {
  listProducts,
  type SKURead,
  InventoryApiError,
} from "@/lib/inventory";

// ─── Umbrales de stock ──────────────────────────────────────────────────
//  CRÍTICO: current_stock < 10   → rojo, requiere atención inmediata
//  BAJO:    current_stock ≥ 10 y < 50 → amarillo, reponer pronto
//  SALUDABLE: current_stock ≥ 50 → verde, stock suficiente
// -------------------------------------------------------------------------

const STOCK_CRITICAL_THRESHOLD = 10;
const STOCK_LOW_THRESHOLD = 50;

type StockLevel = "critical" | "low" | "healthy";

function computeStockLevel(stock: number): StockLevel {
  if (stock < STOCK_CRITICAL_THRESHOLD) return "critical";
  if (stock < STOCK_LOW_THRESHOLD) return "low";
  return "healthy";
}

const stockLevelConfig: Record<
  StockLevel,
  { label: string; dot: string; bg: string; border: string }
> = {
  critical: {
    label: "Crítico",
    dot: "bg-rose-500",
    bg: "bg-rose-50",
    border: "border-rose-200",
  },
  low: {
    label: "Bajo",
    dot: "bg-amber-400",
    bg: "bg-amber-50",
    border: "border-amber-200",
  },
  healthy: {
    label: "Saludable",
    dot: "bg-emerald-500",
    bg: "bg-emerald-50",
    border: "border-emerald-200",
  },
};

function StockBadge({ value }: { value: number }) {
  const level = computeStockLevel(value);
  const config = stockLevelConfig[level];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${config.bg} ${config.border}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${config.dot}`} />
      <span>{value}</span>
      <span className="text-slate-500">·</span>
      <span>{config.label}</span>
    </span>
  );
}

// ─── Componente principal ──────────────────────────────────────────────

export function ProductsListPanel() {
  const [products, setProducts] = useState<SKURead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  const loadProducts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listProducts();
      setProducts(data);
    } catch (err) {
      const message =
        err instanceof InventoryApiError
          ? err.message
          : "No se pudieron cargar los productos del inventario.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  // Filtro por nombre o código SKU
  const filtered = products.filter((p) => {
    if (!searchTerm.trim()) return true;
    const term = searchTerm.toLowerCase();
    return (
      p.name.toLowerCase().includes(term) ||
      p.sku_code.toLowerCase().includes(term)
    );
  });

  // Métricas de resumen
  const totalProducts = products.length;
  const criticalCount = products.filter(
    (p) => computeStockLevel(p.current_stock) === "critical"
  ).length;
  const lowCount = products.filter(
    (p) => computeStockLevel(p.current_stock) === "low"
  ).length;

  // ── Render ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner label="Cargando productos..." size="lg" />
      </div>
    );
  }

  if (error && products.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <Alert variant="error">{error}</Alert>
        <button
          type="button"
          onClick={loadProducts}
          className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
        >
          Reintentar
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Cabecera ──────────────────────────────────────────────── */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
              Inventario
            </p>
            <h1 className="mt-1 text-2xl font-bold text-slate-900">
              Productos / SKU
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Catálogo de productos con stock actual y movimientos.
            </p>
          </div>

          <Link
            href="/backoffice/inventory/entrada"
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-500"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Registrar Entrada
          </Link>
        </div>
      </section>

      {/* ── Tarjetas de resumen ────────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-3">
        <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs uppercase tracking-[0.08em] text-slate-500">
            Total SKU
          </p>
          <p className="mt-2 text-3xl font-bold text-slate-900">{totalProducts}</p>
        </article>

        <article className="rounded-xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
          <p className="text-xs uppercase tracking-[0.08em] text-amber-800">
            Stock bajo / crítico
          </p>
          <p className="mt-2 text-3xl font-bold text-amber-900">
            {lowCount + criticalCount}
          </p>
          <p className="mt-1 text-xs text-amber-700">
            {criticalCount} críticos · {lowCount} bajos
          </p>
        </article>

        <article className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm">
          <p className="text-xs uppercase tracking-[0.08em] text-emerald-800">
            Stock saludable
          </p>
          <p className="mt-2 text-3xl font-bold text-emerald-900">
            {totalProducts - lowCount - criticalCount}
          </p>
        </article>
      </div>

      {/* ── Buscador ───────────────────────────────────────────────── */}
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="relative">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
            />
          </svg>
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Buscar por nombre o código SKU…"
            className="w-full rounded-lg border border-slate-300 py-2 pl-10 pr-4 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>
      </section>

      {/* ── Tabla de productos ─────────────────────────────────────── */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        {filtered.length === 0 ? (
          <div className="py-10 text-center">
            <p className="text-sm text-slate-500">
              {products.length === 0
                ? "No hay productos registrados en el inventario."
                : "Ningún producto coincide con tu búsqueda."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-[0.08em] text-slate-500">
                  <th className="py-3 pr-4">SKU</th>
                  <th className="py-3 pr-4">Producto</th>
                  <th className="py-3 pr-4">Almacén</th>
                  <th className="py-3 pr-4 text-right">Stock Actual</th>
                  <th className="py-3 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((product) => (
                  <tr
                    key={product.id}
                    className="border-b border-slate-100 transition hover:bg-slate-50 last:border-0"
                  >
                    {/* SKU code */}
                    <td className="py-4 pr-4">
                      <span className="font-mono text-xs font-medium text-slate-700">
                        {product.sku_code}
                      </span>
                    </td>

                    {/* Name */}
                    <td className="py-4 pr-4">
                      <p className="font-semibold text-slate-900">
                        {product.name}
                      </p>
                    </td>

                    {/* Warehouse */}
                    <td className="py-4 pr-4">
                      <span className="inline-flex items-center gap-1 text-slate-600">
                        <svg
                          className="h-3.5 w-3.5 text-slate-400"
                          fill="none"
                          viewBox="0 0 24 24"
                          strokeWidth={1.5}
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="m2.25 12 8.954-8.955a1.126 1.126 0 0 1 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25"
                          />
                        </svg>
                        {product.warehouse === "Los Angeles"
                          ? "Los Ángeles"
                          : product.warehouse}
                      </span>
                    </td>

                    {/* Stock badge */}
                    <td className="py-4 pr-4 text-right">
                      <StockBadge value={product.current_stock} />
                    </td>

                    {/* Action buttons */}
                    <td className="py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Link
                          href={`/backoffice/inventory/entrada?sku_id=${product.id}&sku_code=${product.sku_code}&name=${encodeURIComponent(product.name)}`}
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 transition hover:bg-emerald-100"
                        >
                          <svg
                            className="h-3.5 w-3.5"
                            fill="none"
                            viewBox="0 0 24 24"
                            strokeWidth={2}
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="M12 4.5v15m7.5-7.5h-15"
                            />
                          </svg>
                          Registrar Entrada
                        </Link>

                        <Link
                          href={`/backoffice/inventory/salida?sku_id=${product.id}&sku_code=${product.sku_code}&name=${encodeURIComponent(product.name)}`}
                          className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-800 transition hover:bg-rose-100"
                        >
                          <svg
                            className="h-3.5 w-3.5"
                            fill="none"
                            viewBox="0 0 24 24"
                            strokeWidth={2}
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="M5 12h14"
                            />
                          </svg>
                          Registrar Salida
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}