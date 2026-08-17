"use client";

import { AuthGuard } from "../../components/auth/AuthGuard";
import { InventoryDashboard } from "../../components/inventory/InventoryDashboard";

export default function InventarioPage() {
  return (
    <AuthGuard>
      <InventoryDashboard />
    </AuthGuard>
  );
}