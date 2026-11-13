import { redirect } from "next/navigation";

/**
 * `/operaciones` era un hub con cuatro enlaces que ya están en el sidebar, así
 * que no aportaba nada: un clic extra para llegar al mismo sitio.
 *
 * Se mantiene la ruta como redirección (en lugar de eliminarla) para que los
 * marcadores y enlaces antiguos sigan funcionando en vez de dar un 404.
 */
export default function OperacionesPage() {
  redirect("/operaciones/inventario");
}
