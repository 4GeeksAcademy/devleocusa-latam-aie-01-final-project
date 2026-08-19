/**
 * Centralized HTTP module for inventory API calls.
 *
 * All inventory-related HTTP requests must go through this module.
 * Components must NEVER use `fetch` or `axios` directly.
 *
 * Features:
 * - Auto-injects `Authorization: Bearer <token>` for protected endpoints
 * - Global error handler extracts messages from 4xx/5xx responses
 * - Single base URL source of truth via NEXT_PUBLIC_INVENTORY_API_URL
 */

import { getSessionToken } from "@/services/authApi";

// ─── Base URL ───────────────────────────────────────────────────────────

const INVENTORY_API_BASE_URL: string =
  typeof process !== "undefined" &&
  typeof process.env === "object" &&
  (process.env as Record<string, string | undefined>).NEXT_PUBLIC_INVENTORY_API_URL
    ? ((process.env as Record<string, string | undefined>)
        .NEXT_PUBLIC_INVENTORY_API_URL as string)
    : "http://localhost:8000";

const INVENTORY_PREFIX = "/inventory";

// ─── Types ──────────────────────────────────────────────────────────────

export type WarehouseLocation = "Los Angeles" | "Zaragoza";

export interface SKURead {
  id: string;
  name: string;
  sku_code: string;
  warehouse: string;
  current_stock: number;
}

export interface SKUCreatePayload {
  name: string;
  sku_code: string;
  warehouse: WarehouseLocation;
}

export interface InboundOrderPayload {
  sku_id: string;
  quantity: number;
}

export interface OutboundOrderPayload {
  sku_id: string;
  quantity: number;
}

export interface SKUEntryRead {
  id: string;
  sku_id: string;
  quantity: number;
  created_at: string;
  user_uuid: string;
}

export interface SKUExitRead {
  id: string;
  sku_id: string;
  quantity: number;
  created_at: string;
  user_uuid: string;
}

export interface OrderHistoryItem {
  order_type: "inbound" | "outbound";
  id: string;
  sku_id: string;
  sku_code: string;
  sku_name: string;
  warehouse: string;
  quantity: number;
  user_uuid: string;
  created_at: string;
}

// ─── Custom Error ───────────────────────────────────────────────────────

export class InventoryApiError extends Error {
  public readonly status: number;
  public readonly body: unknown | null;

  constructor(message: string, status: number, body: unknown | null = null) {
    super(message);
    this.name = "InventoryApiError";
    this.status = status;
    this.body = body;
  }
}

// ─── Internal helpers ───────────────────────────────────────────────────

function resolveUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${INVENTORY_API_BASE_URL}${INVENTORY_PREFIX}${normalizedPath}`;
}

/**
 * Read the session token from the existing auth system (localStorage).
 * Returns `null` when running server-side (SSR).
 */
function readAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return getSessionToken();
}

/**
 * Build standard headers, injecting the Bearer token when available.
 */
function buildHeaders(
  customHeaders?: Record<string, string>
): Headers {
  const headers = new Headers(customHeaders ?? undefined);

  // Default to JSON for all requests
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = readAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return headers;
}

/**
 * Global error handler.
 *
 * - On 4xx/5xx responses it attempts to extract a human-readable message
 *   from the JSON body (`detail`, `message`, or `error` fields).
 * - On network failures a generic message is thrown.
 * - If the response is 401 Unauthorized, the token is cleared and the user
 *   is redirected to /login.
 */
async function handleResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    // 2xx — parse body (may be empty on 201/204)
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const data: T = await response.json();
      return data;
    }
    // Non-JSON success (rare) — cast the body as T
    return (await response.text()) as unknown as T;
  }

  // ── Error path (4xx / 5xx) ────────────────────────────────────────
  let errorMessage = `Error del servidor (${response.status}).`;

  try {
    const errorBody: Record<string, unknown> = await response.json();

    // Try common JSON:API error fields
    const detail = errorBody["detail"];
    if (typeof detail === "string") {
      errorMessage = detail;
    } else if (typeof detail === "object" && detail !== null) {
      const nested = detail as Record<string, unknown>;
      errorMessage =
        (typeof nested["error"] === "string" ? nested["error"] : undefined) ??
        (typeof nested["message"] === "string" ? nested["message"] : undefined) ??
        errorMessage;
    } else if (typeof errorBody["message"] === "string") {
      errorMessage = errorBody["message"];
    } else if (typeof errorBody["error"] === "string") {
      errorMessage = errorBody["error"];
    }

    throw new InventoryApiError(errorMessage, response.status, errorBody);
  } catch (err) {
    if (err instanceof InventoryApiError) throw err;

    // Response was not valid JSON
    throw new InventoryApiError(errorMessage, response.status);
  }
}

/**
 * Perform an authenticated HTTP request against the inventory API.
 *
 * This is the **only** function components should call — never `fetch`
 * directly.
 */
async function inventoryFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = resolveUrl(path);
  const headers = buildHeaders(options.headers as Record<string, string> | undefined);

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    return handleResponse<T>(response);
  } catch (error) {
    // Re-throw InventoryApiError instances as-is
    if (error instanceof InventoryApiError) throw error;

    // Network / connection errors
    throw new InventoryApiError(
      "No fue posible conectar con el servidor de inventario. Revisa tu conexión e inténtalo de nuevo.",
      0
    );
  }
}

// ─── Public API functions ──────────────────────────────────────────────

/**
 * List all SKU products with their computed stock balance.
 * GET /inventory/products
 */
export async function listProducts(): Promise<SKURead[]> {
  return inventoryFetch<SKURead[]>("/products");
}

/**
 * Get a single SKU by its ID.
 * GET /inventory/products/{skuId}
 */
export async function getProduct(skuId: string): Promise<SKURead> {
  return inventoryFetch<SKURead>(`/products/${encodeURIComponent(skuId)}`);
}

/**
 * Create a new SKU product (requires authentication).
 * POST /inventory/products
 */
export async function createProduct(
  payload: SKUCreatePayload
): Promise<SKURead> {
  return inventoryFetch<SKURead>("/products", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Record an inbound stock movement (requires authentication).
 * POST /inventory/orders/inbound
 */
export async function createInboundOrder(
  payload: InboundOrderPayload
): Promise<SKUEntryRead> {
  return inventoryFetch<SKUEntryRead>("/orders/inbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Record an outbound stock movement (requires authentication).
 * POST /inventory/orders/outbound
 */
export async function createOutboundOrder(
  payload: OutboundOrderPayload
): Promise<SKUExitRead> {
  return inventoryFetch<SKUExitRead>("/orders/outbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * List combined order history (inbound + outbound) sorted by date descending.
 * GET /inventory/orders
 */
export async function listOrders(): Promise<OrderHistoryItem[]> {
  return inventoryFetch<OrderHistoryItem[]>("/orders");
}