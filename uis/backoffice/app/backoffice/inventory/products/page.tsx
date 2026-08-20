import dynamic from "next/dynamic";
import { AuthGuard } from "@/app/components/auth/AuthGuard";

const ProductsListPanel = dynamic(
  () => import("@/app/components/inventory/ProductsListPanel").then((mod) => mod.ProductsListPanel),
  {
    loading: () => (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-300 border-t-cyan-600" />
      </div>
    ),
  },
);

export default function ProductsPage() {
  return (
    <AuthGuard>
      <ProductsListPanel />
    </AuthGuard>
  );
}