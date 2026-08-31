/* Vista comparativa y auditoria del pre-procesamiento. Issue #7 - Valentina. */

import * as api from "../api.js";
import { crearBarras, colorDeSerie, destruir } from "../graficos.js";
import {
  el,
  formatearNumero,
  formatearPorcentaje,
  formatearPuntos,
  formatearRango,
  limpiar,
  marcarCargando,
  mostrarCargando,
  mostrarError,
  mostrarVacio,
  tablaEquivalente,
} from "../ui.js";

const TEMAS = [
  ["politica", "Politica"], ["economia", "Economia"],
  ["seguridad", "Seguridad"], ["salud", "Salud"],
  ["deportes", "Deportes"], ["clima", "Clima"],
  ["internacional", "Internacional"], ["otros", "Otros"],
];
const NOMBRES_TEMAS = Object.fromEntries(TEMAS);

let contenedor = null;
let graficoComparativa = null;
let graficoCalidad = null;
let graficoOtros = null;
let filtrosActuales = {};
let primerRender = true;
let normalizar = true;
let temasSeleccionados = [];
let hojaEstilos = null;

function leerControlesDeUrl() {
  const parametros = new URLSearchParams(location.search);
  normalizar = parametros.get("normalizar") !== "false";
  temasSeleccionados = (parametros.get("temas") || "")
    .split(",")
    .filter((slug) => NOMBRES_TEMAS[slug]);
}

function guardarControlesEnUrl() {
  const parametros = new URLSearchParams(location.search);
  if (normalizar) parametros.delete("normalizar");
  else parametros.set("normalizar", "false");
  if (temasSeleccionados.length) parametros.set("temas", temasSeleccionados.join(","));
  else parametros.delete("temas");
  const query = parametros.toString();
  history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
}

const nombreTema = (slug) => NOMBRES_TEMAS[slug] || slug;

function cifra(rotulo, valor, nota, alerta = false) {
  return el(
    "div",
    { clase: `cifra${alerta ? " cifra--alerta" : ""}` },
    el("p", { clase: "cifra__rotulo", texto: rotulo }),
    el("p", { clase: "cifra__valor", texto: valor }),
    el("p", { clase: "cifra__nota", texto: nota })
  );
}

function controles() {
  const selector = el("select", {
    id: "comparativa-temas",
    multiple: true,
    size: "4",
    "aria-describedby": "ayuda-comparativa-temas",
    onChange: (evento) => {
      temasSeleccionados = [...evento.target.selectedOptions].map((opcion) => opcion.value);
      guardarControlesEnUrl();
      vista.actualizar(filtrosActuales);
    },
  });
  for (const [slug, nombre] of TEMAS) {
    selector.append(el("option", { value: slug, texto: nombre, selected: temasSeleccionados.includes(slug) }));
  }

  const alternar = el("input", {
    type: "checkbox",
    id: "comparativa-normalizar",
    checked: normalizar,
    onChange: (evento) => {
      normalizar = evento.target.checked;
      guardarControlesEnUrl();
      vista.actualizar(filtrosActuales);
    },
  });

  return el(
    "div",
    { clase: "comparativa-controles" },
    el(
      "div",
      { clase: "comparativa-control" },
      el("label", { for: "comparativa-temas", texto: "Temas a comparar" }),
      selector,
      el("small", {
        id: "ayuda-comparativa-temas",
        texto: "Sin seleccion se muestran todos. Usa Ctrl o Cmd para elegir varios.",
      })
    ),
    el(
      "label",
      { clase: "comparativa-toggle", for: "comparativa-normalizar" },
      alternar,
      el("span", {
        texto: normalizar
          ? "% dentro de la agenda de cada medio"
          : "% sobre el total recolectado por ambos medios",
      })
    )
  );
}

function ordenarTemas(medios) {
  const todos = new Set(medios.flatMap((medio) => medio.temas.map((tema) => tema.tema)));
  return [...todos].sort((a, b) => {
    const suma = (slug) => medios.reduce(
      (total, medio) => total + (medio.temas.find((tema) => tema.tema === slug)?.total || 0), 0
    );
    return suma(b) - suma(a) || nombreTema(a).localeCompare(nombreTema(b), "es");
  });
}

