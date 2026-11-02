import { apiFetch } from "./authApi";

export type LeadStatus = "new" | "contacted" | "qualified" | "disqualified";

export interface LeadRecord {
  id: string;
  companyName: string;
  contactPerson: string;
  corporateEmail: string;
  phone: string;
  website: string | null;
  countryOperation: string;
  productType: string;
  monthlyVolume: string;
  services: string[];
  other3pl: string;
  comments: string;
  privacyPolicy: boolean;
  status: LeadStatus;
  createdAt: string;
  updatedAt: string;
}

export async function listLeads(): Promise<LeadRecord[]> {
  const response = await apiFetch("/leads");
  if (!response.ok) throw new Error("No se pudieron cargar los prospectos.");
  return (await response.json()) as LeadRecord[];
}

export async function updateLeadStatus(id: string, status: LeadStatus): Promise<LeadRecord> {
  const response = await apiFetch(`/leads/${encodeURIComponent(id)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  if (!response.ok) throw new Error("No se pudo actualizar el estado del prospecto.");
  return (await response.json()) as LeadRecord;
}

export async function deleteLead(id: string): Promise<void> {
  const response = await apiFetch(`/leads/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!response.ok) throw new Error("No se pudo eliminar el prospecto.");
}
