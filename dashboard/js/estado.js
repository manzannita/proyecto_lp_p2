/* Estado global de los filtros, sincronizado con la URL.
 *
 * Los filtros viven en el query string (?desde=&hasta=&medio=) y la vista
 * activa en el hash (#/tendencias). Asi recargar la pagina o compartir el
 * enlace conserva el analisis exacto, que es lo minimo que se espera de un
 * dashboard: un grafico que no se puede volver a encontrar no sirve para
 * sustentar nada.
 *
 * Es un store minimo a proposito: tres campos y suscriptores. No hace falta
 * una libreria de estado para esto.
 */

const CAMPOS = ["desde", "hasta", "medio"];

const suscriptores = new Set();

function leerDeUrl() {
  const params = new URLSearchParams(window.location.search);
  const filtros = {};
  for (const campo of CAMPOS) {
    filtros[campo] = (params.get(campo) || "").trim();
  }
  return filtros;
}

let filtros = leerDeUrl();

/** Copia de los filtros actuales. Se devuelve una copia para que nadie los
 *  mute por fuera de actualizar(). */
export function obtener() {
  return { ...filtros };
}

/** Motivo por el que los filtros actuales no son consultables, o null.
 *  Se valida en el cliente para dar el aviso al instante en vez de esperar
 *  el 400 del backend. */
export function validar(candidatos = filtros) {
  const { desde, hasta } = candidatos;
  if (desde && hasta && desde > hasta) {
    // Las fechas son ISO (YYYY-MM-DD), asi que comparar como texto es correcto.
    return "La fecha 'desde' no puede ser posterior a 'hasta'.";
  }
  return null;
}

function escribirEnUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const campo of CAMPOS) {
    if (filtros[campo]) {
      params.set(campo, filtros[campo]);
    } else {
      params.delete(campo);
    }
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  // replaceState y no pushState: mover un filtro no deberia llenar el historial
  // de entradas por las que el boton "atras" tenga que pasar una por una.
  window.history.replaceState(null, "", url);
}

/** Aplica un cambio parcial, lo refleja en la URL y avisa a las vistas. */
export function actualizar(parcial) {
  let cambio = false;
  for (const campo of CAMPOS) {
    if (!(campo in parcial)) continue;
    const valor = (parcial[campo] ?? "").trim();
    if (valor !== filtros[campo]) {
      filtros[campo] = valor;
      cambio = true;
    }
  }
  if (!cambio) return;

  escribirEnUrl();
  for (const suscriptor of suscriptores) suscriptor(obtener());
}

/** Suscribe una funcion a los cambios de filtro. Devuelve como desuscribirse. */
export function suscribir(callback) {
  suscriptores.add(callback);
  return () => suscriptores.delete(callback);
}
