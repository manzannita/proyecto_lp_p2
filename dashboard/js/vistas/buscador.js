/* Vista: buscador de noticias. Issue #8 - Cristian.
 *
 * Es el respaldo verificable del gráfico de evolución semanal: permite pasar
 * de un pico en la serie a las noticias concretas que lo produjeron. Todo el
 * contenido externo (titular, resumen) entra al DOM con textContent — nunca
 * innerHTML — porque viene de sitios que no controlamos.
 */

import * as api from "../api.js";
import * as estado from "../estado.js";
import {
  el,
  formatearFecha,
  limpiar,
  marcarCargando,
  mostrarCargando,
  mostrarError,
  mostrarVacio,
} from "../ui.js";

const CATALOGO_TEMAS = [
  { slug: "politica", nombre: "Política" },
  { slug: "economia", nombre: "Economía" },
  { slug: "seguridad", nombre: "Seguridad" },
  { slug: "salud", nombre: "Salud" },
  { slug: "deportes", nombre: "Deportes" },
  { slug: "clima", nombre: "Clima" },
  { slug: "internacional", nombre: "Internacional" },
  { slug: "otros", nombre: "Otros" },
];
const CATALOGO_MEDIOS = [
  { slug: "el-universo", nombre: "El Universo" },
  { slug: "primicias", nombre: "Primicias" },
];
const POR_PAGINA = 20;
const DEBOUNCE_MS = 300;

let contenedor = null;
let temporizadorDebounce = null;
let esPrimerRender = true;

// Filtros propios de esta vista (no son los globales de estado.js).
let q = "";
let tema = "";
let pagina = 1;

/* -------------------------------------------------------------------------
   Query string propio de la vista: tema, q y pagina.
   desde/hasta/medio ya los gestiona estado.js como filtros globales.
   ------------------------------------------------------------------------- */

function leerFiltrosPropiosDeUrl() {
  const params = new URLSearchParams(window.location.search);
  q = (params.get("q") || "").trim();
  tema = (params.get("tema") || "").trim();
  const paginaCruda = Number.parseInt(params.get("pagina") || "1", 10);
  pagina = Number.isFinite(paginaCruda) && paginaCruda >= 1 ? paginaCruda : 1;
}

function escribirFiltrosPropiosEnUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const [nombre, valor] of [["q", q], ["tema", tema], ["pagina", pagina > 1 ? String(pagina) : ""]]) {
    if (valor) params.set(nombre, valor);
    else params.delete(nombre);
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history.replaceState(null, "", url);
}

/* -------------------------------------------------------------------------
   Normalizacion para el resaltado: misma logica que el backend
   (backend/routes/noticias.py::_normalizar_texto), minusculas y sin tildes,
   caracter por caracter para que los indices queden alineados con el texto
   original y el resaltado no se corra.
   ------------------------------------------------------------------------- */

