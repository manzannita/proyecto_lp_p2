/* Vista: evolucion semanal por tema. Issue #8 - Cristian.
 *
 * Responde la pregunta de analisis:
 *   Como varia semana a semana la cantidad de noticias publicadas sobre un
 *   tema especifico (por ejemplo clima o seguridad)?
 *
 * Forma elegida: lineas. Es una serie de tiempo, y comparar hasta tres temas
 * (o un tema entre medios) es exactamente para lo que sirve superponer lineas
 * con marcadores distintos, no solo color.
 */

import * as api from "../api.js";
import * as estado from "../estado.js";
import { crearLineas, colorDeSerie, destruir } from "../graficos.js";
import {
  el,
  formatearFecha,
  formatearNumero,
  formatearSemanaIso,
  limpiar,
  marcarCargando,
  mostrarCargando,
  mostrarError,
  mostrarVacio,
  tablaEquivalente,
} from "../ui.js";

// Catalogo cerrado: la vista nunca deja escribir un tema libre, solo elegir
// de esta lista (coincide con el catalogo sembrado por schema.sql).
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
const MAXIMO_TEMAS_COMPARADOS = 3;

let contenedor = null;
let grafico = null;
let modo = "temas"; // "temas" | "medios"
let temasSeleccionados = ["seguridad"];
let temaUnico = "seguridad";
let filtrosActuales = {};
let esPrimerRender = true;
let catalogoMedios = null; // cache: [{ nombre, slug }]

function nombreDeTema(slug) {
  return CATALOGO_TEMAS.find((tema) => tema.slug === slug)?.nombre || slug;
}

function sumarDias(fechaIso, dias) {
  const fecha = new Date(`${fechaIso}T00:00:00`);
  fecha.setDate(fecha.getDate() + dias);
  return fecha.toISOString().slice(0, 10);
}

/* -------------------------------------------------------------------------
   Controles propios de la vista
   ------------------------------------------------------------------------- */

function controlDeModo() {
  const grupo = el("div", { clase: "segmentado", role: "group", "aria-label": "Modo de comparación" });
  for (const [valor, etiqueta] of [["temas", "Comparar temas"], ["medios", "Por medio"]]) {
    grupo.append(
      el("button", {
        type: "button",
        texto: etiqueta,
        "aria-pressed": String(modo === valor),
        onClick: () => {
          if (modo === valor) return;
          modo = valor;
          vista.actualizar(filtrosActuales);
        },
      })
    );
  }
  return grupo;
}

function controlDeTemasComparados() {
  // .segmentado (componentes.css) es "inline-flex" sin wrap: le alcanza para
  // los 2-3 botones que usan otras vistas, pero este grupo tiene 8. Sin
  // flex-wrap aqui, a 375px el grupo desborda el ancho de la tarjeta y fuerza
  // scroll horizontal en toda la pagina.
  const grupo = el("div", {
    clase: "segmentado",
    role: "group",
    "aria-label": "Temas a comparar (máximo 3)",
    estilo: { flexWrap: "wrap" },
  });
  for (const tema of CATALOGO_TEMAS) {
    const activo = temasSeleccionados.includes(tema.slug);
    const bloqueado = !activo && temasSeleccionados.length >= MAXIMO_TEMAS_COMPARADOS;
    grupo.append(
      el("button", {
        type: "button",
        texto: tema.nombre,
        disabled: bloqueado,
        "aria-pressed": String(activo),
        onClick: () => {
          if (activo) {
            // Siempre queda al menos un tema seleccionado.
            if (temasSeleccionados.length === 1) return;
            temasSeleccionados = temasSeleccionados.filter((slug) => slug !== tema.slug);
          } else {
            if (temasSeleccionados.length >= MAXIMO_TEMAS_COMPARADOS) return;
            temasSeleccionados = [...temasSeleccionados, tema.slug];
          }
          vista.actualizar(filtrosActuales);
        },
      })
    );
  }
  return grupo;
}

function controlDeTemaUnico() {
  const select = el("select", {
    "aria-label": "Tema a comparar entre medios",
    onChange: (evento) => {
      temaUnico = evento.target.value;
      vista.actualizar(filtrosActuales);
    },
  });
  for (const tema of CATALOGO_TEMAS) {
    select.append(el("option", { value: tema.slug, texto: tema.nombre, selected: tema.slug === temaUnico }));
  }
  return select;
}

