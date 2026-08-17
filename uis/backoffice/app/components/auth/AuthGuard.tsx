"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSessionToken } from "@/services/authApi";
import { Spinner } from "@/app/components/ui/Spinner";
import { Alert } from "@/app/components/ui/Alert";

interface AuthGuardProps {
  /** Content to render when the user is authenticated. */
  children: ReactNode;
  /** Optional path to redirect unauthenticated users (default: /login). */
  redirectTo?: string;
}

/**
 * Route guard component that blocks access to unauthenticated users.
 *
 * - If no valid session token is found, the user is redirected to `/login`
 *   (or a custom `redirectTo` path).
 * - While checking authentication a centered spinner is displayed.
 * - If the token is present but expired or malformed, the guard also
 *   redirects after clearing any stale token.
 *
 * @example
 * ```tsx
 * // In an inventory page:
 * export default function InventoryPage() {
 *   return (
 *     <AuthGuard>
 *       <InventoryDashboard />
 *     </AuthGuard>
 *   );
 * }
 * ```
 */
export function AuthGuard({ children, redirectTo = "/login" }: AuthGuardProps) {
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "authenticated" | "unauthenticated">("loading");

  useEffect(() => {
    const token = getSessionToken();

    if (!token) {
      setStatus("unauthenticated");
      router.replace(redirectTo);
      return;
    }

    // Quick JWT validity check (same logic as authApi.isTokenValid)
    const tokenParts = token.split(".");
    if (tokenParts.length !== 3) {
      setStatus("unauthenticated");
      router.replace(redirectTo);
      return;
    }

    try {
      const normalizedPayload = tokenParts[1].replace(/-/g, "+").replace(/_/g, "/");
      const decodedPayload = atob(normalizedPayload);
      const payload = JSON.parse(decodedPayload) as { exp?: number };

      if (payload.exp && payload.exp <= Math.floor(Date.now() / 1000)) {
        // Token expired — clear and redirect
        localStorage.removeItem("trackflow_token");
        setStatus("unauthenticated");
        router.replace(redirectTo);
        return;
      }
    } catch {
      // Malformed payload — treat as invalid
      localStorage.removeItem("trackflow_token");
      setStatus("unauthenticated");
      router.replace(redirectTo);
      return;
    }

    setStatus("authenticated");
  }, [router, redirectTo]);

  if (status === "loading") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <Spinner label="Verificando sesión..." />
        </div>
      </div>
    );
  }

  if (status === "unauthenticated") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Alert variant="error">
          Debes iniciar sesión para acceder a esta sección.
        </Alert>
      </div>
    );
  }

  return <>{children}</>;
}