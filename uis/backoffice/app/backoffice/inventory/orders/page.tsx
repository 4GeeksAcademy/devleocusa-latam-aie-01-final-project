"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Alert } from "@/app/components/ui/Alert";
import { Spinner } from "@/app/components/ui/Spinner";
import {
  listOrders,
  type OrderHistoryItem,
  InventoryApiError,
} from "@/lib/inventory";

/** Format an ISO-8601 string to a human-readable local datetime. */
function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("es-ES", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Truncate a UUID for display. */
function shortUuid(uuid: string): string {
  if (uuid.length <= 12) return uuid;
  return `${uuid.slice(0, 6)}…${uuid.slice(-4)}`;
}

export default function OrdersHistoryPage() {
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listOrders();
      setOrders(data);
    } catch (err) {
      const message =
        err instanceof InventoryApiError
          ? err.message
          : "No se pudo cargar el historial de órdenes.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  // ── Loading state ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Spinner label="Cargando historial…" size="lg" />
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="mx-auto max-w-lg space-y-4 py-10">
        <Alert variant="error">{error}</Alert>
        <button
          type="button"
          onClick={fetchOrders}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
        >
          Reintentar
        </button>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 py-6">
      {/* ── Cabecera ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <Link
            href="/backoffice/inventory/products"
            className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700"
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
                d="M15.75 19.5 8.25 12l7.5-7.5"
              />
            </svg>
            Volver a productos
          </Link>
          <h1 className="mt-2 text-xl font-bold text-slate-900">
            Historial de Órdenes
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Registro completo de entradas y salidas de inventario.
          </p>
        </div>

        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {orders.length} registros
        </span>
      </div>

      {/* ── Tabla vacía ──────────────────────────────────────────── */}
      {orders.length === 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center">
          <p className="text-sm text-slate-500">
            No hay movimientos de inventario registrados todavía.
          </p>
        </div>
      )}

      {/* ── Tabla ────────────────────────────────────────────────── */}
      {orders.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">
                    Producto
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">
                    Tipo
                  </th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-600">
                    Cantidad
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">
                    Operario
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">
                    Fecha
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {orders.map((order) => (
                  <tr
                    key={`${order.order_type}-${order.id}`}
                    className="transition hover:bg-slate-50"
                  >
                    {/* Producto */}
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="font-medium text-slate-900">
                        {order.sku_name}
                      </div>
                      <div className="text-xs text-slate-500">
                        {order.sku_code}
                      </div>
                    </td>

                    {/* Tipo de orden */}
                    <td className="whitespace-nowrap px-4 py-3">
                      {order.order_type === "inbound" ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                          <svg
                            className="h-3 w-3"
                            fill="none"
                            viewBox="0 0 24 24"
                            strokeWidth={2}
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="m4.5 15.75 7.5-7.5 7.5 7.5"
                            />
                          </svg>
                          Entrada
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-700">
                          <svg
                            className="h-3 w-3"
                            fill="none"
                            viewBox="0 0 24 24"
                            strokeWidth={2}
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="m19.5 8.25-7.5 7.5-7.5-7.5"
                            />
                          </svg>
                          Salida
                        </span>
                      )}
                    </td>

                    {/* Cantidad */}
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      <span
                        className={
                          order.order_type === "inbound"
                            ? "font-semibold text-emerald-600"
                            : "font-semibold text-red-600"
                        }
                      >
                        {order.order_type === "inbound" ? "+" : "-"}
                        {order.quantity}
                      </span>
                    </td>

                    {/* Operario */}
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-500">
                      <span title={order.user_uuid}>
                        {shortUuid(order.user_uuid)}
                      </span>
                    </td>

                    {/* Fecha */}
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                      {formatDate(order.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}