function conclusion(datos) {
  const frases = datos.brechas.slice(0, 2).map((brecha) => {
    if (brecha.prioriza === null) return `${nombreTema(brecha.tema)} queda empatado entre ambos medios`;
    const medio = datos.medios.find((item) => item.slug === brecha.prioriza)?.medio || brecha.prioriza;
    return `${medio} dedica ${formatearPuntos(brecha.diferencia_pp)} mas a ${nombreTema(brecha.tema)}`;
  });
  if (!frases.length) return "No hay brechas tematicas disponibles para este recorte.";
  return `${frases.join("; ")}.`;
}

function pintarComparativa(datos, destino) {
  const temas = ordenarTemas(datos.medios);
  const unidad = normalizar ? "% de la agenda del medio" : "% del total recolectado";
  const porSlug = Object.fromEntries(datos.medios.map((medio) => [medio.slug, medio.medio]));
  const canvas = el("canvas", {
    role: "img",
    "aria-label": `Comparacion agrupada de ${datos.medios.map((m) => m.medio).join(" y ")} por tema, en ${unidad}.`,
  });

  const filasTabla = temas.map((tema) => {
    const fila = { tema };
    for (const medio of datos.medios) {
      fila[medio.slug] = medio.temas.find((item) => item.tema === tema)?.porcentaje || 0;
    }
    return fila;
  });

  const tablaBrechas = el(
    "div",
    { clase: "tabla-envoltura" },
    el(
      "table",
      { clase: "datos" },
      el("caption", { texto: "Brechas de prioridad tematica, ordenadas por el backend" }),
      el("thead", {}, el("tr", {},
        el("th", { scope: "col", texto: "Tema" }),
        el("th", { scope: "col", texto: "Diferencia" }),
        el("th", { scope: "col", texto: "Prioriza" })
      )),
      el("tbody", {}, datos.brechas.map((brecha, indice) => el(
        "tr",
        { clase: indice < 3 ? "brecha-destacada" : "" },
        el("th", { scope: "row", texto: nombreTema(brecha.tema) }),
        el("td", { texto: formatearPuntos(brecha.diferencia_pp) }),
        el("td", { texto: brecha.prioriza === null ? "Empate" : porSlug[brecha.prioriza] || brecha.prioriza })
      )))
    )
  );

  const seccion = el(
    "section",
    { clase: "tarjeta surge" },
    el("header", { clase: "tarjeta__cabecera" }, el("div", {},
      el("h2", { clase: "tarjeta__titulo", id: "titulo-comparativa", texto: "Comparativa entre medios" }),
      el("p", { clase: "tarjeta__pregunta", texto: "¿Existen diferencias en que temas prioriza cada medio?" })
    )),
    controles(),
    filtrosActuales.medio ? el("div", { clase: "sello", role: "note", texto: "El filtro global de medio no se aplica aqui: esta vista siempre compara ambos medios." }) : null,
    el("p", { clase: "conclusion", texto: conclusion(datos) }),
    el("p", { clase: "cifra__nota", texto: `Unidad mostrada: ${unidad}. Los temas se ordenan por la suma de noticias de ambos medios.` }),
    el("div", { clase: "grafico grafico--comparativa" }, canvas),
    tablaEquivalente({
      resumen: `Distribucion por medio en ${unidad}`,
      columnas: [
        { titulo: "Tema", valor: (fila) => nombreTema(fila.tema) },
        ...datos.medios.map((medio) => ({ titulo: medio.medio, valor: (fila) => formatearPorcentaje(fila[medio.slug]) })),
      ],
      filas: filasTabla,
    }),
    el("h3", { clase: "subtitulo", texto: "Mayores brechas" }),
    tablaBrechas
  );

  destino.append(seccion);
  graficoComparativa = crearBarras(canvas, {
    etiquetas: temas.map(nombreTema),
    series: datos.medios.map((medio, indice) => ({
      etiqueta: medio.medio,
      datos: temas.map((tema) => medio.temas.find((item) => item.tema === tema)?.porcentaje || 0),
      color: colorDeSerie(indice),
    })),
    formatoValor: (valor) => `${valor} %`,
    formatoTooltip: (contexto) => `${contexto.dataset.label}: ${formatearPorcentaje(contexto.parsed.y)}`,
  });
}

