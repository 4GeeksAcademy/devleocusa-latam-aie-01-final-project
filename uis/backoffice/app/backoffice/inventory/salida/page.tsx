"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { Alert } from "@/app/components/ui/Alert";
import { Spinner } from "@/app/components/ui/Spinner";
import {
  createOutboundOrder,
  InventoryApiError,
} from "@/lib/inventory";

function SalidaForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const skuId = searchParams.get("sku_id") ?? "";
  const skuCode = searchParams.get("sku_code") ?? "";
  const productName = searchParams.get("name") ?? "";

  const [quantity, setQuantity] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const qty = parseInt(quantity, 10);
    if (!qty || qty < 1) {
      setFeedback({
        kind: "error",
        message: "La cantidad debe ser un número entero mayor que 0.",
      });
      return;
    }

    setSubmitting(true);
    setFeedback(null);

    try {
      await createOutboundOrder({ sku_id: skuId, quantity: qty });
      setFeedback({
        kind: "success",
        message: `Salida registrada: -${qty} unidades de "${productName || skuCode}".`,
      });
      setQuantity("");
      setTimeout(() => router.push("/backoffice/inventory/products"), 1200);
    } catch (err: unknown) {
      const message =
        err instanceof InventoryApiError
          ? err.message
          : "No se pudo registrar la salida.";
      setFeedback({ kind: "error", message });
    } finally {
      setSubmitting(false);
    }
  };

  if (!skuId) {
    return (
      <div className="mx-auto max-w-lg space-y-4 py-10">
        <Alert variant="error">
          No se ha especificado un producto. Selecciona uno desde el{" "}
          <Link
            href="/backoffice/inventory/products"
            className="font-semibold underline"
          >
            listado de productos
          </Link>
          .
        </Alert>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-6 py-6">
      {/* Cabecera */}
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
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
          </svg>
          Volver a productos
        </Link>
        <h1 className="mt-2 text-xl font-bold text-slate-900">
          Registrar Salida
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Reduce el stock de un producto por despacho o baja.
        </p>
      </div>

      {/* Contexto del producto */}
      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-slate-500">
          Producto seleccionado
        </p>
        <div className="mt-2 flex items-center gap-3">
          <span className="font-mono text-sm font-medium text-slate-700">
            {skuCode}
          </span>
          {productName && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-sm font-semibold text-slate-900">
                {productName}
              </span>
            </>
          )}
        </div>
      </section>

      {/* Feedback */}
      {feedback && (
        <Alert variant={feedback.kind}>{feedback.message}</Alert>
      )}

      {/* Formulario */}
      <form
        onSubmit={handleSubmit}
        className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="space-y-4">
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
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="Ej. 10"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              autoFocus
            />
            <p className="mt-1 text-xs text-slate-500">
              Unidades que egresan del almacén.
            </p>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {submitting ? "Registrando..." : "Confirmar salida"}
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

export default function SalidaPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center">
          <Spinner label="Preparando formulario…" />
        </div>
      }
    >
      <SalidaForm />
    </Suspense>
  );
}