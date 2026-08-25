/**
 * Web Vitals instrumentation for TrackFlow backoffice telemetry.
 *
 * Captures real-user metrics (LCP, FID/INP, CLS, TTFB, FCP) using the
 * standard `web-vitals` library and emits them as `performance.web.vitals`
 * telemetry events via the global `track()` function.
 *
 * Usage (in Instrumentation component):
 *   import { initWebVitals } from "@/lib/webVitals";
 *   initWebVitals();
 */

import { onCLS, onFCP, onINP, onLCP, onTTFB } from 'web-vitals';
import { track } from '@/services/telemetry';

// ─── Metric name mapping ───────────────────────────────────────────────

type WebVitalMetric =
  | 'LCP'  // Largest Contentful Paint
  | 'CLS'  // Cumulative Layout Shift
  | 'TTFB' // Time to First Byte
  | 'FCP'  // First Contentful Paint
  | 'INP'  // Interaction to Next Paint

// ─── Rating helper ─────────────────────────────────────────────────────

/**
 * Converts a raw numeric threshold value to a qualitative rating.
 *
 * Thresholds from Google's "Core Web Vitals" guidance:
 *   Good  → green
 *   Needs improvement → orange
 *   Poor  → red
 */
function getRating(metric: WebVitalMetric, value: number): 'good' | 'needs-improvement' | 'poor' {
  switch (metric) {
    case 'LCP':
      if (value <= 2500) return 'good';
      if (value <= 4000) return 'needs-improvement';
      return 'poor';
    case 'CLS':
      // CLS is unitless, threshold at 0.1 / 0.25
      if (value <= 0.1) return 'good';
      if (value <= 0.25) return 'needs-improvement';
      return 'poor';
    case 'TTFB':
      if (value <= 800) return 'good';
      if (value <= 1800) return 'needs-improvement';
      return 'poor';
    case 'FCP':
      if (value <= 1800) return 'good';
      if (value <= 3000) return 'needs-improvement';
      return 'poor';
    case 'INP':
      if (value <= 200) return 'good';
      if (value <= 500) return 'needs-improvement';
      return 'poor';
    default:
      return 'needs-improvement';
  }
}

// ─── Emit single Web Vital ──────────────────────────────────────────────

function emitWebVital(
  metric: WebVitalMetric,
  value: number,
  rating: 'good' | 'needs-improvement' | 'poor',
): void {
  // Round CLS to 4 decimal places, rest to integers
  const roundedValue = metric === 'CLS'
    ? Math.round(value * 10_000) / 10_000
    : Math.round(value);

  track('performance.web.vitals', {
    metric,
    value: roundedValue,
    rating,
  });
}

// ─── Initialisation ─────────────────────────────────────────────────────

let registered = false;

/**
 * Registers Web Vitals observers that emit telemetry events.
 *
 * Safe to call multiple times — observers are installed only once.
 * Should be called once the app has hydrated (inside a useEffect).
 */
export function initWebVitals(): void {
  if (registered) return;
  registered = true;

  // LCP — Largest Contentful Paint
  onLCP((report) => {
    emitWebVital('LCP', report.value, getRating('LCP', report.value));
  });

  // INP — Interaction to Next Paint (replaces FID, Chromium 120+)
  try {
    onINP((report) => {
      emitWebVital('INP', report.value, getRating('INP', report.value));
    });
  } catch {
    // INP not supported in older browsers — silently skip
  }

  // CLS — Cumulative Layout Shift
  onCLS((report) => {
    emitWebVital('CLS', report.value, getRating('CLS', report.value));
  });

  // TTFB — Time to First Byte
  onTTFB((report) => {
    emitWebVital('TTFB', report.value, getRating('TTFB', report.value));
  });

  // FCP — First Contentful Paint
  onFCP((report) => {
    emitWebVital('FCP', report.value, getRating('FCP', report.value));
  });
}