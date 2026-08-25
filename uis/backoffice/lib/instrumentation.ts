/**
 * Instrumentation hub for TrackFlow backoffice telemetry.
 *
 * This module wires up:
 *  - Global error capture (window.onerror + unhandledrejection)
 *  - Page view tracking (via Next.js router events)
 *  - Helper functions for business events (auth, inventory, etc.)
 *
 * ALL events use the global `track()` from `@/services/telemetry`
 * and respect the EXACT field names & constraints from event-schemas.json.
 *
 * Usage (in layout.tsx):
 *   import { Instrumentation } from "@/lib/instrumentation";
 *   <Instrumentation />
 */

'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { track } from '@/services/telemetry';
import { initWebVitals } from '@/lib/webVitals';

// ─── SHA-256 helpers ───────────────────────────────────────────────────

/**
 * Returns the SHA-256 hex digest of a string using the Web Crypto API.
 */
async function sha256Hex(input: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(input.normalize('NFC'));
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

// ─── IP address helper ──────────────────────────────────────────────────

/**
 * Best-effort IP retrieval from common headers exposed by the CDN / proxy.
 * Falls back to "0.0.0.0" in local development.
 */
function getClientIP(): string {
  if (typeof window === 'undefined') return '0.0.0.0';
  try {
    // Some CDNs expose the client IP via a header-readable meta or script
    const cfIp = document.querySelector<HTMLMetaElement>(
      'meta[name="cf-connecting-ip"]',
    );
    if (cfIp?.content) return cfIp.content;
  } catch {
    // Ignore
  }
  return '0.0.0.0';
}

// ─── User-Agent helper (truncated, no patch versions) ───────────────────

function getUserAgent(): string {
  if (typeof navigator === 'undefined') return '';
  const ua = navigator.userAgent;
  // Remove patch versions to avoid excessive fingerprinting
  // "Chrome/120.0.0.0" → "Chrome/120"
  return ua.replace(/(\d+\.\d+)(\.\d+)+/g, '$1').slice(0, 120);
}

// ─── Session / user helpers ─────────────────────────────────────────────

const AUTH_TOKEN_STORAGE_KEY = 'trackflow_token';

function getSessionId(): string {
  if (typeof window === 'undefined') return '';
  try {
    const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (!token) return '';
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.jti || payload.sub || '';
  } catch {
    return '';
  }
}

function getUserId(): string {
  if (typeof window === 'undefined') return '';
  try {
    const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (!token) return '';
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.sub || '';
  } catch {
    return '';
  }
}

// ─── Global error capture ───────────────────────────────────────────────

/** Installs window.onerror globally (synchronous errors). */
function installOnError(): void {
  window.onerror = (
    _event: string | Event | null,
    _source: string | undefined,
    _lineno: number | undefined,
    _colno: number | undefined,
    error: Error | undefined,
  ): void => {
    track('ui.action.error', {
      component: 'window',
      action: 'window.onerror',
      error_message: error?.message?.slice(0, 300) ?? 'Unknown error',
      http_status: 0,
      retry_count: 0,
    });
  };
}

/** Installs unhandledrejection listener (async promise rejections). */
function installUnhandledRejection(): void {
  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    const message =
      typeof reason === 'string'
        ? reason.slice(0, 300)
        : reason instanceof Error
          ? reason.message.slice(0, 300)
          : 'Unhandled Promise rejection';

    track('ui.action.error', {
      component: 'window',
      action: 'unhandledrejection',
      error_message: message,
      http_status: 0,
      retry_count: 0,
    });
  });
}

// ─── Business event helpers ─────────────────────────────────────────────

/**
 * Emit auth.login.attempt — called BEFORE the fetch to POST /auth/login.
 *
 * Properties (exact match from event-schemas.json):
 *  - user_email_hash (required, SHA-256)
 *  - ip_address (required)
 *  - warehouse_context (required, enum)
 *  - user_agent (optional, ≤120 chars, no patch versions)
 *
 * IMPORTANT: password is NEVER captured (policy: NEVER_CAPTURED).
 * The event is emitted before sending the credential to the wire.
 */
