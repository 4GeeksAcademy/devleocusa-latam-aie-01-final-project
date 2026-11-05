'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Alert } from '../../components/ui/Alert';
import { Spinner } from '../../components/ui/Spinner';
import { apiFetch, changePassword, getCurrentUser, getSessionToken, logout } from '../../../services/authApi';
import type { CurrentUser } from '../../../services/authApi';

/* ── Perfil ─────────────────────────────────────────── */

interface ProfileFormValues {
  email: string;
  name: string;
  phone: string;
  address: string;
}

interface AuthMeResponse {
  email?: string;
  profile?: {
    name?: string | null;
    phone?: string | null;
    address?: string | null;
  } | null;
}

interface ProfileUpdateResponse {
  name?: string | null;
  phone?: string | null;
  address?: string | null;
}

const ROLE_LABELS: Record<string, string> = {
  manager: 'Manager',
  admin: 'Administrador',
  user: 'Usuario',
  viewer: 'Visor',
};

function roleLabel(role: string): string {
  return ROLE_LABELS[role] || role;
}

function normalizeField(value: string | null | undefined): string {
  return value?.trim() || '';
}

function getProfileValues(payload: AuthMeResponse): ProfileFormValues {
  return {
    email: payload.email || '',
    name: normalizeField(payload.profile?.name),
    phone: normalizeField(payload.profile?.phone),
    address: normalizeField(payload.profile?.address),
  };
}

function getReadableErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return 'Ocurrió un error inesperado. Intenta nuevamente.';
}

async function parseApiError(response: Response, fallback: string): Promise<string> {
  try {
    const errorData = (await response.json()) as { message?: string; detail?: string; error?: string };
    return errorData.message || errorData.detail || errorData.error || fallback;
  } catch {
    return fallback;
  }
}

/* ── Componente principal ───────────────────────────── */

