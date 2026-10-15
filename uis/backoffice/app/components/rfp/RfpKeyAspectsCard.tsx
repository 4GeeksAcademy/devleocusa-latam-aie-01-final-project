import type { RFPKeyAspects } from "../../../services/rfpApi";

function BulletList({ items, empty }: { items: string[]; empty: string }) {
  if (!items || items.length === 0) {
    return <p className="text-sm text-slate-400 italic">{empty}</p>;
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}

export default function RfpKeyAspectsCard({ aspects }: { aspects: RFPKeyAspects | null }) {
  if (!aspects) {
    return <p className="text-sm text-slate-400 italic">Sin aspectos clave.</p>;
  }

  return (
    <div className="space-y-4">
      {aspects.resumen_requisitos && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Resumen de requisitos
          </h4>
          <p className="text-sm text-slate-800">{aspects.resumen_requisitos}</p>
        </div>
      )}

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Cifras citadas (literales)
        </h4>
        {aspects.cifras_citadas && aspects.cifras_citadas.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {aspects.cifras_citadas.map((cifra, index) => (
              <li key={index} className="text-slate-800">
                <span className="rounded bg-sky-50 px-1.5 py-0.5 font-mono text-xs font-semibold text-sky-800">
                  {cifra.valor}
                </span>
                {cifra.contexto && (
                  <span className="ml-2 text-slate-500">— {cifra.contexto}</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400 italic">No se citaron cifras.</p>
        )}
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Entregables
        </h4>
        <BulletList items={aspects.entregables ?? []} empty="Sin entregables definidos." />
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Restricciones y exclusiones
        </h4>
        <BulletList
          items={aspects.restricciones_exclusiones ?? []}
          empty="Sin restricciones explícitas."
        />
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Datos ausentes (no inventados)
        </h4>
        <BulletList
          items={aspects.missing_data ?? []}
          empty="Nada faltante declarado."
        />
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Preguntas abiertas
        </h4>
        <BulletList
          items={aspects.preguntas_abiertas ?? []}
          empty="Sin preguntas abiertas."
        />
      </div>
    </div>
  );
}
