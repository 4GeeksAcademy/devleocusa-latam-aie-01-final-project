import dynamic from "next/dynamic";
import { AuthGuard } from "../../components/auth/AuthGuard";

const IncidentsDashboard = dynamic(
  () => import("../../components/incidents/IncidentsDashboard").then((mod) => mod.IncidentsDashboard),
  {
    loading: () => (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-300 border-t-cyan-600" />
      </div>
    ),
  },
);

export default function IncidenciasPage() {
  return (
    <AuthGuard>
      <IncidentsDashboard />
    </AuthGuard>
  );
}
