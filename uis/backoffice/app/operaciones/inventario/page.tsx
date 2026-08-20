import dynamic from "next/dynamic";
import { AuthGuard } from "../../components/auth/AuthGuard";

const InventoryDashboard = dynamic(
  () => import("../../components/inventory/InventoryDashboard").then((mod) => mod.InventoryDashboard),
  {
    loading: () => (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-300 border-t-cyan-600" />
      </div>
    ),
  },
);

export default function InventarioPage() {
  return (
    <AuthGuard>
      <InventoryDashboard />
    </AuthGuard>
  );
}