"use client";

import type { ReactNode } from "react";

interface AuthGuardProps {
  /** Content to render when the user is authenticated. */
  children: ReactNode;
  /** Unused. Kept for backwards compatibility with existing call sites. */
  redirectTo?: string;
}

/**
 * @deprecated La protección de rutas vive en `ProtectedRoute`, que `AppShell`
 * aplica a todas las rutas privadas.
 *
 * Antes este componente tenía su propia validación de JWT y su propia
 * redirección a `/login`. Tener dos guards con dos políticas distintas
 * provocaba cierres de sesión "fantasma": `AppShell` redirigía primero y el
 * mensaje de `AuthGuard` nunca llegaba a verse.
 *
 * Se mantiene como passthrough para no romper las páginas que lo envuelven.
 *
 * @example
 * ```tsx
 * // En una página de inventario:
 * export default function InventoryPage() {
 *   return (
 *     <AuthGuard>
 *       <InventoryDashboard />
 *     </AuthGuard>
 *   );
 * }
 * ```
 */
export function AuthGuard({ children }: AuthGuardProps) {
  return <>{children}</>;
}