export async function trackLoginAttempt(
  email: string,
  warehouseContext: string = 'unknown',
): Promise<void> {
  const emailHash = await sha256Hex(email.trim().toLowerCase());

  track('auth.login.attempt', {
    user_email_hash: emailHash,
    ip_address: getClientIP(),
    warehouse_context: warehouseContext,
    user_agent: getUserAgent(),
  });
}

/**
 * Emit auth.login.success — called after storing the JWT.
 *
 * Properties (exact match from event-schemas.json):
 *  - warehouse_context (required, enum)
 */
export function trackLoginSuccess(
  warehouseContext: string = 'unknown',
): void {
  track('auth.login.success', {
    warehouse_context: warehouseContext,
  });
}

/**
 * Emit auth.login.failure — called after HTTP 401.
 *
 * Properties (exact match from event-schemas.json):
 *  - user_email_hash (required, SHA-256)
 *  - failure_reason (required, enum)
 *  - attempt_count (optional)
 *  - ip_address (optional)
 */
export async function trackLoginFailure(
  email: string,
  failureReason: 'invalid_credentials' | 'user_not_found' | 'account_locked',
  attemptCount: number = 1,
): Promise<void> {
  const emailHash = await sha256Hex(email.trim().toLowerCase());

  track('auth.login.failure', {
    user_email_hash: emailHash,
    failure_reason: failureReason,
    attempt_count: attemptCount,
    ip_address: getClientIP(),
  });
}

/**
 * Emit auth.session.expired — called when JWT is expired.
 *
 * Properties (exact match from event-schemas.json):
 *  - session_duration_minutes (required)
 *  - expired_reason (optional, enum)
 */
export function trackSessionExpired(
  sessionDurationMinutes: number = 0,
  expiredReason: 'token_expired' | 'token_invalid' | 'logout' = 'token_expired',
): void {
  track('auth.session.expired', {
    session_duration_minutes: sessionDurationMinutes,
    expired_reason: expiredReason,
  });
}

/**
 * Emit sku.create.attempt — called before POST /inventory/products.
 *
 * Properties (exact match from event-schemas.json):
 *  - sku_code (required)
 *  - warehouse (required, enum)
 *  - product_name_length (optional)
 */
export function trackSkuCreateAttempt(
  skuCode: string,
  warehouse: 'Los Angeles' | 'Zaragoza',
  productNameLength: number = 0,
): void {
  track('sku.create.attempt', {
    sku_code: skuCode,
    warehouse,
    product_name_length: productNameLength,
  });
}

/**
 * Emit sku.create.success — called after HTTP 201.
 *
 * Properties (exact match from event-schemas.json):
 *  - sku_id (required, uuid)
 *  - sku_code (required)
 *  - warehouse (required, enum)
 *  - latency_ms (optional)
 */
export function trackSkuCreateSuccess(
  skuId: string,
  skuCode: string,
  warehouse: 'Los Angeles' | 'Zaragoza',
  latencyMs: number = 0,
): void {
  track('sku.create.success', {
    sku_id: skuId,
    sku_code: skuCode,
    warehouse,
    latency_ms: latencyMs,
  });
}

/**
 * Emit sku.create.failure — called after HTTP 4xx/5xx.
 *
 * Properties (exact match from event-schemas.json):
 *  - sku_code (required)
 *  - error_code (required, enum)
 *  - http_status (required)
 *  - error_detail (optional, ≤300 chars)
 */
export function trackSkuCreateFailure(
  skuCode: string,
  errorCode: 'duplicate_sku' | 'validation_error' | 'server_error' | 'unauthorized',
  httpStatus: number,
  errorDetail: string = '',
): void {
  track('sku.create.failure', {
    sku_code: skuCode,
    error_code: errorCode,
    http_status: httpStatus,
    error_detail: errorDetail.slice(0, 300),
  });
}

