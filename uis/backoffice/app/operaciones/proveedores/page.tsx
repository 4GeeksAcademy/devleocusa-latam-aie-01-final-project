import { AuthGuard } from "../../components/auth/AuthGuard";
import { SuppliersDirectoryPanel } from "../../components/SuppliersDirectoryPanel";

export default function ProveedoresPage() {
  return (
    <AuthGuard>
      <SuppliersDirectoryPanel />
    </AuthGuard>
  );
}