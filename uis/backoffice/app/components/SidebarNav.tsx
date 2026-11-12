"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getCurrentUser } from "@/services/authApi";

type NavItem = {
  href: string;
  label: string;
  nested?: boolean;
};

const navItems: NavItem[] = [
  { href: "/", label: "Inicio" },
  { href: "/account/user", label: "Mi usuario" },
  { href: "/candidaturas", label: "Candidaturas" },
  { href: "/leads", label: "Prospectos" },
  { href: "/operaciones/inventario", label: "Inventario operativo" },
  { href: "/operaciones/proveedores", label: "Directorio de proveedores" },
  { href: "/operaciones/incidencias", label: "Gestión de incidencias" },
  { href: "/knowledge", label: "Base de conocimiento" },
  { href: "/rfp", label: "Recepción de RFPs" },
  { href: "/telemetry", label: "Radar de telemetría" },
  { href: "/reporting", label: "Reporting ejecutivo" },
];

export function SidebarNav() {
  const pathname = usePathname();
  const [canManageLeads, setCanManageLeads] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    getCurrentUser()
      .then((user) => {
        if (active) {
          setCanManageLeads(user.role === "manager");
        }
      })
      .catch(() => {
        if (active) {
          setCanManageLeads(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const visibleItems = navItems.filter((item) => {
    if (item.href === "/leads") return canManageLeads === true;
    return true;
  });

  return (
    <nav aria-label="Navegación del dashboard">
      <ul className="space-y-2 text-sm">
        {visibleItems.map((item) => {
          const isActive = pathname === item.href;

          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={
                  isActive
                    ? `block rounded-lg py-2 pr-3 font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${item.nested ? "ml-3 border-l border-slate-600 pl-5" : "px-3"}`
                    : `block rounded-lg py-2 pr-3 text-slate-300 hover:bg-slate-800 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${item.nested ? "ml-3 border-l border-slate-600 pl-5" : "px-3"}`
                }
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
