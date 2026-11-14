'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Alert } from '../components/ui/Alert';
import { exchangeFederatedLoginCode, login, setSessionToken } from '../../services/authApi';
import {
  trackLoginAttempt,
  trackLoginSuccess,
  trackLoginFailure,
} from '../../lib/instrumentation';

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isMicrosoftBusy, setIsMicrosoftBusy] = useState(false);
  const attemptRef = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('federated_code');
    const failure = params.get('federated_error');
    if (failure === 'account_not_linked') {
      setErrorMessage('Esta cuenta Microsoft no está vinculada a una cuenta TrackFlow. Solicita primero el alta por el canal de onboarding correspondiente.');
      window.history.replaceState({}, '', window.location.pathname);
      return;
    }
    if (failure) {
      setErrorMessage('No se pudo completar el inicio de sesión con Microsoft. Inténtalo de nuevo o utiliza otro método.');
      window.history.replaceState({}, '', window.location.pathname);
      return;
    }
    if (!code) return;
    setIsMicrosoftBusy(true);
    window.history.replaceState({}, '', window.location.pathname);
    void exchangeFederatedLoginCode(code)
      .then((token) => {
        setSessionToken(token);
        router.replace('/');
      })
      .catch((error: unknown) => setErrorMessage((error as Error).message || 'No fue posible iniciar sesión con Microsoft.'))
      .finally(() => setIsMicrosoftBusy(false));
  }, [router]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    setIsSubmitting(true);
    setErrorMessage(null);

    const trimmedEmail = email.trim();

    // Emit auth.login.attempt BEFORE the fetch — NO password captured
    // Per policy: user_password → NEVER_CAPTURED
    await trackLoginAttempt(trimmedEmail);

    try {
      const token = await login({ email: trimmedEmail, password });

      setSessionToken(token);

      // Emit auth.login.success after token is stored
      trackLoginSuccess();

      router.replace('/');
    } catch (error) {
      const message = (error as Error).message || 'No fue posible iniciar sesión.';
      setErrorMessage(message);

      // Map error messages to normalized failure_reason enum
      attemptRef.current += 1;
      let failureReason: 'invalid_credentials' | 'user_not_found' | 'account_locked' = 'invalid_credentials';

      if (message.includes('no encontrado') || message.includes('not found')) {
        failureReason = 'user_not_found';
      } else if (message.includes('bloqueada') || message.includes('locked')) {
        failureReason = 'account_locked';
      }

      trackLoginFailure(trimmedEmail, failureReason, attemptRef.current);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="flex min-h-[calc(100vh-4rem)] items-center justify-center py-8">
      <div className="w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-6 space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Iniciar sesión</h2>
          <p className="text-sm text-slate-600">
            Accede al Backoffice de TrackFlow.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-1">
            <label htmlFor="email" className="text-sm font-medium text-slate-700">
              Correo corporativo
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2"
              placeholder="nombre@trackflow.com"
            />
          </div>

          <div className="space-y-1">
            <label htmlFor="password" className="text-sm font-medium text-slate-700">
              Contraseña
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-sky-300 transition focus:border-sky-500 focus:ring-2"
              placeholder="Ingresa tu contraseña"
            />
            <div className="pt-1 text-right">
              <Link
                href="/forgot-password"
                className="text-xs font-medium text-sky-700 hover:text-sky-800 hover:underline"
              >
                Olvidé mi contraseña
              </Link>
            </div>
          </div>

          {errorMessage ? (
            <Alert variant="error" title="Error de autenticación">
              {errorMessage}
            </Alert>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex w-full items-center justify-center rounded-md bg-sky-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting ? 'Ingresando...' : 'Entrar al sistema'}
          </button>
        </form>

        <div className="my-4 flex items-center gap-3 text-xs text-slate-400" aria-hidden="true">
          <span className="h-px flex-1 bg-slate-200" />
          <span>o</span>
          <span className="h-px flex-1 bg-slate-200" />
        </div>
        <button
          type="button"
          disabled={isMicrosoftBusy || isSubmitting}
          onClick={() => {
            const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
            window.location.assign(`${apiBase.replace(/\/$/, '')}/auth/federated/microsoft/login`);
          }}
          className="inline-flex w-full items-center justify-center rounded-md border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isMicrosoftBusy ? 'Validando cuenta Microsoft...' : 'Iniciar sesión con Microsoft'}
        </button>

        <p className="mt-4 text-center text-sm text-slate-600">
          No tienes cuenta?{' '}
          <Link href="/register" className="font-medium text-sky-700 hover:text-sky-800 hover:underline">
            Regístrate
          </Link>
        </p>
      </div>
    </section>
  );
}