export default function AccountUserPage() {
  const [activeTab, setActiveTab] = useState<'profile' | 'security'>('profile');

  // Perfil ─ estado
  const [profileValues, setProfileValues] = useState<ProfileFormValues>({
    email: '', name: '', phone: '', address: '',
  });
  const [draftValues, setDraftValues] = useState<ProfileFormValues>({
    email: '', name: '', phone: '', address: '',
  });
  const [isEditing, setIsEditing] = useState(false);
  const [isLoadingProfile, setIsLoadingProfile] = useState(true);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Seguridad ─ estado
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSubmittingPassword, setIsSubmittingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);

  // Rol (solo lectura)
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);

  /* Cargar perfil + rol al montar */
  useEffect(() => {
    let isMounted = true;

    const load = async () => {
      if (!getSessionToken()) {
        logout();
        return;
      }

      try {
        // Cargamos el rol desde /auth/me que ya incluye { email, role }
        const [meResponse] = await Promise.all([
          apiFetch('/auth/me', { method: 'GET' }),
        ]);

        if (meResponse.status === 401) return;

        if (!meResponse.ok) {
          const msg = await parseApiError(meResponse, 'No fue posible cargar los datos de tu cuenta.');
          throw new Error(msg);
        }

        const mePayload = (await meResponse.json()) as AuthMeResponse & { role?: string };

        if (isMounted) {
          const vals = getProfileValues(mePayload);
          setProfileValues(vals);
          setDraftValues(vals);
          setProfileError(null);
          setCurrentUser({
            email: mePayload.email || '',
            role: mePayload.role || 'user',
          });
        }
      } catch (error) {
        if (isMounted) setProfileError(getReadableErrorMessage(error));
      } finally {
        if (isMounted) setIsLoadingProfile(false);
      }
    };

    load();
    return () => { isMounted = false; };
  }, [reloadKey]);

  /* Perfil ─ cambios pendientes */
  const hasUnsavedChanges = useMemo(() => (
    profileValues.name !== draftValues.name ||
    profileValues.phone !== draftValues.phone ||
    profileValues.address !== draftValues.address
  ), [profileValues, draftValues]);

  const handleChange = (field: keyof ProfileFormValues, value: string) => {
    setDraftValues((prev) => ({ ...prev, [field]: value }));
  };

  const handleEdit = () => {
    setProfileSuccess(null);
    setProfileError(null);
    setDraftValues(profileValues);
    setIsEditing(true);
  };

  const handleCancel = () => {
    setDraftValues(profileValues);
    setIsEditing(false);
    setProfileError(null);
  };

  const handleProfileSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isEditing || !getSessionToken()) return;

    setIsSavingProfile(true);
    setProfileError(null);
    setProfileSuccess(null);

    try {
      const response = await apiFetch('/profiles/me', {
        method: 'PUT',
        body: JSON.stringify({
          name: draftValues.name.trim(),
          phone: draftValues.phone.trim(),
          address: draftValues.address.trim(),
        }),
      });

      if (response.status === 401) return;
      if (!response.ok) {
        const msg = await parseApiError(response, 'No fue posible actualizar tus datos de perfil.');
        throw new Error(msg);
      }

      const updated = (await response.json()) as ProfileUpdateResponse;
      const updatedValues: ProfileFormValues = {
        email: profileValues.email,
        name: normalizeField(updated.name),
        phone: normalizeField(updated.phone),
        address: normalizeField(updated.address),
      };
      setProfileValues(updatedValues);
      setDraftValues(updatedValues);
      setIsEditing(false);
      setProfileSuccess('Perfil actualizado correctamente.');
    } catch (error) {
      setProfileError(getReadableErrorMessage(error));
    } finally {
      setIsSavingProfile(false);
    }
  };

  /* Seguridad ─ cambio de contraseña */
  const clearPasswordForm = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
  };

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmittingPassword) return;

    if (newPassword.length < 8) {
      setPasswordError('La contraseña nueva debe tener al menos 8 caracteres.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('La confirmación de la nueva contraseña no coincide.');
      return;
    }
    if (currentPassword === newPassword) {
      setPasswordError('La nueva contraseña debe ser diferente de la actual.');
      return;
    }

    setIsSubmittingPassword(true);
    setPasswordError(null);
    setPasswordSuccess(null);

    try {
      await changePassword({ currentPassword, newPassword });
      clearPasswordForm();
      setPasswordSuccess('Contraseña actualizada correctamente.');
    } catch (error) {
      setPasswordError((error as Error).message || 'No fue posible cambiar la contraseña.');
    } finally {
      setIsSubmittingPassword(false);
    }
  };

  /* ── Render ──────────────────────────────────────────── */

  return (
    <section className="mx-auto w-full max-w-2xl space-y-6">
      {/* Cabecera */}
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Mi usuario</h2>
        <p className="text-sm text-slate-600">
          Consulta y edita tu perfil, y administra tu contraseña desde un solo lugar.
        </p>
      </header>

      {/* Tarjeta de información del usuario (rol visible, no editable) */}
      {currentUser && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-cyan-100 text-lg font-bold text-cyan-800">
              {currentUser.email.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900">{currentUser.email}</p>
              <span className="inline-block mt-0.5 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                {roleLabel(currentUser.role)}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 rounded-xl bg-slate-100 p-1" role="tablist" aria-label="Secciones de usuario">
        <button
          role="tab"
          aria-selected={activeTab === 'profile'}
          onClick={() => setActiveTab('profile')}
          className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition ${
            activeTab === 'profile'
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-600 hover:text-slate-800'
          }`}
        >
          Perfil
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'security'}
          onClick={() => setActiveTab('security')}
          className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition ${
            activeTab === 'security'
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-600 hover:text-slate-800'
          }`}
        >
          Seguridad
        </button>
      </div>

      {/* Tab: Perfil */}
      {activeTab === 'profile' && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {isLoadingProfile ? (
            <div className="flex min-h-48 items-center justify-center">
              <Spinner label="Cargando perfil..." />
            </div>
          ) : (
            <form onSubmit={handleProfileSubmit} className="space-y-4" noValidate>
              <div className="space-y-1">
                <label htmlFor="email" className="text-sm font-medium text-slate-700">Email</label>
                <input
                  id="email" name="email" type="email"
                  value={profileValues.email} disabled
                  className="w-full rounded-md border border-slate-200 bg-slate-100 px-3 py-2 text-sm text-slate-500"
                />
              </div>

              <div className="space-y-1">
                <label htmlFor="name" className="text-sm font-medium text-slate-700">Nombre</label>
                <input
                  id="name" name="name" type="text" autoComplete="name"
                  disabled={!isEditing || isSavingProfile}
                  value={draftValues.name}
                  onChange={(e) => handleChange('name', e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-100"
                  placeholder="Tu nombre"
                />
              </div>

              <div className="space-y-1">
                <label htmlFor="phone" className="text-sm font-medium text-slate-700">Teléfono</label>
                <input
                  id="phone" name="phone" type="tel" autoComplete="tel"
                  disabled={!isEditing || isSavingProfile}
                  value={draftValues.phone}
                  onChange={(e) => handleChange('phone', e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-100"
                  placeholder="+1 555 123 4567"
                />
              </div>

              <div className="space-y-1">
                <label htmlFor="address" className="text-sm font-medium text-slate-700">Dirección</label>
                <input
                  id="address" name="address" type="text" autoComplete="street-address"
                  disabled={!isEditing || isSavingProfile}
                  value={draftValues.address}
                  onChange={(e) => handleChange('address', e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-100"
                  placeholder="Dirección de contacto"
                />
              </div>

              {profileError ? (
                <Alert variant="error" title="Error de perfil">
                  <div className="space-y-3">
                    <p>{profileError}</p>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" onClick={() => setReloadKey((k) => k + 1)}
                        className="rounded-md border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-100"
                      >Reintentar</button>
                    </div>
                  </div>
                </Alert>
              ) : null}

              {profileSuccess ? (
                <Alert variant="success" title="Cambios guardados">{profileSuccess}</Alert>
              ) : null}

              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                {isEditing ? (
                  <>
                    <button type="button" onClick={handleCancel} disabled={isSavingProfile}
                      className="inline-flex items-center justify-center rounded-md border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-70"
                    >Cancelar</button>
                    <button type="submit" disabled={isSavingProfile || !hasUnsavedChanges}
                      className="inline-flex items-center justify-center rounded-md bg-sky-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-70"
                    >{isSavingProfile ? 'Guardando...' : 'Guardar cambios'}</button>
                  </>
                ) : (
                  <button type="button" onClick={handleEdit}
                    className="inline-flex items-center justify-center rounded-md bg-sky-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-sky-800"
                  >Editar perfil</button>
                )}
              </div>
            </form>
          )}
        </div>
      )}

      {/* Tab: Seguridad */}
      {activeTab === 'security' && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <form onSubmit={handlePasswordSubmit} className="space-y-4" noValidate>
            <div className="space-y-1">
              <label htmlFor="current-password" className="text-sm font-medium text-slate-700">
                Contraseña actual
              </label>
              <input
                id="current-password" name="current-password" type="password"
                autoComplete="current-password" required
                disabled={isSubmittingPassword}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-100"
                placeholder="Ingresa tu contraseña actual"
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="new-password" className="text-sm font-medium text-slate-700">
                Nueva contraseña
              </label>
              <input
                id="new-password" name="new-password" type="password"
                autoComplete="new-password" required minLength={8}
                disabled={isSubmittingPassword}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-100"
                placeholder="Al menos 8 caracteres"
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="confirm-password" className="text-sm font-medium text-slate-700">
                Confirmar nueva contraseña
              </label>
              <input
                id="confirm-password" name="confirm-password" type="password"
                autoComplete="new-password" required minLength={8}
                disabled={isSubmittingPassword}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-100"
                placeholder="Repite la nueva contraseña"
              />
            </div>

            {passwordError ? (
              <Alert variant="error" title="No se pudo cambiar la contraseña">{passwordError}</Alert>
            ) : null}

            {passwordSuccess ? (
              <Alert variant="success" title="Contraseña actualizada">{passwordSuccess}</Alert>
            ) : null}

            <div className="flex justify-end">
              <button type="submit" disabled={isSubmittingPassword}
                className="inline-flex items-center justify-center rounded-md bg-sky-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-70"
              >{isSubmittingPassword ? 'Guardando...' : 'Cambiar contraseña'}</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}