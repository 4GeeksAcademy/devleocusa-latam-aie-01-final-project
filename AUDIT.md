# AUDIT.md — Duplicación de componentes y lógica en el frontend

> **Rol:** Senior Web Performance Engineer  
> **Fecha del análisis:** 2026-08-19  
> **Scope:** Frontend del backoffice (`/uis/backoffice/`)  
> **Restricción:** No se modifica arquitectura global, enrutamiento ni estado global.

---

## Caso 1 — `AuthLayoutCard`: envoltorio visual repetido en las 4 páginas de autenticación

### 📍 Dónde aparece actualmente

| Archivo | Líneas (aproximadas) |
|---|---|
| `app/login/page.tsx` | 24–42 (wrapper + header) |
| `app/register/page.tsx` | 43–62 (wrapper + header) |
| `app/forgot-password/page.tsx` | 36–53 (wrapper + header) |
| `app/reset-password/page.tsx` | 40–59 (wrapper + header) |

### 🧐 Por qué es candidato claro a refactorización

Las cuatro páginas comparten **exactamente la misma estructura JSX de contenedor**:

```tsx
<section className="flex min-h-[calc(100vh-4rem)] items-center justify-center py-8">
  <div className="w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
    <div className="mb-6 space-y-2">
      <h2 className="text-2xl font-semibold tracking-tight text-slate-900">…</h2>
      <p className="text-sm text-slate-600">…</p>
    </div>
    { /* contenido específico de cada página */ }
    <p className="mt-4 text-center text-sm text-slate-600">
      …{' '}
      <Link href="/login" className="font-medium text-sky-700 hover:text-sky-800 hover:underline">…</Link>
    </p>
  </div>
</section>
```

**Impacto en mantenibilidad:**

- Cualquier cambio en el diseño del card de autenticación (bordes, sombras, padding, responsive) obliga a modificar **4 archivos distintos**.
- El footer con el enlace de retorno a `/login` también se repite en 3 de las 4 páginas con la misma estructura.
- El layout visual de estas páginas no tiene razón de negocio para divergir; es ruido visual que entorpece la lectura del formulario específico.

### 💡 Propuesta de abstracción

Extraer un **componente compartido** `AuthLayoutCard` que encapsule el contenedor + header + footer opcional.

```tsx
// app/components/auth/AuthLayoutCard.tsx
import type { ReactNode } from "react";
import Link from "next/link";

interface AuthLayoutCardProps {
  title: string;
  description: string;
  children: ReactNode;
  /** Texto para el footer con enlace. Ej: "Volver a Iniciar sesión" */
  footerLabel?: string;
  /** Ruta del enlace del footer. Por defecto "/login" */
  footerHref?: string;
}

export function AuthLayoutCard({
  title,
  description,
  children,
  footerLabel,
  footerHref = "/login",
}: AuthLayoutCardProps) {
  return (
    <section className="flex min-h-[calc(100vh-4rem)] items-center justify-center py-8">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-6 space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
            {title}
          </h2>
          <p className="text-sm text-slate-600">{description}</p>
        </div>

        {children}

        {footerLabel && (
          <p className="mt-4 text-center text-sm text-slate-600">
            {footerLabel.split(footerLabel.match(/\S+$/)?.[0] ?? "")[0]}{" "}
            <Link
              href={footerHref}
              className="font-medium text-sky-700 hover:text-sky-800 hover:underline"
            >
              {footerLabel.match(/\S+$/)?.[0] ?? footerLabel}
            </Link>
          </p>
        )}
      </div>
    </section>
  );
}
```

**Uso resultante en cada página (ej. Login):**

```tsx
// app/login/page.tsx — se reduce a la lógica del formulario
export default function LoginPage() {
  // … hooks y handlers …

  return (
    <AuthLayoutCard
      title="Iniciar sesión"
      description="Accede al Backoffice de TrackFlow para gestionar candidaturas y operaciones."
      footerLabel="¿No tienes cuenta? Regístrate"
      footerHref="/register"
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* inputs del formulario, sin wrapper repetido */}
      </form>
    </AuthLayoutCard>
  );
}
```

**Impacto:** Elimina ~20 líneas repetidas × 4 páginas ≈ **80 líneas de código duplicado**. Cualquier retoque visual futuro toca un solo archivo.

---

## Caso 2 — `useAsyncData`: patrón loading / error / retry repetido en componentes con fetch

### 📍 Dónde aparece actualmente

| Componente / Página | Archivo | Patrón observado |
|---|---|---|
| `IncidentsSummaryPanel` | `components/incidents/IncidentsSummaryPanel.tsx` | `isLoading` + `error` + `retryKey` + `setRetryKey` manual |
| `IncidentsListPanel` | `components/incidents/IncidentsListPanel.tsx` | `isLoading` + `error` + botón "Reintentar" que llama a `loadIncidents()` |
| `ProductsListPanel` | `components/inventory/ProductsListPanel.tsx` | `loading` + `error` + botón "Reintentar" que llama a `loadProducts()` |
| `EditCandidatePage` | `candidaturas/[id]/edit/page.tsx` | `loading` + `error` + `reloadKey` + `setReloadKey` |
| `CandidatesPageContent` | `candidaturas/page.tsx` | `loading` + `error` + `reloadKey` + `setReloadKey` |
| `CandidateDetailPage` | `candidaturas/[id]/page.tsx` | `loading` + `error` + `reloadKey` + `setReloadKey` |

