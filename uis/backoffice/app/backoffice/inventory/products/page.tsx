import { AuthGuard } from "@/app/components/auth/AuthGuard";
import { ProductsListPanel } from "@/app/components/inventory/ProductsListPanel";

export default function ProductsPage() {
  return (
    <AuthGuard>
      <ProductsListPanel />
    </AuthGuard>
  );
}