"use client";

import { useState } from "react";

interface KnowledgeResponse {
  answer: string;
}

export default function KnowledgePage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!question.trim()) return;

    setLoading(true);
    setError(null);
    setAnswer("");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/knowledge/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question: question.trim() }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(
          errorData?.detail || `Error ${response.status}: ${response.statusText}`
        );
      }

      const data: KnowledgeResponse = await response.json();
      setAnswer(data.answer);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Error desconocido al consultar la base de conocimiento"
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">
          📚 Base de Conocimiento TrackFlow
        </h1>
        <p className="mt-2 text-slate-600">
          Consulta la base de conocimiento de TrackFlow en lenguaje natural.
          Recibe respuestas sobre políticas, procedimientos, servicios y más.
        </p>
      </div>

      {/* Question Form */}
      <form onSubmit={handleSubmit} className="mb-8">
        <div className="flex gap-3">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ej: ¿Cuál es la política de devoluciones de TrackFlow?"
            disabled={loading}
            className="flex-1 rounded-lg border border-slate-300 px-4 py-3 text-slate-900 placeholder:text-slate-400 focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="rounded-lg bg-cyan-600 px-6 py-3 font-medium text-white transition hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg
                  className="h-5 w-5 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Consultando...
              </span>
            ) : (
              "Consultar"
            )}
          </button>
        </div>
      </form>

      {/* Error State */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
          <p className="font-medium">⚠️ Error</p>
          <p className="mt-1 text-sm">{error}</p>
        </div>
      )}

      {/* Answer */}
      {answer && (
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Respuesta
          </h2>
          <div className="prose prose-slate max-w-none whitespace-pre-wrap text-slate-800">
            {answer}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!loading && !answer && !error && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <p className="text-slate-500">
            Escribe una pregunta sobre las políticas, procedimientos o servicios
            de TrackFlow para recibir una respuesta.
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {[
              "¿Cómo funciona el proceso de devoluciones?",
              "¿Qué transportistas usa TrackFlow en España?",
              "¿Cuáles son los SLAs de entrega?",
              "¿Cómo se calcula el almacenaje?",
            ].map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setQuestion(example)}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-600 transition hover:border-cyan-300 hover:text-cyan-700"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