### 🧐 Por qué es candidato claro a refactorización

Todos estos componentes implementan **el mismo tridente de estado manual**:

```tsx
const [data, setData] = useState<T | null>(null);
const [isLoading, setIsLoading] = useState(true);
const [error, setError] = useState<string | null>(null);
const [retryKey, setRetryKey] = useState(0);

useEffect(() => {
  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchFn();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setIsLoading(false);
    }
  };
  load();
}, [fetchFn, retryKey]);
```

**Impacto en mantenibilidad:**

- Son ~30 líneas de boilerplate que se copian en **cada componente** que necesita cargar datos.
- La gestión del flag `retryKey` como trigger de re-fetch es frágil y fácil de olvidar.
- La lógica de `isMounted` para evitar setState en componentes desmontados (visible en `EditCandidatePage`, `CandidateDetailPage`) se omite en algunos componentes, exponiendo a warnings de React.
- El botón de "Reintentar" (error + retry) se implementa con clases distintas en cada componente (inconsistencia visual).

### 💡 Propuesta de abstracción

Extraer un **Custom Hook** `useAsyncData` que encapsule el ciclo completo de fetch + loading + error + retry.

```tsx
// hooks/useAsyncData.ts
import { useCallback, useEffect, useRef, useState } from "react";

interface UseAsyncDataResult<T> {
  /** Los datos ya cargados, o `null` si aún no hay respuesta exitosa. */
  data: T | null;
  /** `true` mientras se está realizando la petición. */
  isLoading: boolean;
  /** Mensaje de error textual, o `null` si no hay error. */
  error: string | null;
  /** Incrementa el contador de reintentos → dispara un refetch. */
  retry: () => void;
  /** Vuelve a lanzar la petición manualmente (útil tras un CUD). */
  refresh: () => void;
}

/**
 * Hook genérico que gestiona el ciclo de vida de una petición asíncrona:
 * loading → success / error → retry.
 *
 * @param fetchFn  Función que retorna la promesa con los datos.
 * @param deps     Dependencias adicionales (ej. filtros) que disparan refetch.
 */
export function useAsyncData<T>(
  fetchFn: () => Promise<T>,
  deps: unknown[] = [],
): UseAsyncDataResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const isMounted = useRef(true);

  const execute = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await fetchFn();
      if (isMounted.current) {
        setData(result);
      }
    } catch (err) {
      if (isMounted.current) {
        const message =
          err instanceof Error ? err.message : "Ocurrió un error inesperado.";
        setError(message);
      }
    } finally {
      if (isMounted.current) {
        setIsLoading(false);
      }
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    isMounted.current = true;
    void execute();
    return () => {
      isMounted.current = false;
    };
  }, [execute, retryCount]);

  const retry = useCallback(() => {
    setRetryCount((prev) => prev + 1);
  }, []);

  const refresh = useCallback(() => {
    void execute();
  }, [execute]);

  return { data, isLoading, error, retry, refresh };
}
```

**Uso resultante (ej. IncidentsSummaryPanel):**

```tsx
// components/incidents/IncidentsSummaryPanel.tsx
import { useAsyncData } from "@/hooks/useAsyncData";

export function IncidentsSummaryPanel({ refreshToken }: IncidentsSummaryPanelProps) {
  const {
    data: summary,
    isLoading,
    error,
    retry,
  } = useAsyncData(() => getIncidentsSummary(), [refreshToken]);

  return (
    <section className="…">
      {/* … header … */}

      {isLoading && (
        <div className="…">
          <Spinner size="md" label="Cargando métricas" />
        </div>
      )}

      {error && (
        <div className="…">
          <p>{error}</p>
          <button type="button" onClick={retry} className="…">
            Reintentar
          </button>
        </div>
      )}

      {summary && (
        <div className="…">
          {/* render de datos */}
        </div>
      )}
    </section>
  );
}
```

**Impacto:** Elimina ~25–30 líneas de boilerplate por componente. Con 6 puntos de uso identificados, se reducen **~150–180 líneas de lógica duplicada** y se unifica el manejo de `isMounted`, evitando fugas de memoria por setState en componentes desmontados.

---

## Resumen del impacto

| Caso | Abstracción | Archivos afectados | Líneas eliminadas aprox. | Beneficio principal |
|---|---|---|---|---|
| 1 | `AuthLayoutCard` (componente) | 4 páginas auth | ~80 | Consistencia visual + un solo punto de cambio |
| 2 | `useAsyncData` (Custom Hook) | 6 componentes | ~150–180 | Elimina boilerplate + protección `isMounted` |
| **Total** | — | **10 archivos** | **~230–260** | **Mantenibilidad y consistencia** |