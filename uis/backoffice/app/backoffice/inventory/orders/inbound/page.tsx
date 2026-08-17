"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Alert } from "@/app/components/ui/Alert";
import { Spinner } from "@/app/components/ui/Spinner";
import {
  listProducts,
  createInboundOrder,
  type SKURead,
  InventoryApiError,
} from "@/lib/inventory";

type FeedbackKind = "success" | "error";

export default function InboundOrderPage() {
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

  // ── Derived ────────────────────────────────────────────────────────
  const selectedProduct = useMemo(
    () => products.find((p) => p.id === selectedSkuId) ?? null,
    [products, selectedSkuId]
  );

  const canSubmit =
    selectedSkuId !== "" &&
    quantity.trim() !== "" &&
    parseInt(quantity, 10) >= 1 &&
    !submitting;

  // ── Submit ─────────────────────────────────────────────────────────
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    const qty = parseInt(quantity, 10);
    setSubmitting(true);
    setFeedback(null);

    try {
      const result = await createInboundOrder({
        sku_id: selectedSkuId,
        quantity: qty,
      });

      const skuCode = selectedProduct?.sku_code ?? selectedSkuId;
      setFeedback({
        kind: "success",
        message: `Entrada registrada: +${result.quantity} uds. para SKU "${skuCode}".`,
      });

      // Limpiar formulario
      setSelectedSkuId("");
      setQuantity("");
    } catch (err) {
      const message =
        err instanceof InventoryApiError
          ? err.message
          : "No se pudo registrar la entrada.";
      setFeedback({ kind: "error", message });
    } finally {
      setSubmitting(false);
    }
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
          Registrar Entrada (Inbound)
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Incrementa el stock de un producto seleccionándolo del catálogo.
        </p>
      </div>

      {/* ── Feedback ──────────────────────────────────────────────── */}
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
              htmlFor="product-select"
              className="block text-sm font-medium text-slate-700"
            >
              Producto
            </label>
            <select
              id="product-select"
              value={selectedSkuId}
              onChange={(e) => {
                setSelectedSkuId(e.target.value);
                setFeedback(null);
              }}
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

            {selectedProduct && (
              <div className="mt-2 flex items-center gap-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <span>
                  <span className="font-semibold text-slate-700">Stock actual:</span>{" "}
                  {selectedProduct.current_stock} uds.
                </span>
                <span>
                  <span className="font-semibold text-slate-700">Almacén:</span>{" "}
                  {selectedProduct.warehouse === "Los Angeles"
                    ? "Los Ángeles"
                    : selectedProduct.warehouse}
                </span>
              </div>
            )}
          </div>

          {/* Cantidad */}
          <div>
            <label
              htmlFor="inbound-qty"
              className="block text-sm font-medium text-slate-700"
            >
              Cantidad de entrada
            </label>
            <input
              id="inbound-qty"
              type="number"
              min={1}
              step={1}
              required
              value={quantity}
              onChange={(e) => {
                setQuantity(e.target.value);
                setFeedback(null);
              }}
              placeholder="Ej. 50"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              disabled={!selectedProduct}
            />
            <p className="mt-1 text-xs text-slate-500">
              Unidades que ingresan al almacén.
            </p>
          </div>

          {/* Acciones */}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {submitting ? "Registrando…" : "Confirmar entrada"}
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