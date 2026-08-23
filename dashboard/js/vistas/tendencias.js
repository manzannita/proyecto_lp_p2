/* Vista: temas mas cubiertos.  Issue #6 - Annabella.
 *
 * Responde la pregunta de analisis:
 *   Cuales son los 5 temas mas cubiertos por los medios ecuatorianos
 *   analizados durante el periodo de recoleccion?
 *
 * Forma elegida: barras HORIZONTALES. El dato es una magnitud comparada entre
 * categorias nominales con nombre largo ("internacional", "seguridad"), y en
 * horizontal la etiqueta se lee de corrido sin rotarla. Una sola serie, un solo
 * color: pintar cada barra de un tono distinto segun su tamano duplicaria en
 * color lo que el largo ya dice.
 */

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

const LIMITES = [5, 10, 20];

let contenedor = null;
let grafico = null;
let limite = 5;
let filtrosActuales = {};
let esPrimerRender = true;

/** "el-universo" -> "El Universo". Evita una peticion extra solo para el rotulo. */
function nombreDeMedio(slug) {
  if (!slug || slug === "todos") return "Todos los medios";
  return slug
    .split("-")
    .map((parte) => parte.charAt(0).toUpperCase() + parte.slice(1))
    .join(" ");
}

function cifra({ rotulo, valor, nota, alerta = false, texto = false }) {
  return el(
    "div",
    { clase: `cifra${alerta ? " cifra--alerta" : ""}` },
    el("p", { clase: "cifra__rotulo", texto: rotulo }),
    // Una ficha cuyo valor es una palabra y no un numero necesita menos cuerpo:
    // "Todos los medios" a 2rem se parte en dos lineas y desbalancea la fila.
    el("p", { clase: `cifra__valor${texto ? " cifra__valor--texto" : ""}`, texto: valor }),
    nota ? el("p", { clase: "cifra__nota", texto: nota }) : null
  );
}

function controlDeLimite() {
  const grupo = el("div", { clase: "segmentado", role: "group", "aria-label": "Cantidad de temas" });

  for (const opcion of LIMITES) {
    grupo.append(
      el("button", {
        type: "button",
        texto: String(opcion),
        "aria-pressed": String(opcion === limite),
        onClick: () => {
          if (opcion === limite) return;
          limite = opcion;
          vista.actualizar(filtrosActuales);
        },
      })
    );
  }

  return el(
    "div",
    { clase: "controles" },
    el("span", { clase: "controles__rotulo", id: "rotulo-limite", texto: "Top" }),
    grupo
  );
}

/** Frase que responde la pregunta con los datos a la vista. Un grafico solo no
 *  responde nada: alguien tiene que decir que se concluye de el. */
function respuesta(datos) {
  const [primero, segundo] = datos.temas;
  if (!primero) return null;

  let texto =
    `${primero.tema} encabeza la agenda con ${formatearNumero(primero.total)} ` +
    `de las ${formatearNumero(datos.clasificadas)} noticias clasificadas ` +
    `(${formatearPorcentaje(primero.porcentaje)}).`;

  if (segundo) {
    // La diferencia entre dos porcentajes se mide en PUNTOS porcentuales, no en
    // porcentaje: decir "43,5 % por debajo" seria otra cifra y estaria mal.
    const brecha = Math.round((primero.porcentaje - segundo.porcentaje) * 10) / 10;
    texto +=
      ` Le sigue ${segundo.tema} con ${formatearPorcentaje(segundo.porcentaje)}, ` +
      `${formatearPuntos(brecha)} por debajo.`;
  }

  return el("p", { clase: "tarjeta__pregunta", texto });
}

