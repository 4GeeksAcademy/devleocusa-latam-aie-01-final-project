import { AuthGuard } from "../../components/auth/AuthGuard";
import { IncidentsDashboard } from "../../components/incidents/IncidentsDashboard";

export default function IncidenciasPage() {
  return (
    <AuthGuard>
      <IncidentsDashboard />
    </AuthGuard>
  );
}
