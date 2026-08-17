"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Alert } from "@/app/components/ui/Alert";
import { Spinner } from "@/app/components/ui/Spinner";
import {
  listProducts,
  createOutboundOrder,
  type SKURead,
  InventoryApiError,
} from "@/lib/inventory";

type FeedbackKind = "success" | "error";

export default function OutboundOrderPage() {
  // ── Product list ───────────────────────────────────────────────────
  const [products, setProducts] = useState<SKURead[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [productsError, setProductsError] = useState<string | null>(null);

  // ── Form state ─────────────────────────────────────────────────────
  const [selectedSkuId, setSelectedSkuId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // ── Feedback ───────────────────────────────────────────────────────
  const [feedback, setFeedback] = useState<{
    kind: FeedbackKind;
    message: string;
  } | null>(null);

  // ── Server error bound to the quantity field ──────────────────────
  const [serverQtyError, setServerQtyError] = useState<string | null>(null);

  // ── Load products on mount ─────────────────────────────────────────
  const loadProducts = useCallback(async () => {
    setLoadingProducts(true);
    setProductsError(null);
    try {
      const data = await listProducts();
      setProducts(data);
    } catch (err) {
      const message =
        err instanceof InventoryApiError
          ? err.message
          : "No se pudieron cargar los productos.";
      setProductsError(message);
    } finally {
      setLoadingProducts(false);
    }
  }, []);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  // ── Derived from selected product ─────────────────────────────────
  const selectedProduct = useMemo(
    () => products.find((p) => p.id === selectedSkuId) ?? null,
    [products, selectedSkuId]
  );

  const availableStock = selectedProduct?.current_stock ?? 0;
  const requestedQty = parseInt(quantity, 10) || 0;

  // ── Validation ────────────────────────────────────────────────────
  const qtyExceedsStock = selectedSkuId !== "" && requestedQty > availableStock;
  const qtyInvalid = quantity.trim() !== "" && (requestedQty < 1 || isNaN(requestedQty));
  const canSubmit =
    selectedSkuId !== "" &&
    quantity.trim() !== "" &&
    requestedQty >= 1 &&
    !qtyExceedsStock &&
    !submitting;

  // ── Submit ─────────────────────────────────────────────────────────
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    setSubmitting(true);
    setFeedback(null);
    setServerQtyError(null);

    try {
      const result = await createOutboundOrder({
        sku_id: selectedSkuId,
        quantity: requestedQty,
      });

      const skuCode = selectedProduct?.sku_code ?? selectedSkuId;
      setFeedback({
        kind: "success",
        message: `Salida registrada: -${result.quantity} uds. para SKU "${skuCode}".`,
      });

      // Limpiar formulario
      setSelectedSkuId("");
      setQuantity("");
    } catch (err) {
      if (err instanceof InventoryApiError) {
        if (err.status === 400) {
          // Error de stock insuficiente / concurrencia — mostrar inline
          setServerQtyError(err.message);
        } else {
          setFeedback({ kind: "error", message: err.message });
        }
      } else {
        setFeedback({
          kind: "error",
          message: "No se pudo registrar la salida.",
        });
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ── Helpers to clear field-level errors on change ─────────────────
  const handleProductChange = (value: string) => {
    setSelectedSkuId(value);
    setFeedback(null);
    setServerQtyError(null);
  };

  const handleQuantityChange = (value: string) => {
    setQuantity(value);
    setFeedback(null);
    setServerQtyError(null);
  };

  // ── Loading / Error states ─────────────────────────────────────────
  if (loadingProducts) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Spinner label="Cargando productos…" size="lg" />
      </div>
    );
  }

  if (productsError && products.length === 0) {
    return (
      <div className="mx-auto max-w-lg space-y-4 py-10">
        <Alert variant="error">{productsError}</Alert>
        <button
          type="button"
          onClick={loadProducts}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
        >
          Reintentar
        </button>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className="mx-auto max-w-xl space-y-6 py-6">
      {/* ── Cabecera ──────────────────────────────────────────────── */}
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
          Registrar Salida (Outbound)
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Reduce el stock de un producto. El sistema valida disponibilidad
          antes y durante el envío.
        </p>
      </div>

      {/* ── Feedback global ───────────────────────────────────────── */}
      {feedback && (
        <Alert variant={feedback.kind}>{feedback.message}</Alert>
      )}

      {/* ── Formulario ────────────────────────────────────────────── */}
      <form
        onSubmit={handleSubmit}
        className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="space-y-5">
          {/* Selector de producto */}
          <div>
            <label
              htmlFor="product-select-out"
              className="block text-sm font-medium text-slate-700"
            >
              Producto
            </label>
            <select
              id="product-select-out"
              value={selectedSkuId}
              onChange={(e) => handleProductChange(e.target.value)}
              required
              className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            >
              <option value="">— Selecciona un producto —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.sku_code} — {p.name} ({p.warehouse})
                </option>
              ))}
            </select>
          </div>

          {/* ── Stock reactivo ──────────────────────────────────── */}
          {selectedProduct && (
            <div
              className={`rounded-lg border px-4 py-3 ${
                availableStock === 0
                  ? "border-red-300 bg-red-50"
                  : availableStock < 10
                  ? "border-red-200 bg-red-50/50"
                  : availableStock < 50
                  ? "border-amber-200 bg-amber-50/50"
                  : "border-emerald-200 bg-emerald-50/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">
                  Stock disponible
                </span>
                <span
                  className={`text-lg font-bold ${
                    availableStock === 0
                      ? "text-red-600"
                      : availableStock < 10
                      ? "text-red-500"
                      : availableStock < 50
                      ? "text-amber-600"
                      : "text-emerald-600"
                  }`}
                >
                  {availableStock} uds.
                </span>
              </div>
              {availableStock === 0 && (
                <p className="mt-1 text-xs text-red-600">
                  Este producto está agotado. No es posible registrar salidas.
                </p>
              )}
            </div>
          )}

          {/* Cantidad */}
          <div>
            <label
              htmlFor="outbound-qty"
              className="block text-sm font-medium text-slate-700"
            >
              Cantidad de salida
            </label>
            <input
              id="outbound-qty"
              type="number"
              min={1}
              step={1}
              required
              value={quantity}
              onChange={(e) => handleQuantityChange(e.target.value)}
              placeholder="Ej. 10"
              disabled={!selectedProduct || availableStock === 0}
              className={`mt-1 block w-full rounded-lg border px-4 py-2.5 text-sm shadow-sm focus:outline-none focus:ring-1 disabled:cursor-not-allowed disabled:opacity-50 ${
                qtyExceedsStock || serverQtyError
                  ? "border-red-400 focus:border-red-500 focus:ring-red-500"
                  : "border-slate-300 focus:border-cyan-500 focus:ring-cyan-500"
              }`}
            />

            {/* ── Inline validation messages ───────────────────── */}
            <div className="mt-1.5 min-h-[1.25rem] space-y-1">
              {selectedProduct && qtyInvalid && (
                <p className="text-xs text-red-600">
                  La cantidad debe ser al menos 1.
                </p>
              )}

              {qtyExceedsStock && (
                <p className="flex items-center gap-1 text-xs font-medium text-red-600">
                  <svg
                    className="h-3.5 w-3.5 flex-shrink-0"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"
                    />
                  </svg>
                  La cantidad solicitada ({requestedQty}) supera el stock
                  disponible ({availableStock}). Reduce el valor.
                </p>
              )}

              {serverQtyError && (
                <p className="flex items-center gap-1 text-xs font-medium text-red-600">
                  <svg
                    className="h-3.5 w-3.5 flex-shrink-0"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
                    />
                  </svg>
                  {serverQtyError}
                </p>
              )}
            </div>
          </div>

          {/* Acciones */}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {submitting ? "Registrando…" : "Confirmar salida"}
            </button>

            <Link
              href="/backoffice/inventory/products"
              className="rounded-lg border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Cancelar
            </Link>
          </div>
        </div>
      </form>
    </div>
  );
}