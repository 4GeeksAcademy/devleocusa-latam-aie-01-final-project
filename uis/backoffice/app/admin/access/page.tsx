"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/services/authApi";

type Department = { id: string; name: string; is_active: boolean };
type UserRecord = {
  id: number | string;
  email: string;
  role: "admin" | "manager" | "user" | "service";
  department: string | null;
  is_active: boolean;
};

const ROLES = [
  { value: "admin", label: "Admin" },
  { value: "manager", label: "Supervisor" },
  { value: "user", label: "Empleado" },
  { value: "service", label: "Servicio técnico" },
] as const;

export default function AccessAdministrationPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [departmentResponse, usersResponse] = await Promise.all([
        apiFetch("/users/departments"),
        apiFetch("/users"),
      ]);
      if (!departmentResponse.ok || !usersResponse.ok) {
        throw new Error("No se pudo cargar la administración de accesos. Verifica que tengas permisos de Admin.");
      }
      setDepartments(await departmentResponse.json());
      setUsers(await usersResponse.json());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Error al cargar datos.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    queueMicrotask(() => { void load(); });
  }, []);

  async function updateAccess(user: UserRecord, role: UserRecord["role"], department: string) {
    setSavingId(String(user.id));
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`/users/${user.id}`, {
        method: "PUT",
        body: JSON.stringify({ role, department: department || null }),
      });
      if (!response.ok) throw new Error("El servidor rechazó el cambio de acceso.");
      setNotice(`Acceso actualizado para ${user.email}.`);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo guardar el cambio.");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <section className="mx-auto max-w-6xl space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-wide text-cyan-700">Administración</p>
        <h1 className="mt-1 text-3xl font-bold text-slate-900">Roles y departamentos</h1>
        <p className="mt-2 text-slate-600">El rol define capacidades y el departamento delimita el acceso a los datos.</p>
      </header>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</p>}
      {notice && <p role="status" className="rounded-lg bg-green-50 p-4 text-green-800">{notice}</p>}
      {loading ? <p className="text-slate-600">Cargando…</p> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-slate-50 text-slate-700">
              <tr><th className="p-4">Usuario</th><th className="p-4">Rol</th><th className="p-4">Departamento</th><th className="p-4">Acción</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((user) => (
                <AccessRow key={user.id} user={user} departments={departments} saving={savingId === String(user.id)} onSave={updateAccess} />
              ))}
            </tbody>
          </table>
          {users.length === 0 && <p className="p-6 text-slate-600">No hay usuarios.</p>}
        </div>
      )}
    </section>
  );
}

function AccessRow({
  user,
  departments,
  saving,
  onSave,
}: {
  user: UserRecord;
  departments: Department[];
  saving: boolean;
  onSave: (user: UserRecord, role: UserRecord["role"], department: string) => Promise<void>;
}) {
  const [role, setRole] = useState<UserRecord["role"]>(user.role);
  const [department, setDepartment] = useState(user.department ?? "");
  return (
    <tr>
      <td className="p-4"><span className="font-medium text-slate-900">{user.email}</span><span className="mt-1 block text-xs text-slate-500">ID: {user.id}</span></td>
      <td className="p-4"><select aria-label={`Rol de ${user.email}`} className="rounded-md border border-slate-300 p-2" value={role} onChange={(event) => setRole(event.target.value as UserRecord["role"])}>{ROLES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></td>
      <td className="p-4"><select aria-label={`Departamento de ${user.email}`} className="w-full rounded-md border border-slate-300 p-2" value={department} onChange={(event) => setDepartment(event.target.value)}><option value="">Sin asignar</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></td>
      <td className="p-4"><button type="button" disabled={saving} onClick={() => void onSave(user, role, department)} className="rounded-md bg-slate-900 px-3 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-50">{saving ? "Guardando…" : "Guardar"}</button></td>
    </tr>
  );
}