function controles() {
  return el(
    "div",
    { clase: "controles" },
    el("span", { clase: "controles__rotulo", texto: "Modo" }),
    controlDeModo(),
    modo === "temas"
      ? el(
          "div",
          { clase: "controles" },
          el("span", { clase: "controles__rotulo", texto: "Temas" }),
          controlDeTemasComparados()
        )
      : el(
          "div",
          { clase: "controles" },
          el("span", { clase: "controles__rotulo", texto: "Tema" }),
          controlDeTemaUnico()
        )
  );
}

/* -------------------------------------------------------------------------
   Peticiones
   ------------------------------------------------------------------------- */

async function obtenerMediosActivos() {
  if (catalogoMedios) return catalogoMedios;
  catalogoMedios = await api.obtenerMedios();
  return catalogoMedios;
}

/** Trae las series a graficar segun el modo activo. Devuelve una lista de
 *  { etiqueta, temaSlug, medioSlug, datos } donde "datos" es la respuesta
 *  cruda de /series-semanales. */
async function traerSeries(filtros) {
  if (modo === "temas") {
    // Un endpoint por tema, en paralelo: cada llamada usa su propia clave de
    // cancelacion en api.js ("series:<tema>"), asi que no se pisan entre si.
    const respuestas = await Promise.all(
      temasSeleccionados.map((slug) => api.obtenerSeriesSemanales({ tema: slug, ...filtros }))
    );
    return respuestas.map((datos, indice) => ({
      etiqueta: nombreDeTema(temasSeleccionados[indice]),
      temaSlug: temasSeleccionados[indice],
      medioSlug: filtros.medio || null,
      datos,
    }));
  }

  // Modo "por medio": las llamadas comparten tema y por lo tanto la MISMA
  // clave de cancelacion en api.js ("series:<tema>"). Si se pidieran en
  // paralelo con Promise.all, cada peticion cancelaria a la anterior antes de
  // que llegue su respuesta. Por eso aqui se piden en secuencia.
  // api.obtenerMedios() ya devuelve solo los medios activos (medios.py filtra
  // por m.activo = 1), asi que no hace falta filtrar de nuevo aqui.
  const medios = await obtenerMediosActivos();
  const resultados = [];
  for (const medio of medios) {
    const datos = await api.obtenerSeriesSemanales({
      tema: temaUnico,
      desde: filtros.desde,
      hasta: filtros.hasta,
      medio: medio.slug,
    });
    resultados.push({ etiqueta: medio.nombre, temaSlug: temaUnico, medioSlug: medio.slug, datos });
  }
  return resultados;
}

/* -------------------------------------------------------------------------
   Eje X compartido: union de las semanas de todas las series, para que se
   puedan superponer aunque alguna tenga un periodo mas angosto.
   ------------------------------------------------------------------------- */

function construirEjeX(seriesMeta) {
  const semanas = new Map(); // semana_iso -> semana_inicio
  for (const { datos } of seriesMeta) {
    for (const punto of datos.serie) {
      if (!semanas.has(punto.semana_iso)) semanas.set(punto.semana_iso, punto.semana_inicio);
    }
  }
  return [...semanas.entries()].sort((a, b) => a[1].localeCompare(b[1]));
}

function valorEnSemana(serieMeta, semanaIso) {
  return serieMeta.datos.serie.find((punto) => punto.semana_iso === semanaIso) || null;
}

/* -------------------------------------------------------------------------
   KPI
   ------------------------------------------------------------------------- */

function variacionFicha(valor) {
  if (valor === null || valor === undefined) {
    return el(
      "div",
      { clase: "cifra", estilo: { flex: "1 1 140px" } },
      el("p", { clase: "cifra__rotulo", texto: "Variación última semana" }),
      el("p", { clase: "cifra__valor cifra__valor--texto", texto: "Sin dato suficiente" })
    );
  }
  const sube = valor >= 0;
  return el(
    "div",
    { clase: `cifra${sube ? "" : " cifra--alerta"}`, estilo: { flex: "1 1 140px" } },
    el("p", { clase: "cifra__rotulo", texto: "Variación última semana" }),
    el("p", {
      clase: "cifra__valor",
      texto: `${sube ? "▲" : "▼"} ${Math.abs(valor).toFixed(1)} %`,
    })
  );
}