function normalizarCaracter(caracter) {
  return caracter.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function normalizarTexto(texto) {
  return Array.from(texto).map(normalizarCaracter).join("");
}

/**
 * Texto normalizado MAS el mapa de posiciones al texto original.
 *
 * Normalizar caracter por caracter no alcanza para mantener los indices
 * alineados, que es lo que el comentario de arriba daba por sentado: NFKD
 * EXPANDE algunos caracteres. "…" se convierte en "..." (+2) y "½" en "1⁄2"
 * (+2), y los puntos suspensivos son frecuentisimos en los resumenes de RSS
 * truncados. Con el desfase, el <mark> quedaba corrido:
 *
 *   "Alerta…crece la inseguridad"  buscando "seguridad"  ->  resaltaba "guridad e"
 *
 * y en el peor caso el cursor pasaba el largo del texto y se perdia el final.
 *
 * Por eso se devuelve tambien `mapa`: para cada posicion del texto normalizado,
 * el indice del caracter ORIGINAL que la produjo.
 */
function normalizarConMapa(texto) {
  let normalizado = "";
  const mapa = [];
  let indiceOriginal = 0;

  for (const caracter of texto) {
    const trozo = normalizarCaracter(caracter);
    for (let i = 0; i < trozo.length; i += 1) mapa.push(indiceOriginal);
    normalizado += trozo;
    // Array.from/for-of recorre por punto de codigo: un emoji o un caracter
    // fuera del BMP ocupa dos unidades en el string original.
    indiceOriginal += caracter.length;
  }

  // Centinela: permite mapear el final de una coincidencia que termina en el
  // ultimo caracter sin tratarlo como caso aparte.
  mapa.push(texto.length);
  return { normalizado, mapa };
}

/** Envuelve las coincidencias de `termino` dentro de `texto` en <mark>,
 *  case-insensitive y sin sensibilidad a tildes. Solo usa nodos de texto. */
function resaltar(texto, termino) {
  const fragmento = document.createDocumentFragment();
  const terminoNormalizado = termino ? normalizarTexto(termino) : "";
  if (!terminoNormalizado) {
    fragmento.append(texto);
    return fragmento;
  }

  const { normalizado, mapa } = normalizarConMapa(texto);
  let indice = normalizado.indexOf(terminoNormalizado);
  if (indice === -1) {
    fragmento.append(texto);
    return fragmento;
  }

  // El cursor avanza sobre el texto ORIGINAL; los indices del normalizado se
  // traducen con el mapa.
  let cursor = 0;
  while (indice !== -1) {
    const desde = mapa[indice];
    const hasta = mapa[indice + terminoNormalizado.length];
    if (desde > cursor) fragmento.append(texto.slice(cursor, desde));
    fragmento.append(el("mark", {}, texto.slice(desde, hasta)));
    cursor = hasta;
    indice = normalizado.indexOf(terminoNormalizado, indice + terminoNormalizado.length);
  }
  if (cursor < texto.length) fragmento.append(texto.slice(cursor));
  return fragmento;
}

/* -------------------------------------------------------------------------
   Controles
   ------------------------------------------------------------------------- */

function campoBusqueda() {
  const entrada = el("input", {
    type: "search",
    id: "buscador-q",
    value: q,
    placeholder: "Ej. seguridad, elecciones, inflación…",
    "aria-describedby": "buscador-aviso-longitud",
    onInput: (evento) => {
      const valor = evento.target.value;
      clearTimeout(temporizadorDebounce);
      temporizadorDebounce = setTimeout(() => {
        q = valor.trim();
        pagina = 1;
        escribirFiltrosPropiosEnUrl();
        buscarYPintar();
      }, DEBOUNCE_MS);
    },
  });

  return el(
    "div",
    { clase: "filtros__campo" },
    el("label", { clase: "filtros__etiqueta", for: "buscador-q", texto: "Buscar" }),
    entrada,
    el("p", {
      id: "buscador-aviso-longitud",
      clase: "cifra__nota",
      texto: "Al menos 2 caracteres. Busca en titular y resumen, sin distinguir mayúsculas ni tildes.",
    })
  );
}

function selectorTema() {
  const select = el("select", {
    id: "buscador-tema",
    onChange: (evento) => {
      tema = evento.target.value;
      pagina = 1;
      escribirFiltrosPropiosEnUrl();
      buscarYPintar();
    },
  });
  select.append(el("option", { value: "", texto: "Todos los temas", selected: tema === "" }));
  for (const opcion of CATALOGO_TEMAS) {
    select.append(el("option", { value: opcion.slug, texto: opcion.nombre, selected: opcion.slug === tema }));
  }
  return el(
    "div",
    { clase: "filtros__campo" },
    el("label", { clase: "filtros__etiqueta", for: "buscador-tema", texto: "Tema" }),
    select
  );
}

function selectorMedio() {
  const medioActual = estado.obtener().medio;
  const select = el("select", {
    id: "buscador-medio",
    onChange: (evento) => {
      estado.actualizar({ medio: evento.target.value });
    },
  });
  select.append(el("option", { value: "", texto: "Todos los medios", selected: medioActual === "" }));
  for (const opcion of CATALOGO_MEDIOS) {
    select.append(
      el("option", { value: opcion.slug, texto: opcion.nombre, selected: opcion.slug === medioActual })
    );
  }
  return el(
    "div",
    { clase: "filtros__campo" },
    el("label", { clase: "filtros__etiqueta", for: "buscador-medio", texto: "Medio" }),
    select
  );
}

function camposDeFecha() {
  const { desde, hasta } = estado.obtener();
  const entradaDesde = el("input", {
    type: "date",
    id: "buscador-desde",
    value: desde,
    onChange: (evento) => estado.actualizar({ desde: evento.target.value }),
  });
  const entradaHasta = el("input", {
    type: "date",
    id: "buscador-hasta",
    value: hasta,
    onChange: (evento) => estado.actualizar({ hasta: evento.target.value }),
  });
  return el(
    "div",
    { clase: "filtros", estilo: { border: "none", padding: "0" } },
    el(
      "div",
      { clase: "filtros__campo" },
      el("label", { clase: "filtros__etiqueta", for: "buscador-desde", texto: "Desde" }),
      entradaDesde
    ),
    el(
      "div",
      { clase: "filtros__campo" },
      el("label", { clase: "filtros__etiqueta", for: "buscador-hasta", texto: "Hasta" }),
      entradaHasta
    )
  );
}

/* -------------------------------------------------------------------------
   Resultados
   ------------------------------------------------------------------------- */

function filaDeResultado(noticia) {
  const enlace = el(
    "a",
    { href: noticia.url, target: "_blank", rel: "noopener noreferrer" },
    resaltar(noticia.titular, q)
  );

  const metadatos = el(
    "p",
    { clase: "cifra__nota" },
    `${noticia.medio} · ${noticia.tema || "sin tema clasificado"} · ${formatearFecha(noticia.fecha_publicacion)}`
  );

  const resumen = noticia.resumen
    ? el("p", { clase: "tarjeta__pregunta", estilo: { marginTop: "0.3rem" } }, resaltar(noticia.resumen, q))
    : null;

  return el(
    "li",
    { estilo: { padding: "0.85rem 0", borderBottom: "1px solid var(--regla)" } },
    el("p", { clase: "cifra__valor--texto", estilo: { fontWeight: "600" } }, enlace),
    metadatos,
    resumen
  );
}

function controlesDePaginacion(datos) {
  if (datos.paginas <= 1) return null;
  return el(
    "div",
    { clase: "controles", estilo: { justifyContent: "space-between", marginTop: "1rem" } },
    el("button", {
      clase: "boton boton--tenue",
      type: "button",
      disabled: pagina <= 1,
      texto: "← Anterior",
      onClick: () => {
        pagina -= 1;
        escribirFiltrosPropiosEnUrl();
        buscarYPintar();
      },
    }),
    el("span", { clase: "cifra__nota", texto: `Página ${datos.pagina} de ${datos.paginas}` }),
    el("button", {
      clase: "boton boton--tenue",
      type: "button",
      disabled: pagina >= datos.paginas,
      texto: "Siguiente →",
      onClick: () => {
        pagina += 1;
        escribirFiltrosPropiosEnUrl();
        buscarYPintar();
      },
    })
  );
}

function pintarResultados(datos) {
  const regionResultados = document.getElementById("buscador-resultados");
  const regionAnuncio = document.getElementById("buscador-anuncio");

  if (datos.noticias.length === 0) {
    mostrarVacio(regionResultados, {
      titulo: "Sin resultados",
      mensaje: "Probá con otra palabra clave, ampliá el rango de fechas o quitá algún filtro.",
    });
    regionAnuncio.textContent = "Sin resultados para esta búsqueda.";
    return;
  }

  // Se comprueba antes de insertarlo: controlesDePaginacion devuelve null
  // cuando hay una sola pagina, y Node.append(null) NO ignora el nulo -- lo
  // convierte a la cadena "null" y la mete como nodo de texto. el() de ui.js
  // si los filtra, pero este append es directo sobre el nodo. Se veia la
  // palabra "null" debajo de los resultados en toda busqueda de una sola
  // pagina, que con 131 noticias es casi cualquiera con un filtro puesto.
  const paginacion = controlesDePaginacion(datos);
  limpiar(regionResultados).append(
    el("ul", { estilo: { listStyle: "none", padding: "0", margin: "0" } }, datos.noticias.map(filaDeResultado))
  );
  if (paginacion) regionResultados.append(paginacion);
  regionAnuncio.textContent = `${datos.total} resultado${datos.total === 1 ? "" : "s"} encontrado${
    datos.total === 1 ? "" : "s"
  }.`;
}

/* -------------------------------------------------------------------------
   Peticion
   ------------------------------------------------------------------------- */

async function buscarYPintar() {
  const { medio, desde, hasta } = estado.obtener();
  const regionResultados = document.getElementById("buscador-resultados");
  if (!regionResultados) return; // la vista ya se desmonto

  // El backend exige 2 caracteres y responde 400. Sin esta guarda, escribir
  // una sola letra pintaba "No se pudieron cargar los datos" -- un cuadro de
  // error por escribir, que es justo lo que el aviso de longitud intenta
  // evitar. Con un caracter simplemente no se busca.
  if (q.length === 1) {
    marcarCargando(regionResultados, false);
    return;
  }

  marcarCargando(regionResultados, true);

  let datos;
  try {
    datos = await api.buscarNoticias({ q, tema, medio, desde, hasta, pagina, porPagina: POR_PAGINA });
  } catch (error) {
    if (error.name === "AbortError") return;
    // marcarCargando(false) ANTES de pintar el error. La clase .esta-cargando
    // lleva pointer-events:none y esta puesta sobre regionResultados, no sobre
    // un hijo, asi que mostrarError --que solo reemplaza los hijos-- la dejaba
    // viva: el cuadro de error salia atenuado y el boton "Reintentar" no
    // respondia al clic. La unica salida era tocar un filtro.
    marcarCargando(regionResultados, false);
    mostrarError(regionResultados, { mensaje: error.message, alReintentar: buscarYPintar });
    return;
  }

  marcarCargando(regionResultados, false);
  pintarResultados(datos);
}

/* -------------------------------------------------------------------------
   Contrato de vista
   ------------------------------------------------------------------------- */

const vista = {
  id: "buscador",
  titulo: "Buscador de noticias",

  montar(nodo) {
    contenedor = nodo;
    esPrimerRender = true;
    leerFiltrosPropiosDeUrl();

    const envoltura = el(
      "section",
      { clase: "tarjeta surge" },
      el(
        "header",
        { clase: "tarjeta__cabecera" },
        el(
          "div",
          {},
          el("h2", { clase: "tarjeta__titulo", id: "titulo-buscador", texto: "Buscador de noticias" }),
          el("p", {
            clase: "tarjeta__pregunta",
            texto: "Encontrá las noticias concretas detrás de cualquier pico del gráfico de evolución semanal.",
          })
        )
      ),
      el(
        "form",
        {
          clase: "filtros",
          "aria-label": "Filtros del buscador",
          onSubmit: (evento) => evento.preventDefault(),
        },
        campoBusqueda(),
        selectorTema(),
        selectorMedio(),
        camposDeFecha()
      ),
      el("p", {
        id: "buscador-anuncio",
        role: "status",
        "aria-live": "polite",
        clase: "visualmente-oculto",
      }),
      el("div", { id: "buscador-resultados" })
    );

    limpiar(contenedor).append(envoltura);
  },

  // main.js llama a actualizar() al montar y en cada cambio de los filtros
  // globales (medio, desde, hasta) via estado.suscribir: no hace falta que
  // esta vista se suscriba por su cuenta.
  async actualizar() {
    if (esPrimerRender) {
      mostrarCargando(document.getElementById("buscador-resultados"), { conCifras: false });
      esPrimerRender = false;
    } else {
      pagina = 1;
      escribirFiltrosPropiosEnUrl();
    }
    await buscarYPintar();
  },

  desmontar() {
    clearTimeout(temporizadorDebounce);
    if (contenedor) limpiar(contenedor);
    contenedor = null;
    esPrimerRender = true;
  },
};

export default vista;
