import { apiFetch } from "./authApi";

// Types mirroring the FastAPI schemas in services/api/src/routes/rfp_router.py

export type RFPStatus =
  | "analizando"
  | "analisis_completo"
  | "descartado"
  | "generando_borrador"
  | "en_evaluación"
  | "needs_human_review";

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
}

export const RFP_STATUS_LABELS: Record<RFPStatus, string> = {
  analizando: "Analizando",
  analisis_completo: "Análisis completo",
  descartado: "Descartado",
  generando_borrador: "Generando borrador",
  "en_evaluación": "En evaluación",
  needs_human_review: "Revisión humana requerida",
};

export const DEPARTMENT_LABELS: Record<string, string> = {
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