/**
 * Emit inbound.order.created — called after POST /inventory/orders/inbound 201.
 *
 * Properties (exact match from event-schemas.json):
 *  - sku_id (required, uuid)
 *  - sku_code (required)
 *  - warehouse (required, enum)
 *  - quantity (required)
 *  - stock_before (optional)
 *  - stock_after (required)
 *  - latency_ms (optional)
 */
export function trackInboundOrderCreated(
  skuId: string,
  skuCode: string,
  warehouse: 'Los Angeles' | 'Zaragoza',
  quantity: number,
  stockAfter: number,
  stockBefore?: number,
  latencyMs?: number,
): void {
  const props: Record<string, unknown> = {
    sku_id: skuId,
    sku_code: skuCode,
    warehouse,
    quantity,
    stock_after: stockAfter,
  };
  if (stockBefore !== undefined) props.stock_before = stockBefore;
  if (latencyMs !== undefined) props.latency_ms = latencyMs;

  track('inbound.order.created', props);
}

/**
 * Emit outbound.order.created — called after POST /inventory/orders/outbound 201.
 *
 * Properties (exact match from event-schemas.json):
 *  - sku_id (required, uuid)
 *  - sku_code (required)
 *  - warehouse (required, enum)
 *  - quantity (required)
 *  - stock_before (optional)
 *  - stock_after (required)
 *  - latency_ms (optional)
 */
export function trackOutboundOrderCreated(
  skuId: string,
  skuCode: string,
  warehouse: 'Los Angeles' | 'Zaragoza',
  quantity: number,
  stockAfter: number,
  stockBefore?: number,
  latencyMs?: number,
): void {
  const props: Record<string, unknown> = {
    sku_id: skuId,
    sku_code: skuCode,
    warehouse,
    quantity,
    stock_after: stockAfter,
  };
  if (stockBefore !== undefined) props.stock_before = stockBefore;
  if (latencyMs !== undefined) props.latency_ms = latencyMs;

  track('outbound.order.created', props);
}

/**
 * Emit ui.action.error — generic component-level error.
 *
 * Properties (exact match from event-schemas.json):
 *  - component (required)
 *  - action (required)
 *  - error_message (required, ≤300 chars)
 *  - http_status (optional)
 *  - retry_count (optional)
 */
export function trackUiActionError(
  component: string,
  action: string,
  errorMessage: string,
  httpStatus: number = 0,
  retryCount: number = 0,
): void {
  track('ui.action.error', {
    component,
    action,
    error_message: errorMessage.slice(0, 300),
    http_status: httpStatus,
    retry_count: retryCount,
  });
}

// ─── React component: Instrumentation ─────────────────────────────────

/**
 * React component that installs global error handlers and tracks
 * page views on every route change.
 *
 * Place ONCE in the root layout, inside `<body>`.
 *
 * @example
 * ```tsx
 * // app/layout.tsx
 * import { Instrumentation } from "@/lib/instrumentation";
 *
 * export default function RootLayout({ children }) {
 *   return (
 *     <html>
 *       <body>
 *         <Instrumentation />
 *         {children}
 *       </body>
 *     </html>
 *   );
 * }
 * ```
 */
export function Instrumentation(): null {
  const pathname = usePathname();
  const prevRef = useRef<string>('');

  useEffect(() => {
    // Install global error handlers once
    installOnError();
    installUnhandledRejection();
    initWebVitals();
  }, []);

  useEffect(() => {
    const prev = prevRef.current;
    const now = performance.now();
    prevRef.current = pathname;

    track('ui.page.view', {
      page: pathname,
      referrer: prev,
      load_time_ms: prev ? Math.round(performance.now() - now) : 0,
    });
  }, [pathname]);

  return null;
}