async function obtenerCalidad(filtros) {
  const catalogo = await api.obtenerMedios();
  const resultados = [];
  // api.js cancela la consulta top-temas anterior; por eso estas consultas son
  // deliberadamente secuenciales y no Promise.all.
  for (const medio of catalogo) {
    const datos = await api.obtenerTopTemas({ limite: 50, desde: filtros.desde, hasta: filtros.hasta, medio: medio.slug });
    resultados.push({ ...medio, ...datos });
  }
  return resultados;
}

function pintarCalidad(medios, destino) {
  const total = medios.reduce((suma, medio) => suma + medio.total_noticias, 0);
  const clasificadas = medios.reduce((suma, medio) => suma + medio.clasificadas, 0);
  const pendientes = medios.reduce((suma, medio) => suma + medio.sin_clasificar, 0);
  const cobertura = total ? clasificadas * 100 / total : 0;
  const inicios = medios.map((medio) => medio.periodo?.desde).filter(Boolean).sort();
  const fines = medios.map((medio) => medio.periodo?.hasta).filter(Boolean).sort();
  const ventana = formatearRango(inicios[0], fines.at(-1));
  const canvasCalidad = el("canvas", { role: "img", "aria-label": "Noticias clasificadas y sin clasificar por medio." });
  const canvasOtros = el("canvas", { role: "img", "aria-label": "Peso porcentual del tema Otros por medio." });
  const otros = medios.map((medio) => medio.temas.find((tema) => tema.slug === "otros") || { total: 0, porcentaje: 0 });

  const seccion = el(
    "section",
    { clase: "tarjeta surge" },
    el("h2", { clase: "tarjeta__titulo", texto: "Calidad del pre-procesamiento" }),
    el("p", { clase: "tarjeta__pregunta", texto: "Cobertura de clasificacion y senales para auditar el diccionario tematico." }),
    pendientes > 0 ? el("div", { clase: "sello", role: "alert" },
      el("span", { clase: "sello__titulo", texto: "Pipeline pendiente" }),
      `Hay ${formatearNumero(pendientes)} noticias pendientes en la ventana analizada (${ventana}). ` +
      "El endpoint no informa la fecha individual de la primera pendiente. Ejecuta ",
      el("code", { texto: "python -m backend.pipeline.procesar" }), "."
    ) : null,
    el("div", { clase: "cifras" },
      cifra("Total en la base", formatearNumero(total), "en el periodo seleccionado"),
      cifra("Clasificadas", formatearNumero(clasificadas), "entran en los porcentajes"),
      cifra("Sin clasificar", formatearNumero(pendientes), pendientes ? "requieren ejecutar el pipeline" : "nada pendiente", pendientes > 0),
      cifra("Cobertura", formatearPorcentaje(cobertura), "clasificadas / total")
    ),
    el("div", { clase: "calidad-rejilla" },
      el("div", {}, el("h3", { clase: "subtitulo", texto: "Cobertura por medio" }), el("div", { clase: "grafico" }, canvasCalidad),
        tablaEquivalente({ resumen: "Estado de clasificacion por medio", columnas: [
          { titulo: "Medio", valor: (fila) => fila.nombre },
          { titulo: "Clasificadas", valor: (fila) => formatearNumero(fila.clasificadas) },
          { titulo: "Sin clasificar", valor: (fila) => formatearNumero(fila.sin_clasificar) },
        ], filas: medios })),
      el("div", {}, el("h3", { clase: "subtitulo", texto: "Peso del tema Otros" }), el("div", { clase: "grafico" }, canvasOtros),
        el("p", { clase: "cifra__nota", texto: "Un peso alto de Otros indica que el diccionario backend/pipeline/temas.yml puede necesitar mas terminos." }),
        tablaEquivalente({ resumen: "Noticias clasificadas como Otros por medio", columnas: [
          { titulo: "Medio", valor: (fila) => fila.nombre },
          { titulo: "Noticias en Otros", valor: (fila) => formatearNumero(fila.otros.total) },
          { titulo: "% de clasificadas", valor: (fila) => formatearPorcentaje(fila.otros.porcentaje) },
        ], filas: medios.map((medio, i) => ({ ...medio, otros: otros[i] })) }))
    ),
    el("aside", { clase: "nota-metodologica" },
      el("h3", { clase: "subtitulo", texto: "Nota metodologica" }),
      el("p", { texto: "Los porcentajes se calculan solo sobre noticias clasificadas. La ventana corresponde a lo disponible en los feeds RSS, no a un archivo historico completo. Como los medios aportan volumenes distintos, la comparacion valida es por porcentajes de agenda y no por totales absolutos." })
    )
  );

  destino.append(seccion);
  graficoCalidad = crearBarras(canvasCalidad, {
    etiquetas: medios.map((medio) => medio.nombre),
    series: [
      { etiqueta: "Clasificadas", datos: medios.map((medio) => medio.clasificadas), color: colorDeSerie(0) },
      { etiqueta: "Sin clasificar", datos: medios.map((medio) => medio.sin_clasificar), color: colorDeSerie(2) },
    ], apilado: true, formatoValor: formatearNumero,
  });
  graficoOtros = crearBarras(canvasOtros, {
    etiquetas: medios.map((medio) => medio.nombre),
    series: [{ etiqueta: "Otros", datos: otros.map((tema) => tema.porcentaje), color: colorDeSerie(4) }],
    horizontal: true, etiquetasDirectas: true, formatoValor: (valor) => `${valor} %`,
    formatoTooltip: (contexto) => formatearPorcentaje(contexto.parsed.x),
  });
}

