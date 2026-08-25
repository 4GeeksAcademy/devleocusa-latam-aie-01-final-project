'use client';

import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getSessionToken, isTokenValid, clearSessionToken } from '../../../services/authApi';
import { Spinner } from '../ui/Spinner';
import { trackSessionExpired } from '../../../lib/instrumentation';

interface ProtectedRouteProps {
  children: ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const router = useRouter();
  const [canRender, setCanRender] = useState(false);
  const hasTrackedRef = useRef(false);

  useEffect(() => {
    const token = getSessionToken();

    if (!token || !isTokenValid(token)) {
      if (!hasTrackedRef.current) {
        hasTrackedRef.current = true;
        trackSessionExpired(0, 'token_expired');
      }
      clearSessionToken();
      router.replace('/login');
      return;
    }

    hasTrackedRef.current = false;

    const frameId = window.requestAnimationFrame(() => {
      setCanRender(true);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [router]);

  if (!canRender) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Verificando sesion..." />
      </div>
    );
  }

  return <>{children}</>;
}
