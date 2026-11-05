"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Spinner } from "../ui/Spinner";
import { Alert } from "../ui/Alert";
import {
  listProducts,
  createProduct,
  createInboundOrder,
  createOutboundOrder,
  listOrders,
  type SKURead,
  type SKUCreatePayload,
  type OrderHistoryItem,
  type WarehouseLocation,
  InventoryApiError,
} from "../../../lib/inventory";
import {
  trackSkuCreateAttempt,
  trackSkuCreateSuccess,
  trackSkuCreateFailure,
  trackInboundOrderCreated,
  trackOutboundOrderCreated,
} from "../../../lib/instrumentation";

// ─── Helpers ────────────────────────────────────────────────────────────

type StockLevel = "critical" | "low" | "healthy";

function computeStockLevel(value: number): StockLevel {
  if (value < 10) return "critical";
  if (value < 50) return "low";
  return "healthy";
}

const stockLevelConfig: Record<
  StockLevel,
  { label: string; dot: string; bg: string; border: string }
> = {
  critical: {
    label: "Crítico",
    dot: "bg-rose-400",
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

const WAREHOUSE_OPTIONS: { value: WarehouseLocation; label: string }[] = [
  { value: "Los Angeles", label: "Los Ángeles" },
  { value: "Zaragoza", label: "Zaragoza" },
];

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("es-ES", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** Marca de tiempo para métricas de latencia (envolvente de performance.now). */
function nowMs(): number {
  return performance.now();
}

// ─── Component ──────────────────────────────────────────────────────────

export function InventoryDashboard() {
  // Lists
  const [products, setProducts] = useState<SKURead[]>([]);
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  // Filtro por nombre o código SKU
  const filtered = useMemo(
    () =>
      products.filter((p) => {
        if (!searchTerm.trim()) return true;
        const term = searchTerm.toLowerCase();
        return (
          p.name.toLowerCase().includes(term) ||
          p.sku_code.toLowerCase().includes(term)
        );
      }),
    [products, searchTerm],
  );

  // Métricas de resumen
  const summary = useMemo(() => {
    let crit = 0;
    let low = 0;
    for (const p of products) {
      const level = computeStockLevel(p.current_stock);
      if (level === "critical") crit++;
      else if (level === "low") low++;
    }
    return { total: products.length, critical: crit, low };
  }, [products]);

  // Create product form
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newProduct, setNewProduct] = useState<SKUCreatePayload>({
    name: "",
    sku_code: "",
    warehouse: "Los Angeles",
  });

  // Inbound / outbound forms (tracking by product id)
  const [inboundQty, setInboundQty] = useState<Record<string, string>>({});
  const [outboundQty, setOutboundQty] = useState<Record<string, string>>({});
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  const [notification, setNotification] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);

  // ── Data fetching ────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    try {
      const [productsData, ordersData] = await Promise.all([
        listProducts(),
        listOrders(),
      ]);
      setProducts(productsData);
      setOrders(ordersData);
    } catch (err) {
      const message =
        err instanceof InventoryApiError
          ? err.message
          : "No se pudieron cargar los datos del inventario.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // queueMicrotask deja explícita la frontera asíncrona para el linter
    // (react-hooks/set-state-in-effect); el spinner inicial ya es `loading`.
    queueMicrotask(() => {
      void loadData();
    });
  }, [loadData]);

  // ── Actions ──────────────────────────────────────────────────────────

  const notify = (kind: "success" | "error", message: string) => {
    setNotification({ kind, message });
    setTimeout(() => setNotification(null), 5000);
  };

  const handleCreateProduct = async () => {
    if (!newProduct.name.trim() || !newProduct.sku_code.trim()) {
      notify("error", "El nombre y código SKU son obligatorios.");
      return;
    }

    const startTs = nowMs();
    const skuCode = newProduct.sku_code.trim();
    const warehouse = newProduct.warehouse;

    // Emit sku.create.attempt
    trackSkuCreateAttempt(skuCode, warehouse, newProduct.name.trim().length);

    setActionLoading((prev) => ({ ...prev, create: true }));
    try {
      const created = await createProduct(newProduct);
      const latencyMs = Math.round(nowMs() - startTs);

      notify("success", `Producto "${newProduct.name}" creado correctamente.`);

      // Emit sku.create.success
      trackSkuCreateSuccess(created.id, created.sku_code, warehouse, latencyMs);

      setShowCreateForm(false);
      setNewProduct({ name: "", sku_code: "", warehouse: "Los Angeles" });
      await loadData();
    } catch (err) {
      const inventoryErr = err instanceof InventoryApiError ? err : null;

      // Emit sku.create.failure
      let errorCode: 'duplicate_sku' | 'validation_error' | 'server_error' | 'unauthorized' = 'server_error';
      const status = inventoryErr?.status ?? 0;
      if (status === 400) errorCode = 'validation_error';
      else if (status === 409) errorCode = 'duplicate_sku';
      else if (status === 401) errorCode = 'unauthorized';

      trackSkuCreateFailure(
        skuCode,
        errorCode,
        status,
        inventoryErr?.message ?? '',
      );

      notify(
        "error",
        inventoryErr
          ? inventoryErr.message
          : "No se pudo crear el producto."
      );
    } finally {
      setActionLoading((prev) => ({ ...prev, create: false }));
    }
  };

  const handleInbound = async (skuId: string) => {
    const qty = parseInt(inboundQty[skuId] ?? "", 10);
    if (!qty || qty < 1) {
      notify("error", "Indica una cantidad válida (mayor que 0).");
      return;
    }

    setActionLoading((prev) => ({ ...prev, [`inbound-${skuId}`]: true }));
    const startTs = nowMs();
    try {
      await createInboundOrder({ sku_id: skuId, quantity: qty });
      const latencyMs = Math.round(nowMs() - startTs);

      notify("success", `Entrada registrada: +${qty} unidades.`);
      setInboundQty((prev) => ({ ...prev, [skuId]: "" }));

      // Find the product to get sku_code and stock_after
      const product = products.find((p) => p.id === skuId);
      if (product) {
        trackInboundOrderCreated(
          skuId,
          product.sku_code,
          product.warehouse as 'Los Angeles' | 'Zaragoza',
          qty,
          product.current_stock + qty,
          product.current_stock,
          latencyMs,
        );
      }

      await loadData();
    } catch (err) {
      notify(
        "error",
        err instanceof InventoryApiError
          ? err.message
          : "No se pudo registrar la entrada."
      );
    } finally {
      setActionLoading((prev) => ({ ...prev, [`inbound-${skuId}`]: false }));
    }
  };

  const handleOutbound = async (skuId: string) => {
    const qty = parseInt(outboundQty[skuId] ?? "", 10);
    if (!qty || qty < 1) {
      notify("error", "Indica una cantidad válida (mayor que 0).");
      return;
    }

    setActionLoading((prev) => ({ ...prev, [`outbound-${skuId}`]: true }));
    const startTs = nowMs();
    try {
      await createOutboundOrder({ sku_id: skuId, quantity: qty });
      const latencyMs = Math.round(nowMs() - startTs);

      notify("success", `Salida registrada: -${qty} unidades.`);
      setOutboundQty((prev) => ({ ...prev, [skuId]: "" }));

      // Find the product to get sku_code and stock_after
      const product = products.find((p) => p.id === skuId);
      if (product) {
        const stockAfter = product.current_stock - qty;
        trackOutboundOrderCreated(
          skuId,
          product.sku_code,
          product.warehouse as 'Los Angeles' | 'Zaragoza',
          qty,
          stockAfter >= 0 ? stockAfter : 0,
          product.current_stock,
          latencyMs,
        );
      }

      await loadData();
    } catch (err) {
      notify(
        "error",
        err instanceof InventoryApiError
          ? err.message
          : "No se pudo registrar la salida."
      );
    } finally {
      setActionLoading((prev) => ({ ...prev, [`outbound-${skuId}`]: false }));
    }
  };

  // ── Render ───────────────────────────────────────────────────────────

  if (loading && products.length === 0) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Spinner label="Cargando inventario..." />
      </div>
    );
  }

  if (error && products.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <Alert variant="error">{error}</Alert>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            setError(null);
            void loadData();
          }}
          className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
        >
          Reintentar
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
              Operaciones
            </p>
            <h1 className="mt-1 text-2xl font-bold text-slate-900">
              Inventario / SKUs
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Gestiona productos, entradas y salidas de stock.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateForm((prev) => !prev)}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
          >
            {showCreateForm ? "Cancelar" : "+ Nuevo producto"}
          </button>
        </div>

        {/* Notification toast */}
        {notification && (
          <div
            className={`mt-4 rounded-md border px-4 py-3 text-sm shadow-sm ${
              notification.kind === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                : "border-rose-200 bg-rose-50 text-rose-900"
            }`}
            role="alert"
          >
            {notification.message}
          </div>
        )}
      </section>

      {/* Create product form */}
      {showCreateForm && (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">
            Nuevo producto SKU
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label
                htmlFor="sku-name"
                className="block text-sm font-medium text-slate-700"
              >
                Nombre
              </label>
              <input
                id="sku-name"
                type="text"
                value={newProduct.name}
                onChange={(e) =>
                  setNewProduct((prev) => ({ ...prev, name: e.target.value }))
                }
                placeholder="Ej. Lote de sensores"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              />
            </div>
            <div>
              <label
                htmlFor="sku-code"
                className="block text-sm font-medium text-slate-700"
              >
                Código SKU
              </label>
              <input
                id="sku-code"
                type="text"
                value={newProduct.sku_code}
                onChange={(e) =>
                  setNewProduct((prev) => ({
                    ...prev,
                    sku_code: e.target.value,
                  }))
                }
                placeholder="Ej. WH-LA-001"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              />
            </div>
            <div>
              <label
                htmlFor="sku-warehouse"
                className="block text-sm font-medium text-slate-700"
              >
                Almacén
              </label>
              <select
                id="sku-warehouse"
                value={newProduct.warehouse}
                onChange={(e) =>
                  setNewProduct((prev) => ({
                    ...prev,
                    warehouse: e.target.value as WarehouseLocation,
                  }))
                }
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              >
                {WAREHOUSE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            onClick={handleCreateProduct}
            disabled={actionLoading["create"]}
            className="mt-4 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {actionLoading["create"] ? "Guardando..." : "Guardar producto"}
          </button>
        </section>
      )}

      {/* Summary cards + search + Products table */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        {/* Summary cards */}
        <div className="mb-6 grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Total SKUs
            </p>
            <p className="mt-1 text-2xl font-bold text-slate-900">
              {summary.total}
            </p>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
              Stock bajo / crítico
            </p>
            <p className="mt-1 text-2xl font-bold text-amber-900">
              {summary.critical + summary.low}
            </p>
          </div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
              Stock saludable
            </p>
            <p className="mt-1 text-2xl font-bold text-emerald-900">
              {summary.total - summary.critical - summary.low}
            </p>
          </div>
        </div>

        {/* Search input */}
        <div className="relative mb-4">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-4.35-4.35M11 19a8 8 0 100-16 8 8 0 000 16z"
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

        <h2 className="mb-4 text-lg font-semibold text-slate-900">
          Productos ({filtered.length} de {products.length})
        </h2>

        {products.length === 0 ? (
          <p className="text-sm text-slate-500">
            No hay productos registrados. Crea el primero usando el botón
            superior.
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-slate-500">
            No se encontraron productos que coincidan con{" "}
            <span className="font-semibold">“{searchTerm}”</span>.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="py-3 pr-4">Código SKU</th>
                  <th className="py-3 pr-4">Nombre</th>
                  <th className="py-3 pr-4">Almacén</th>
                  <th className="py-3 pr-4 text-right">Stock actual</th>
                  <th className="py-3 pr-4 text-right">Entrada</th>
                  <th className="py-3 text-right">Salida</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((product) => (
                  <tr
                    key={product.id}
                    className="border-b border-slate-100 last:border-0"
                  >
                    <td className="py-3 pr-4 font-mono text-xs text-slate-700">
                      {product.sku_code}
                    </td>
                    <td className="py-3 pr-4 font-medium text-slate-900">
                      {product.name}
                    </td>
                    <td className="py-3 pr-4 text-slate-600">
                      {product.warehouse}
                    </td>
                    <td className="py-3 pr-4 text-right">
                      <StockBadge value={product.current_stock} />
                    </td>
                    <td className="py-3 pr-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <input
                          type="number"
                          min={1}
                          placeholder="Cant."
                          value={inboundQty[product.id] ?? ""}
                          onChange={(e) =>
                            setInboundQty((prev) => ({
                              ...prev,
                              [product.id]: e.target.value,
                            }))
                          }
                          className="w-20 rounded border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-cyan-500 focus:outline-none"
                        />
                        <button
                          type="button"
                          disabled={
                            actionLoading[`inbound-${product.id}`] ?? false
                          }
                          onClick={() => handleInbound(product.id)}
                          className="rounded bg-emerald-600 px-2 py-1 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {actionLoading[`inbound-${product.id}`]
                            ? "..."
                            : "+"}
                        </button>
                      </div>
                    </td>
                    <td className="py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <input
                          type="number"
                          min={1}
                          placeholder="Cant."
                          value={outboundQty[product.id] ?? ""}
                          onChange={(e) =>
                            setOutboundQty((prev) => ({
                              ...prev,
                              [product.id]: e.target.value,
                            }))
                          }
                          className="w-20 rounded border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-cyan-500 focus:outline-none"
                        />
                        <button
                          type="button"
                          disabled={
                            actionLoading[`outbound-${product.id}`] ?? false
                          }
                          onClick={() => handleOutbound(product.id)}
                          className="rounded bg-rose-600 px-2 py-1 text-xs font-semibold text-white transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {actionLoading[`outbound-${product.id}`]
                            ? "..."
                            : "–"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Order history */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">
          Historial de movimientos ({orders.length})
        </h2>

        {orders.length === 0 ? (
          <p className="text-sm text-slate-500">
            No hay movimientos registrados.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="py-3 pr-4">Tipo</th>
                  <th className="py-3 pr-4">SKU</th>
                  <th className="py-3 pr-4">Producto</th>
                  <th className="py-3 pr-4">Almacén</th>
                  <th className="py-3 pr-4 text-right">Cantidad</th>
                  <th className="py-3 text-right">Fecha</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr
                    key={`${order.order_type}-${order.id}`}
                    className="border-b border-slate-100 last:border-0"
                  >
                    <td className="py-3 pr-4">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          order.order_type === "inbound"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-rose-100 text-rose-800"
                        }`}
                      >
                        {order.order_type === "inbound" ? "Entrada" : "Salida"}
                      </span>
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs text-slate-700">
                      {order.sku_code}
                    </td>
                    <td className="py-3 pr-4 font-medium text-slate-900">
                      {order.sku_name}
                    </td>
                    <td className="py-3 pr-4 text-slate-600">
                      {order.warehouse}
                    </td>
                    <td className="py-3 pr-4 text-right font-semibold">
                      <span
                        className={
                          order.order_type === "inbound"
                            ? "text-emerald-700"
                            : "text-rose-700"
                        }
                      >
                        {order.order_type === "inbound" ? "+" : "–"}
                        {order.quantity}
                      </span>
                    </td>
                    <td className="py-3 text-right text-xs text-slate-500">
                      {formatDate(order.created_at)}
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