function destruirGraficos() {
  graficoComparativa = destruir(graficoComparativa);
  graficoCalidad = destruir(graficoCalidad);
  graficoOtros = destruir(graficoOtros);
}

const vista = {
  id: "comparativa",
  titulo: "Comparativa entre medios",
  montar(nodo) {
    contenedor = nodo;
    primerRender = true;
    leerControlesDeUrl();
    // Se guarda la referencia SIEMPRE, tambien cuando el <link> ya estaba en
     // el documento. Antes, si montar() encontraba uno existente, hojaEstilos
     // quedaba en null y el hojaEstilos?.remove() de desmontar() no hacia
     // nada: el CSS de comparativa se quedaba cargado para el resto de la
     // sesion, y sus selectores (.subtitulo, .conclusion, .grafico--comparativa)
     // son globales, asi que afectaban a las otras vistas.
    hojaEstilos = document.querySelector("link[data-comparativa]");
    if (!hojaEstilos) {
      hojaEstilos = el("link", { rel: "stylesheet", href: "/static-dashboard/css/comparativa.css", "data-comparativa": "" });
      document.head.append(hojaEstilos);
    }
  },
  async actualizar(filtros) {
    filtrosActuales = filtros;
    if (primerRender) mostrarCargando(contenedor);
    else marcarCargando(contenedor.firstElementChild, true);
    try {
      const datos = await api.obtenerComparativa({ desde: filtros.desde, hasta: filtros.hasta, temas: temasSeleccionados, normalizar });
      if (!datos.medios.length) {
        destruirGraficos();
        mostrarVacio(contenedor, { mensaje: "No hay noticias clasificadas en este rango. Amplia el periodo o ejecuta el scraper y el pipeline." });
        primerRender = true;
        return;
      }
      const calidad = await obtenerCalidad(filtros);
      document.dispatchEvent(new CustomEvent("noticia:periodo", { detail: datos.periodo }));
      destruirGraficos();
      const contenido = el("div", {});
      limpiar(contenedor).append(contenido);
      pintarComparativa(datos, contenido);
      pintarCalidad(calidad, contenido);
      primerRender = false;
    } catch (error) {
      if (error.name === "AbortError") return;
      destruirGraficos();
      mostrarError(contenedor, { mensaje: error.message, alReintentar: () => vista.actualizar(filtrosActuales) });
      primerRender = true;
    }
  },
  desmontar() {
    destruirGraficos();
    if (contenedor) limpiar(contenedor);
    hojaEstilos?.remove();
    hojaEstilos = null;
    contenedor = null;
    primerRender = true;
  },
};

export default vista;
