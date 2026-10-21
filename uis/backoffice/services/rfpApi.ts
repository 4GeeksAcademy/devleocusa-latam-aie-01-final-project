import { apiFetch, getSessionToken } from "./authApi";

// Types mirroring the FastAPI schemas in services/api/src/routes/rfp_router.py

export type RFPStatus =
  | "analizando"
  | "analisis_completo"
  | "descartado"
  | "generando_borrador"
  | "en_evaluación"
  | "needs_human_review"
  | "esperando_aprobación"
  | "terminado";

export interface RFPUploadResponse {
  ticket_id: string;
  status: string;
  detail: string;
}

export interface RFPTicketSummary {
  id: string;
  status: RFPStatus;
  original_filename: string;
  created_at: string;
  updated_at: string;
  classification_reason: string | null;
  error_detail: string | null;
}

/** Flat data payload for the named ``rfp_ticket_created`` SSE event. */
export interface RfpTicketCreatedEvent {
  ticket_id: string;
  rfp_id: string | null;
  client_name: string | null;
  client_country: string | null;
  services_requested: string[];
  status: "analyzing";
  created_at: string;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/** Connect to the authenticated event stream and consume named SSE frames. */
export async function streamRfpTicketEvents(
  onTicketCreated: (event: RfpTicketCreatedEvent) => void,
  signal: AbortSignal,
  onConnected?: () => void | Promise<void>,
): Promise<void> {
  const token = getSessionToken();
  if (!token) throw new Error("No hay una sesión autenticada para SSE.");

  const response = await fetch(`${API_BASE_URL}/rfp/events`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`SSE respondió ${response.status}.`);
  if (!response.body) throw new Error("El servidor no abrió el stream SSE.");
  await onConnected?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";
  let dataLines: string[] = [];

  const dispatch = () => {
    if (currentEvent === "rfp_ticket_created" && dataLines.length > 0) {
      const payload = JSON.parse(dataLines.join("\n")) as RfpTicketCreatedEvent;
      if (
        typeof payload.ticket_id === "string" &&
        payload.status === "analyzing" &&
        Array.isArray(payload.services_requested)
      ) onTicketCreated(payload);
    }
    currentEvent = "";
    dataLines = [];
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of frame.split("\n")) {
          if (line.startsWith(":")) continue;
          const colon = line.indexOf(":");
          const field = colon < 0 ? line : line.slice(0, colon);
          const valueText = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
          if (field === "event") currentEvent = valueText;
          else if (field === "data") dataLines.push(valueText);
        }
        dispatch();
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

export interface RFPDocumentOut {
  title: string | null;
  issuing_organization: string | null;
  rfp_reference: string | null;
  proposal_due_date: string | null;
  contact_name: string | null;
  contact_email: string | null;
  detected_language: string | null;
  word_count: number | null;
  flesch_kincaid_grade: number | null;
  gunning_fog_index: number | null;
  coleman_liau_index: number | null;
  estimated_token_cost: number | null;
}

export interface RFPCifraCitada {
  valor: string;
  contexto: string;
}

export interface RFPKeyAspects {
  resumen_requisitos?: string;
  entregables?: string[];
  cifras_citadas?: RFPCifraCitada[];
  restricciones_exclusiones?: string[];
  preguntas_abiertas?: string[];
  missing_data?: string[];
  prioridad?: string;
}

export interface RFPArtifactOut {
  department: string;
  contact_name: string | null;
  contact_role: string | null;
  status: string;
  worker_error: string | null;
  key_aspects: RFPKeyAspects | null;
  proposal_draft: string | null;
  evaluation_result: EvaluationResult | null;
  iteration_count: number;
  department_id: string | null;
  approval_status: string;
  approver: string | null;
  approval_comment: string | null;
  approved_at: string | null;
  approval_iteration_count: number;
}

export interface EvaluationResult {
  section_id: string;
  department_id: string;
  readability: { pass: boolean; score: number; details: string };
  relevance: { pass: boolean; missing_aspects: string[] };
  compliance: { pass: boolean; rule_ids: string[]; violations: string[] };
  overall_pass: boolean;
  feedback_for_generator: string;
}

export interface RFPTicketDetail extends RFPTicketSummary {
  is_rfp: boolean | null;
  classification_confidence: number | null;
  markdown_path: string | null;
  synthesis_summary: string | null;
  dispatched_at: string | null;
  proposal_completed_at: string | null;
  document: RFPDocumentOut | null;
  sections: RFPArtifactOut[];
  handoff_payload: Record<string, unknown> | null;
  final_document_available: boolean;
}

export const RFP_STATUS_LABELS: Record<RFPStatus, string> = {
  analizando: "Analizando",
  analisis_completo: "Análisis completo",
  descartado: "Descartado",
  generando_borrador: "Generando borrador",
  "en_evaluación": "En evaluación",
  needs_human_review: "Revisión humana requerida",
  "esperando_aprobación": "Esperando aprobación",
  terminado: "Terminado",
};

export const DEPARTMENT_LABELS: Record<string, string> = {
  warehouse: "Almacén",
  lastmile: "Última milla",
  reverse: "Devoluciones",
  operaciones_almacen: "Operaciones de Almacén",
  ultima_milla_transportistas: "Última Milla y Gestión de Transportistas",
  logistica_inversa: "Logística Inversa",
  experiencia_cliente: "Experiencia del Cliente (CX)",
  comercial_cuentas: "Comercial y Relación con Clientes",
  tecnologia: "Tecnología",
  direccion_ejecutiva: "Dirección Ejecutiva",
};

export function departmentLabel(key: string): string {
  return DEPARTMENT_LABELS[key] ?? key;
}

async function parseJson<T>(response: Response): Promise<T | null> {
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function uploadRfp(file: File): Promise<RFPUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await apiFetch("/rfp/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const payload = await parseJson<{ detail?: string }>(response);
    throw new Error(
      payload?.detail || `Error ${response.status}: no se pudo subir el PDF.`
    );
  }

  const data = await parseJson<RFPUploadResponse>(response);
  if (!data) {
    throw new Error("El servidor no devolvió un ticket válido.");
  }
  return data;
}

export async function listRfpTickets(
  status?: RFPStatus
): Promise<RFPTicketSummary[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const response = await apiFetch(`/rfp/tickets${query}`);

  if (!response.ok) {
    throw new Error(`Error ${response.status}: no se pudo listar los tickets.`);
  }

  const data = await parseJson<RFPTicketSummary[]>(response);
  return data ?? [];
}

export async function getRfpTicket(id: string): Promise<RFPTicketDetail> {
  const response = await apiFetch(`/rfp/tickets/${encodeURIComponent(id)}`);

  if (response.status === 404) {
    throw new Error("Ticket no encontrado.");
  }
  if (!response.ok) {
    throw new Error(`Error ${response.status}: no se pudo cargar el ticket.`);
  }

  const data = await parseJson<RFPTicketDetail>(response);
  if (!data) {
    throw new Error("El servidor no devolvió el detalle del ticket.");
  }
  return data;
}

export async function submitRfpDecision(
  ticketId: string,
  departmentId: string,
  decision: "approve" | "reject" | "request_changes",
  comment = ""
): Promise<void> {
  const response = await apiFetch(
    `/rfp/tickets/${encodeURIComponent(ticketId)}/departments/${encodeURIComponent(departmentId)}/decision`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, comment }) }
  );
  if (!response.ok) {
    const payload = await parseJson<{ detail?: string }>(response);
    throw new Error(payload?.detail || `Error ${response.status}: no se pudo guardar la decisión.`);
  }
}

export async function getRfpFinalDocument(ticketId: string): Promise<{ sections: { department_id: string; text: string }[]; currency: string; generated_at: string }> {
  const response = await apiFetch(`/rfp/tickets/${encodeURIComponent(ticketId)}/final-document`);
  if (!response.ok) throw new Error(`Error ${response.status}: documento final no disponible.`);
  const data = await parseJson<{ sections: { department_id: string; text: string }[]; currency: string; generated_at: string }>(response);
  if (!data) throw new Error("Respuesta de documento final inválida.");
  return data;
}
