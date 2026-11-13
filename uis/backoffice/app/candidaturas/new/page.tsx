import Link from 'next/link';
import { CandidateForm } from '../../components/candidates/CandidateForm';

export default function NewCandidatePage() {
  return (
    <section className="space-y-4">
      <Link
        href="/candidaturas"
        className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
        </svg>
        Volver al listado de candidatos
      </Link>

      <header>
        <h2 className="text-xl font-semibold text-slate-900">Nueva candidatura</h2>
        <p className="mt-1 text-sm text-slate-600">Completa todos los campos para dar de alta al candidato.</p>
      </header>

      <CandidateForm mode="create" />
    </section>
  );
}