function pintar(datos) {
  const envoltura = el("div", {});

  // Aviso de calidad de datos. El endpoint reporta las pendientes a proposito:
  // si el ranking se muestra sin decir que hay noticias sin clasificar, el
  // dashboard esta mintiendo por omision.
  if (datos.sin_clasificar > 0) {
    envoltura.append(
      el(
        "div",
        { clase: "sello surge", role: "status" },
        el("span", { clase: "sello__titulo", texto: "Pipeline atrasado" }),
        el(
          "span",
          {},
          `Hay ${formatearNumero(datos.sin_clasificar)} noticias sin clasificar y el ranking ` +
            `solo cuenta las clasificadas. Para incluirlas, corré `,
          el("code", { texto: "python -m backend.pipeline.procesar" }),
          "."
        )
      )
    );
  }

  const cobertura = datos.total_noticias
    ? (datos.clasificadas * 100) / datos.total_noticias
    : 0;

  envoltura.append(
    el(
      "div",
      { clase: "cifras surge" },
      cifra({
        rotulo: "Noticias recolectadas",
        valor: formatearNumero(datos.total_noticias),
        nota: formatearRango(datos.periodo.desde, datos.periodo.hasta),
      }),
      cifra({
        rotulo: "Clasificadas",
        valor: formatearNumero(datos.clasificadas),
        nota: `${formatearPorcentaje(cobertura)} de cobertura`,
      }),
      cifra({
        rotulo: "Sin clasificar",
        valor: formatearNumero(datos.sin_clasificar),
        nota: datos.sin_clasificar > 0 ? "pendientes del pipeline" : "nada pendiente",
        alerta: datos.sin_clasificar > 0,
      }),
      cifra({
        rotulo: "Medio",
        valor: nombreDeMedio(datos.medio),
        nota: `top ${datos.limite} temas`,
        texto: true,
      })
    )
  );

  const canvas = el("canvas", {
    role: "img",
    "aria-label":
      `Barras horizontales con los ${datos.temas.length} temas más cubiertos. ` +
      datos.temas
        .map((tema) => `${tema.tema}: ${tema.total} noticias`)
        .join("; ") +
      ".",
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
          el("h2", { clase: "tarjeta__titulo", id: "titulo-tendencias", texto: "Temas más cubiertos" }),
          el("p", {
            clase: "tarjeta__pregunta",
            texto:
              "¿Cuáles son los temas más cubiertos por los medios ecuatorianos " +
              "analizados durante el periodo de recolección?",
          })
        ),
        controlDeLimite()
      ),
      respuesta(datos),
      // El alto crece con la cantidad de barras en vez de ser fijo: con un alto
      // fijo, un top 5 queda nadando en blanco y un top 20 sale apretado.
      // Los 64 px extra son la banda del eje horizontal, que tiene que caber
      // dentro del contenedor o aparece un scroll minusculo en la tarjeta.
      el(
        "div",
        {
          clase: "grafico",
          estilo: { height: `${datos.temas.length * 46 + 64}px` },
        },
        canvas
      ),
      el("p", {
        clase: "cifra__nota",
        texto:
          "Los porcentajes son sobre las noticias clasificadas, no sobre el total " +
          "recolectado: incluir las pendientes bajaría a todos los temas por igual " +
          "y haría ilegible la comparación.",
      }),
      tablaEquivalente({
        resumen: `Top ${datos.limite} de temas · ${formatearRango(
          datos.periodo.desde,
          datos.periodo.hasta
        )} · ${nombreDeMedio(datos.medio)}`,
        columnas: [
          { titulo: "Tema", valor: (fila) => fila.tema },
          { titulo: "Noticias", valor: (fila) => formatearNumero(fila.total) },
          { titulo: "% de las clasificadas", valor: (fila) => formatearPorcentaje(fila.porcentaje) },
        ],
        filas: datos.temas,
      })
    )
  );

  limpiar(contenedor).append(envoltura);

  grafico = destruir(grafico);
  grafico = crearBarras(canvas, {
    etiquetas: datos.temas.map((tema) => tema.tema),
    series: [
      {
        etiqueta: "Noticias",
        datos: datos.temas.map((tema) => tema.total),
        // Slot 1 para la unica serie. El color pertenece a "cantidad de
        // noticias", no al primer puesto del ranking.
        color: colorDeSerie(0),
      },
    ],
    horizontal: true,
    etiquetasDirectas: true,
    formatoValor: formatearNumero,
    formatoTooltip: (contexto) => {
      const tema = datos.temas[contexto.dataIndex];
      return `${formatearNumero(tema.total)} noticias · ${formatearPorcentaje(tema.porcentaje)}`;
    },
  });
}

const vista = {
  id: "tendencias",
  titulo: "Temas más cubiertos",

  montar(nodo) {
    contenedor = nodo;
    esPrimerRender = true;
  },

  async actualizar(filtros) {
    filtrosActuales = filtros;

    if (esPrimerRender) {
      mostrarCargando(contenedor);
    } else {
      // Refetch: se atenua el render anterior en vez de mostrar un esqueleto,
      // para que no parpadee ni salte el layout al mover un filtro.
      marcarCargando(contenedor.firstElementChild, true);
    }

    let datos;
    try {
      datos = await api.obtenerTopTemas({ limite, ...filtros });
    } catch (error) {
      // Un abort es una peticion que nosotros mismos cancelamos por otra mas
      // nueva: no es un error que deba ver el usuario.
      if (error.name === "AbortError") return;
      mostrarError(contenedor, {
        mensaje: error.message,
        alReintentar: () => vista.actualizar(filtrosActuales),
      });
      esPrimerRender = true;
      return;
    }

    esPrimerRender = false;

    // El cabezote muestra el periodo real de los datos, que el backend deduce
    // de la primera y la ultima noticia cuando no se filtra por fecha.
    document.dispatchEvent(
      new CustomEvent("noticia:periodo", {
        detail: { desde: datos.periodo.desde, hasta: datos.periodo.hasta },
      })
    );

    grafico = destruir(grafico);

    if (datos.total_noticias === 0) {
      mostrarVacio(contenedor, {
        mensaje:
          "No hay noticias recolectadas en este rango de fechas. Ampliá el periodo " +
          "o corré el scraper: cd scraper && bundle exec ruby scraper.rb",
      });
      esPrimerRender = true;
      return;
    }

    if (datos.temas.length === 0) {
      mostrarVacio(contenedor, {
        titulo: "Hay noticias, pero ninguna clasificada",
        mensaje:
          `Se recolectaron ${formatearNumero(datos.total_noticias)} noticias en este periodo ` +
          `y todas siguen con tema pendiente, así que no hay ranking que mostrar. ` +
          `Corré el pipeline de clasificación: python -m backend.pipeline.procesar`,
      });
      esPrimerRender = true;
      return;
    }

    pintar(datos);
  },

  desmontar() {
    grafico = destruir(grafico);
    if (contenedor) limpiar(contenedor);
    contenedor = null;
    esPrimerRender = true;
  },
};

export default vista;