function bloqueKpi(serieMeta) {
  const { resumen } = serieMeta.datos;
  return el(
    "section",
    { clase: "tarjeta", "aria-label": `Resumen de ${serieMeta.etiqueta}` },
    el("h3", { clase: "tarjeta__titulo", estilo: { fontSize: "1rem" }, texto: serieMeta.etiqueta }),
    el(
      "div",
      {
        // No se reutiliza la clase "cifras" (grid) aqui: con exactamente 4
        // fichas, "auto-fit" a veces arma una ultima fila incompleta y deja
        // una celda de grilla vacia (visible, con el color de fondo de la
        // grilla) donde no hay ficha. Con flex-wrap eso no puede pasar: cada
        // ficha simplemente pasa a la siguiente linea, sin reservar celda.
        estilo: {
          display: "flex",
          flexWrap: "wrap",
          gap: "1px",
          marginTop: "0.75rem",
          border: "1px solid var(--regla-fuerte)",
          borderRadius: "var(--radio)",
          background: "var(--regla-fuerte)",
          overflow: "hidden",
        },
      },
      el(
        "div",
        { clase: "cifra", estilo: { flex: "1 1 140px" } },
        el("p", { clase: "cifra__rotulo", texto: "Total del periodo" }),
        el("p", { clase: "cifra__valor", texto: formatearNumero(resumen.total_periodo) })
      ),
      el(
        "div",
        { clase: "cifra", estilo: { flex: "1 1 140px" } },
        el("p", { clase: "cifra__rotulo", texto: "Promedio semanal" }),
        el("p", { clase: "cifra__valor", texto: formatearNumero(resumen.promedio_semanal) })
      ),
      el(
        "div",
        { clase: "cifra", estilo: { flex: "1 1 140px" } },
        el("p", { clase: "cifra__rotulo", texto: "Semana pico" }),
        el("p", {
          clase: "cifra__valor cifra__valor--texto",
          texto: resumen.semana_pico ? formatearSemanaIso(resumen.semana_pico) : "Sin dato suficiente",
        })
      ),
      variacionFicha(resumen.variacion_ultima_semana_pct)
    )
  );
}

/* -------------------------------------------------------------------------
   Navegar al buscador filtrado
   ------------------------------------------------------------------------- */

