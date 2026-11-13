import type {
  IncidentCategory,
  IncidentOrigin,
  IncidentStatus,
} from "../services/incidentsApi";

/**
 * Etiquetas de presentación para los valores crudos que viajan entre el
 * backend y el frontend del gestor de incidencias.
 *
 * El backend sigue almacenando y devolviendo los mismos valores (snake_case o
 * con acentos omitidos); aquí solo transformamos lo que se muestra en PANTALLA
 * a un texto amigable en español, sin cambiar el payload de la API.
 */

export const INCIDENT_STATUS_LABELS: Record<IncidentStatus, string> = {
  open: "Abierto",
  in_progress: "En proceso",
  resolved: "Resuelto",
  discarded: "Descartado",
};

export const INCIDENT_CATEGORY_LABELS: Record<IncidentCategory, string> = {
  Almacen: "Almacén",
  Ultima_Milla: "Última Milla",
  Logistica_Inversa: "Logística Inversa",
  CX: "CX",
  Comercial: "Comercial",
  Tecnologia: "Tecnología",
};

export const INCIDENT_ORIGIN_LABELS: Record<IncidentOrigin, string> = {
  customer: "Cliente",
  branch: "Sucursal",
  internal: "Interno",
};

export function getIncidentStatusLabel(status: IncidentStatus): string {
  return INCIDENT_STATUS_LABELS[status];
}

export function getIncidentCategoryLabel(category: IncidentCategory): string {
  return INCIDENT_CATEGORY_LABELS[category];
}

export function getIncidentOriginLabel(origin: IncidentOrigin): string {
  return INCIDENT_ORIGIN_LABELS[origin];
}

/**
 * Traduce cualquier clave (estado, categoría u origen) a su etiqueta amigable.
 * Útil cuando se itera sobre mapas genéricos (resúmenes, análisis) en los que
 * el tipo exacto no se conoce en tiempo de compilación. Si la clave no es una
 * de las conocidas, "humaniza" el valor: quita snake_case y capitaliza.
 */
export function getIncidentDisplayLabel(key: string): string {
  if (key in INCIDENT_STATUS_LABELS) {
    return INCIDENT_STATUS_LABELS[key as IncidentStatus];
  }

  if (key in INCIDENT_CATEGORY_LABELS) {
    return INCIDENT_CATEGORY_LABELS[key as IncidentCategory];
  }

  if (key in INCIDENT_ORIGIN_LABELS) {
    return INCIDENT_ORIGIN_LABELS[key as IncidentOrigin];
  }

  return key.replace(/_/g, " ").replace(/\b\w/g, (word) => word.toUpperCase());
}