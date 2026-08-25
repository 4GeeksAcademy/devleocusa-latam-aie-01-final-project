/**
 * Telemetry capture service for TrackFlow backoffice.
 *
 * Batches events in an internal queue and flushes them periodically
 * (every 10 s or when 20 events accumulate, whichever comes first).
 * On page visibility change to "hidden", uses navigator.sendBeacon()
 * for reliable delivery.
 *
 * Usage:
 *   import { track } from '@/services/telemetry';
 *   track('page_view', { page: '/dashboard' });
 */

const DEFAULT_ENDPOINT = 'http://localhost:8000/telemetry/events';

function resolveEndpoint(): string {
  if (
    typeof process !== 'undefined' &&
    typeof process.env === 'object'
  ) {
    const env = process.env as Record<string, string | undefined>;
    return env.NEXT_PUBLIC_TELEMETRY_ENDPOINT || DEFAULT_ENDPOINT;
  }
  return DEFAULT_ENDPOINT;
}

// ── Queue ────────────────────────────────────────────────────────────────

interface TelemetryEvent {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string | null;
  event_type: string;
  schemaVersion: string;
  requestId: string;
  properties: Record<string, unknown>;
}

const QUEUE_BATCH_SIZE = 20;
const QUEUE_FLUSH_INTERVAL_MS = 10_000;
const MAX_RETRIES = 3;

let queue: TelemetryEvent[] = [];
let timerId: ReturnType<typeof setInterval> | null = null;
let sessionId = generateSessionId();
let requestCounter = 0;

// ── Helpers ──────────────────────────────────────────────────────────────

function uuidv4(): string {
  try {
    return crypto.randomUUID();
  } catch {
    // Fallback for environments without crypto.randomUUID
    return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
  }
}

function generateSessionId(): string {
  return uuidv4();
}

function nextRequestId(): string {
  requestCounter += 1;
  return `req-${Date.now()}-${requestCounter}`;
}

function nowISO(): string {
  return new Date().toISOString();
}

// ── Flush / batch send ───────────────────────────────────────────────────

async function sendBatch(events: TelemetryEvent[]): Promise<boolean> {
  const endpoint = resolveEndpoint();
  const body = JSON.stringify({ events });

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      });

      if (response.ok) {
        return true;
      }

      // Non-OK status – treat as transient unless it's a client error (4xx)
      if (response.status >= 400 && response.status < 500) {
        // Client errors are not retryable
        console.warn(
          `[telemetry] batch rejected (${response.status}), dropping silently`,
        );
        return false;
      }
    } catch (err) {
      // Network error – will retry
      console.warn(
        `[telemetry] batch send failed (attempt ${attempt + 1}/${MAX_RETRIES + 1})`,
        err,
      );
    }

    if (attempt < MAX_RETRIES) {
      // Exponential backoff: 1 s, 2 s, 4 s
      const delay = 2 ** attempt * 1000;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  // All retries exhausted
  console.warn('[telemetry] batch discarded after max retries');
  return false;
}

function flushViaBeacon(events: TelemetryEvent[]): boolean {
  const endpoint = resolveEndpoint();
  const blob = new Blob([JSON.stringify({ events })], {
    type: 'application/json',
  });
  return navigator.sendBeacon(endpoint, blob);
}

function flush(): void {
  if (queue.length === 0) return;

  const batch = queue.splice(0);
  void sendBatch(batch);
}

function flushSync(): void {
  if (queue.length === 0) return;

  const batch = queue.splice(0);
  flushViaBeacon(batch);
}

// ── Timer management ─────────────────────────────────────────────────────

function startTimer(): void {
  if (timerId !== null) return;
  timerId = setInterval(flush, QUEUE_FLUSH_INTERVAL_MS);
}

function stopTimer(): void {
  if (timerId !== null) {
    clearInterval(timerId);
    timerId = null;
  }
}

// ── Visibility change listener ───────────────────────────────────────────

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      // Stop the periodic timer while page is hidden
      stopTimer();
      flushSync();
    } else {
      // Resume timer when page becomes visible again
      startTimer();
    }
  });
}

// ── Public API ───────────────────────────────────────────────────────────

/**
 * Enqueue a telemetry event.
 *
 * @param eventType  – The type/category of the event (e.g. "page_view").
 * @param properties – Arbitrary key-value payload for the event.
 */
export function track(
  eventType: string,
  properties: Record<string, unknown>,
): void {
  const event: TelemetryEvent = {
    eventId: uuidv4(),
    timestamp: nowISO(),
    sessionId,
    userId: null,
    event_type: eventType,
    schemaVersion: '1.0',
    requestId: nextRequestId(),
    properties,
  };

  queue.push(event);

  if (queue.length >= QUEUE_BATCH_SIZE) {
    flush();
  }

  // Ensure the periodic timer is running
  startTimer();
}