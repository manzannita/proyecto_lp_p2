/* Cliente de la API. Es el UNICO modulo del dashboard que hace fetch.
 *
 * Autenticacion: no hay ninguna clave en este archivo, ni la puede haber. El
 * servidor deja la API key en una cookie HttpOnly cuando entrega el dashboard
 * (ver backend/routes/dashboard.py), asi que aqui solo se pide
 * credentials: "same-origin" y el navegador la adjunta. Si la clave viviera en
 * el JavaScript, cualquiera la leeria en DevTools o en el codigo fuente.
 *
 * Cancelacion: cada llamada cancela la anterior de su misma "clave". Sin esto,
 * mover un filtro rapido deja varias peticiones en vuelo y una respuesta lenta
 * puede pintar datos viejos encima de los nuevos.
 */

const BASE = "/api";

/** Error con el status HTTP y el mensaje que mando el backend. */
export class ErrorDeApi extends Error {
  constructor(mensaje, status) {
    super(mensaje);
    this.name = "ErrorDeApi";
    this.status = status;
  }
}

/** Un AbortController en vuelo por clave de consulta. */
const enVuelo = new Map();

function armarQuery(parametros) {
  const query = new URLSearchParams();
  for (const [nombre, valor] of Object.entries(parametros)) {
    // Se omiten los vacios: mandar "desde=" haria que el backend intente
    // parsear una fecha vacia, y ademas ensucia la URL sin necesidad.
    if (valor === undefined || valor === null || valor === "") continue;
    query.set(nombre, String(valor));
  }
  return query.toString();
}

async function pedir(ruta, parametros = {}, clave = ruta) {
  enVuelo.get(clave)?.abort();
  const controlador = new AbortController();
  enVuelo.set(clave, controlador);

  const query = armarQuery(parametros);
  const url = query ? `${BASE}${ruta}?${query}` : `${BASE}${ruta}`;

  let respuesta;
  try {
    respuesta = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controlador.signal,
    });
  } catch (error) {
    // Un abort es una cancelacion deliberada, no una falla: se propaga tal cual
    // para que la vista lo ignore en vez de mostrar un error al usuario.
    if (error.name === "AbortError") throw error;
    throw new ErrorDeApi(
      "No se pudo contactar al servidor. Verifica que Flask esté corriendo.",
      0
    );
  } finally {
    if (enVuelo.get(clave) === controlador) enVuelo.delete(clave);
  }

  // El backend responde JSON en TODOS los codigos, incluidos los de error, asi
  // que el mensaje del cuerpo es el que hay que mostrarle al usuario.
  const cuerpo = await respuesta.json().catch(() => ({}));

  if (!respuesta.ok) {
    if (respuesta.status === 401) {
      throw new ErrorDeApi(
        "La sesión del dashboard expiró o no es válida. Recarga la página para renovarla.",
        401
      );
    }
    throw new ErrorDeApi(
      cuerpo.error || `El servidor respondió ${respuesta.status}.`,
      respuesta.status
    );
  }

  return cuerpo;
}

/* -------------------------------------------------------------------------
   Endpoints. Uno por pregunta de analisis, mas el catalogo y el buscador.
   ------------------------------------------------------------------------- */

/** Ranking de temas. Issue #6 (Annabella). */
export function obtenerTopTemas({ limite, desde, hasta, medio } = {}) {
  return pedir("/tendencias/top-temas", { limite, desde, hasta, medio }, "top-temas");
}

/** Catalogo de medios activos con su volumen recolectado. */
export function obtenerMedios() {
  return pedir("/medios", {}, "medios");
}

/** Distribucion tematica por medio. Issue #7 (Valentina). */
export function obtenerComparativa({ desde, hasta, temas, normalizar } = {}) {
  return pedir(
    "/medios/comparativa",
    {
      desde,
      hasta,
      // El backend espera "slug1,slug2"; aqui se acepta tambien un array.
      temas: Array.isArray(temas) ? temas.join(",") : temas,
      normalizar,
    },
    "comparativa"
  );
}

/** Serie semanal de un tema. Issue #8 (Cristian).
 *  Cada tema lleva su propia clave de cancelacion para poder comparar varios
 *  temas a la vez sin que se cancelen entre ellos. */
export function obtenerSeriesSemanales({ tema, desde, hasta, medio } = {}) {
  return pedir(
    "/tendencias/series-semanales",
    { tema, desde, hasta, medio },
    `series:${tema}`
  );
}

/** Buscador de noticias. Issue #8 (Cristian) - el endpoint aun no existe. */
export function buscarNoticias({ q, tema, medio, desde, hasta, pagina, porPagina } = {}) {
  return pedir(
    "/noticias",
    { q, tema, medio, desde, hasta, pagina, por_pagina: porPagina },
    "noticias"
  );
}