function irABuscadorFiltrado({ temaSlug, medioSlug, semanaInicio }) {
  const hasta = sumarDias(semanaInicio, 6);
  estado.actualizar({ desde: semanaInicio, hasta, medio: medioSlug || "" });

  const params = new URLSearchParams(window.location.search);
  params.set("tema", temaSlug);
  // pagina no se hereda: si la URL venia con ?pagina=4 de una busqueda
  // anterior, el buscador abriria en la pagina 4 de un resultado nuevo y
  // mostraria "sin resultados" para una semana que si tiene noticias.
  params.delete("pagina");

  // El orden importa y antes estaba al revés, con el resultado de que este
  // clic NO navegaba nunca. replaceState no dispara hashchange pero SI cambia
  // location.hash, asi que al asignar despues el mismo valor el setter de
  // Location.hash corta por su primer paso normativo ("si el fragment nuevo es
  // igual al actual, retornar"): main.js no recibia el evento y la vista de
  // series se quedaba en pantalla con los filtros cambiados.
  //
  // Ahora se escriben primero los parametros CONSERVANDO el hash actual, y
  // recien despues se cambia el hash, que es lo unico que dispara hashchange.
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}?${params.toString()}${window.location.hash}`
  );
  window.location.hash = "#/buscador";
}

/* -------------------------------------------------------------------------
   Pintado
   ------------------------------------------------------------------------- */

// Mismo orden de marcadores que crearLineas() en graficos.js, para que el
// glifo de la leyenda coincida con el punto que realmente se dibuja.
const GLIFOS_POR_MARCADOR = { circle: "●", rect: "■", triangle: "▲" };
const ORDEN_MARCADORES = ["circle", "rect", "triangle"];

/** Leyenda propia (no la de Chart.js: ver la nota en dibujarGrafico). Cada
 *  entrada combina color, forma del marcador y la etiqueta en texto, para que
 *  identificar una linea nunca dependa solo del color. */
function leyendaPersonalizada(seriesMeta) {
  if (seriesMeta.length <= 1) return null;
  return el(
    "ul",
    {
      "aria-hidden": "true", // el nombre de cada serie ya esta en su tarjeta KPI y en la tabla
      estilo: {
        listStyle: "none",
        display: "flex",
        flexWrap: "wrap",
        gap: "0.4rem 1.1rem",
        margin: "0 0 0.75rem",
        padding: "0",
      },
    },
    seriesMeta.map((serieMeta, indice) =>
      el(
        "li",
        { estilo: { display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.78rem" } },
        el("span", { clase: "marca-serie", estilo: { background: colorDeSerie(indice) } }),
        el("span", { texto: GLIFOS_POR_MARCADOR[ORDEN_MARCADORES[indice % 3]] }),
        el("span", { texto: serieMeta.etiqueta })
      )
    )
  );
}

function pintar(seriesMeta) {
  const ejeX = construirEjeX(seriesMeta);

  const envoltura = el("div", {});
  const canvas = el("canvas", {
    role: "img",
    "aria-label": `Líneas de evolución semanal para ${seriesMeta.map((serie) => serie.etiqueta).join(", ")}.`,
  });

  envoltura.append(
    el(
      "section",
      { clase: "tarjeta surge" },
      el(
        "header",
        { clase: "tarjeta__cabecera" },
        el(
          "div",
          {},
          el("h2", { clase: "tarjeta__titulo", id: "titulo-series", texto: "Evolución semanal por tema" }),
          el("p", {
            clase: "tarjeta__pregunta",
            texto:
              "¿Cómo varía semana a semana la cantidad de noticias publicadas sobre un tema específico?",
          })
        ),
        controles()
      ),

      el(
        "div",
        {
          clase: "surge",
          estilo: {
            display: "grid",
            gridTemplateColumns: `repeat(auto-fit, minmax(240px, 1fr))`,
            gap: "1rem",
            marginBottom: "var(--gap)",
          },
        },
        seriesMeta.map(bloqueKpi)
      ),

      leyendaPersonalizada(seriesMeta),
      el("div", { clase: "grafico" }, canvas),

      el("p", {
        clase: "cifra__nota",
        texto:
          "La última semana del rango casi siempre está incompleta (todavía no terminó de recolectarse), " +
          "así que se dibuja con el tramo final punteado: una caída ahí no es necesariamente una tendencia real.",
      }),

      el("p", {
        clase: "cifra__nota",
        texto: "Hacé clic en un punto del gráfico para ver, en el buscador, las noticias de esa semana.",
      }),

      tablaEquivalente({
        resumen: `Evolución semanal · ${seriesMeta.map((serie) => serie.etiqueta).join(" vs. ")}`,
        columnas: [
          { titulo: "Semana", valor: (fila) => formatearSemanaIso(fila.iso) },
          ...seriesMeta.map((serie, indice) => ({
            titulo: serie.etiqueta,
            valor: (fila) => {
              const punto = valorEnSemana(serie, fila.iso);
              return punto ? formatearNumero(punto.total) : "—";
            },
          })),
        ],
        filas: ejeX.map(([iso, inicio]) => ({ iso, inicio })),
      })
    )
  );

  limpiar(contenedor).append(envoltura);
  dibujarGrafico(canvas, seriesMeta, ejeX);
}

function dibujarGrafico(canvas, seriesMeta, ejeX) {
  grafico = destruir(grafico);

  const series = seriesMeta.map((serieMeta, indice) => {
    const datos = ejeX.map(([iso]) => {
      const punto = valorEnSemana(serieMeta, iso);
      return punto ? punto.total : null;
    });
    const ultimoIndiceConDato = (() => {
      const semanas = serieMeta.datos.serie;
      if (!semanas.length) return -1;
      return ejeX.findIndex(([iso]) => iso === semanas[semanas.length - 1].semana_iso);
    })();

    return {
      etiqueta: serieMeta.etiqueta,
      datos,
      color: colorDeSerie(indice),
      // Tramo final punteado: marca la ultima semana (casi siempre
      // incompleta) sin inventar un punto hueco que graficos.js no soporta.
      // La API de segmentos de Chart.js espera un objeto de callbacks por
      // propiedad de estilo (no una funcion suelta): { borderDash: ctx => ... }.
      segmento: {
        borderDash: (contexto) => (contexto.p1DataIndex === ultimoIndiceConDato ? [6, 4] : undefined),
      },
    };
  });

  grafico = crearLineas(canvas, {
    etiquetas: ejeX.map(([iso]) => formatearSemanaIso(iso)),
    series,
    formatoValor: formatearNumero,
    formatoTooltip: (contexto) => {
      const serieMeta = seriesMeta[contexto.datasetIndex];
      const iso = ejeX[contexto.dataIndex][0];
      const punto = valorEnSemana(serieMeta, iso);
      if (!punto) return `${serieMeta.etiqueta}: sin datos esa semana`;
      const rango = `${formatearFecha(punto.semana_inicio)} – ${formatearFecha(sumarDias(punto.semana_inicio, 6))}`;
      return `${serieMeta.etiqueta}: ${formatearNumero(punto.total)} noticias (${rango})`;
    },
  });

  // El plugin de leyenda de Chart.js queda deshabilitado (ver leyendaPersonalizada
  // mas abajo): graficos.js reemplaza por completo plugins.legend.labels al
  // inicializar el tema, sin volver a poner un generateLabels, asi que la
  // leyenda nativa queda con cero items en cualquier grafico con mas de una
  // serie. "none" evita reanimar el grafico que ya se dibujo.
  grafico.options.plugins.legend.display = false;

  // El eje de categorias del tema comun (ejes() en graficos.js) fuerza
  // autoSkip:false, porque a las otras vistas les alcanza con pocas
  // categorias. Con muchas semanas eso satura el eje X de etiquetas
  // superpuestas, sobre todo a 375px. Se resuelve mostrando el texto solo
  // cada N ticks (dejando el resto en blanco): el tooltip sigue mostrando la
  // semana completa porque su titulo sale de chart.data.labels, que no se toca.
  const anchoDisponible = canvas.clientWidth || 600;
  const anchoPorEtiqueta = 68; // "sem. 34 / 2026" en la fuente mono, ~11px
  const maximoVisibles = Math.max(4, Math.floor(anchoDisponible / anchoPorEtiqueta));
  const salto = Math.max(1, Math.ceil(ejeX.length / maximoVisibles));
  grafico.options.scales.x.ticks.callback = function (valor, indice) {
    return indice % salto === 0 ? this.getLabelForValue(valor) : "";
  };

  grafico.update("none");

  canvas.addEventListener("click", (evento) => {
    // intersect:false para que baste con acercarse al punto (en x e y), no
    // acertar el pixel exacto: exigirlo haria el clic poco fiable, sobre todo
    // con varias lineas superpuestas.
    const elementos = grafico.getElementsAtEventForMode(
      evento,
      "nearest",
      { intersect: false, axis: "xy" },
      true
    );
    if (!elementos.length) return;
    const { datasetIndex, index } = elementos[0];
    const serieMeta = seriesMeta[datasetIndex];
    const iso = ejeX[index][0];
    const punto = valorEnSemana(serieMeta, iso);
    if (!punto) return;
    irABuscadorFiltrado({
      temaSlug: serieMeta.temaSlug,
      medioSlug: serieMeta.medioSlug,
      semanaInicio: punto.semana_inicio,
    });
  });
}

/* -------------------------------------------------------------------------
   Contrato de vista
   ------------------------------------------------------------------------- */

const vista = {
  id: "series",
  titulo: "Evolución semanal por tema",

  montar(nodo) {
    contenedor = nodo;
    esPrimerRender = true;
  },

  async actualizar(filtros) {
    filtrosActuales = filtros;

    if (esPrimerRender) {
      mostrarCargando(contenedor);
    } else {
      marcarCargando(contenedor.firstElementChild, true);
    }

    let seriesMeta;
    try {
      seriesMeta = await traerSeries(filtros);
    } catch (error) {
      if (error.name === "AbortError") return;
      mostrarError(contenedor, {
        mensaje: error.message,
        alReintentar: () => vista.actualizar(filtrosActuales),
      });
      esPrimerRender = true;
      return;
    }

    esPrimerRender = false;

    const desdes = seriesMeta.map((serie) => serie.datos.periodo.desde).filter(Boolean);
    const hastas = seriesMeta.map((serie) => serie.datos.periodo.hasta).filter(Boolean);
    if (desdes.length) {
      document.dispatchEvent(
        new CustomEvent("noticia:periodo", {
          detail: { desde: desdes.sort()[0], hasta: hastas.sort().at(-1) },
        })
      );
    }

    grafico = destruir(grafico);

    const sinDatos = seriesMeta.every((serie) => serie.datos.resumen.total_periodo === 0);
    if (sinDatos) {
      mostrarVacio(contenedor, {
        mensaje:
          "No hay noticias de este tema en el periodo filtrado. Ampliá el rango de fechas o probá con otro tema.",
      });
      esPrimerRender = true;
      return;
    }

    pintar(seriesMeta);
  },

  desmontar() {
    grafico = destruir(grafico);
    if (contenedor) limpiar(contenedor);
    contenedor = null;
    esPrimerRender = true;
  },
};

export default vista;
