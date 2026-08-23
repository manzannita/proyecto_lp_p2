/* Arranque del dashboard: tema de los graficos, barra de filtros y router.
 *
 * CONTRATO DE LAS VISTAS
 * ----------------------
 * Cada archivo de js/vistas/ exporta por defecto un objeto:
 *
 *   export default {
 *     id: "tendencias",
 *     titulo: "Temas mas cubiertos",
 *     montar(contenedor)         // una sola vez, al entrar a la vista
 *     async actualizar(filtros)  // al montar y en cada cambio de filtro
 *     desmontar()                // destruye graficos y listeners al salir
 *   }
 *
 * El contenedor que recibe es su <section id="vista-*"> y es TODO lo que puede
 * tocar del documento: index.html no se edita desde una vista. Asi los issues
 * #6, #7 y #8 no chocan nunca en el mismo archivo.
 *
 * Si una vista quiere que el cabezote muestre el periodo real de los datos,
 * despacha un evento en vez de importar este modulo (importarlo seria un ciclo):
 *
 *   document.dispatchEvent(new CustomEvent("noticia:periodo", {
 *     detail: { desde: "2026-08-14", hasta: "2026-08-23" },
 *   }))
 */

import * as api from "./api.js";
import * as estado from "./estado.js";
import * as graficos from "./graficos.js";
import { formatearPeriodo, mostrarError, mostrarPendiente } from "./ui.js";

const VISTAS = {
  tendencias: {
    contenedor: "vista-tendencias",
    cargar: () => import("./vistas/tendencias.js"),
    issue: 6,
    responsable: "Annabella",
    titulo: "Temas más cubiertos",
  },
  comparativa: {
    contenedor: "vista-comparativa",
    cargar: () => import("./vistas/comparativa.js"),
    issue: 7,
    responsable: "Valentina",
    titulo: "Comparativa entre medios",
  },
  series: {
    contenedor: "vista-series",
    cargar: () => import("./vistas/series.js"),
    issue: 8,
    responsable: "Cristian",
    titulo: "Evolución semanal por tema",
  },
  buscador: {
    contenedor: "vista-buscador",
    cargar: () => import("./vistas/buscador.js"),
    issue: 8,
    responsable: "Cristian",
    titulo: "Buscador de noticias",
  },
};

const VISTA_POR_DEFECTO = "tendencias";

let vistaActiva = null; // { nombre, modulo, contenedor }

/* -------------------------------------------------------------------------
   Cabezote
   ------------------------------------------------------------------------- */

function pintarDateline(desde, hasta) {
  const nodo = document.getElementById("dateline-periodo");
  if (nodo) nodo.textContent = formatearPeriodo(desde, hasta);
}

// Una vista con datos reporta el periodo REAL de las noticias, que puede ser
// mas angosto que el filtro pedido. Ese dato manda sobre el del filtro.
document.addEventListener("noticia:periodo", (evento) => {
  const { desde, hasta } = evento.detail || {};
  pintarDateline(desde, hasta);
});

/* -------------------------------------------------------------------------
   Barra de filtros
   ------------------------------------------------------------------------- */

async function prepararFiltros() {
  const formulario = document.getElementById("filtros");
  const entradaDesde = document.getElementById("filtro-desde");
  const entradaHasta = document.getElementById("filtro-hasta");
  const selectorMedio = document.getElementById("filtro-medio");
  const aviso = document.getElementById("filtros-aviso");

  // Los controles arrancan con lo que venga en la URL, no en blanco: si no,
  // compartir el enlace mostraria el grafico filtrado y los campos vacios.
  const inicial = estado.obtener();
  entradaDesde.value = inicial.desde;
  entradaHasta.value = inicial.hasta;

  // El catalogo de medios viene del backend; no se escriben los slugs a mano.
  try {
    const medios = await api.obtenerMedios();
    for (const medio of medios) {
      const opcion = document.createElement("option");
      opcion.value = medio.slug;
      opcion.textContent = `${medio.nombre} (${medio.total_noticias})`;
      selectorMedio.append(opcion);
    }
    selectorMedio.value = inicial.medio;
  } catch (error) {
    // Que falle el catalogo no debe tumbar el dashboard: el filtro de medio
    // queda solo con "todos" y las vistas siguen funcionando.
    aviso.textContent = `No se pudo cargar el catálogo de medios: ${error.message}`;
  }

  formulario.addEventListener("change", () => {
    const candidatos = {
      desde: entradaDesde.value,
      hasta: entradaHasta.value,
      medio: selectorMedio.value,
    };

    // Se avisa en el cliente en vez de esperar el 400 del backend.
    const problema = estado.validar(candidatos);
    aviso.textContent = problema || "";
    if (problema) return;

    estado.actualizar(candidatos);
  });

  formulario.addEventListener("reset", () => {
    // El reset del formulario ocurre despues del evento, por eso el setTimeout.
    setTimeout(() => {
      aviso.textContent = "";
      estado.actualizar({ desde: "", hasta: "", medio: "" });
    }, 0);
  });
}

/* -------------------------------------------------------------------------
   Router por hash
   ------------------------------------------------------------------------- */

function nombreDeVistaEnUrl() {
  const nombre = window.location.hash.replace(/^#\/?/, "").trim();
  return nombre in VISTAS ? nombre : nombre === "asistente" ? "asistente" : VISTA_POR_DEFECTO;
}

function marcarNavegacion(nombre) {
  for (const enlace of document.querySelectorAll(".navegacion__enlace")) {
    if (enlace.dataset.vista === nombre) enlace.setAttribute("aria-current", "page");
    else enlace.removeAttribute("aria-current");
  }
}

function mostrarSolo(idContenedor) {
  for (const seccion of document.querySelectorAll(".vista")) {
    seccion.hidden = seccion.id !== idContenedor;
  }
}

async function irA(nombre) {
  if (vistaActiva?.nombre === nombre) return;

  // Salir de la vista anterior: destruir sus graficos y sus listeners. Si no,
  // cada visita deja una instancia de Chart.js viva sobre el mismo canvas.
  if (vistaActiva?.modulo?.desmontar) {
    try {
      vistaActiva.modulo.desmontar();
    } catch (error) {
      console.error("[main] fallo al desmontar la vista", vistaActiva.nombre, error);
    }
  }
  vistaActiva = null;

  // El asistente existe en el backend pero su pantalla es del avance 3.
  if (nombre === "asistente") {
    const contenedor = document.getElementById("vista-tendencias");
    mostrarSolo("vista-tendencias");
    marcarNavegacion("tendencias");
    mostrarPendiente(contenedor, {
      titulo: "El asistente de IA llega en el avance 3",
      issue: 3,
      responsable: "Cristian",
    });
    return;
  }

  const definicion = VISTAS[nombre];
  const contenedor = document.getElementById(definicion.contenedor);
  mostrarSolo(definicion.contenedor);
  marcarNavegacion(nombre);

  // Periodo pedido por los filtros, para que el cabezote diga algo cierto
  // aunque la vista todavia no exista. Si la vista trae datos, lo sobreescribe.
  const filtros = estado.obtener();
  pintarDateline(filtros.desde, filtros.hasta);

  let modulo;
  try {
    modulo = (await definicion.cargar()).default;
  } catch (error) {
    // El modulo de la vista todavia no existe (es de otro issue del avance) o
    // tiene un error de sintaxis. Se distingue una cosa de la otra en consola,
    // y en pantalla se explica de quien es la vista.
    console.warn(`[main] no se pudo cargar la vista "${nombre}"`, error);
    mostrarPendiente(contenedor, {
      titulo: definicion.titulo,
      issue: definicion.issue,
      responsable: definicion.responsable,
    });
    return;
  }

  vistaActiva = { nombre, modulo, contenedor };

  try {
    modulo.montar(contenedor);
    await modulo.actualizar(estado.obtener());
  } catch (error) {
    console.error(`[main] fallo la vista "${nombre}"`, error);
    mostrarError(contenedor, {
      mensaje: error.message || "Error inesperado al dibujar la vista.",
      alReintentar: () => modulo.actualizar(estado.obtener()),
    });
  }
}

/* -------------------------------------------------------------------------
   Arranque
   ------------------------------------------------------------------------- */

async function arrancar() {
  try {
    graficos.inicializar();
  } catch (error) {
    mostrarError(document.getElementById("vista-tendencias"), {
      mensaje: error.message,
    });
    document.getElementById("vista-tendencias").hidden = false;
    return;
  }

  await prepararFiltros();

  // Un cambio de filtro no cambia de vista: solo le pide a la activa que se
  // vuelva a dibujar con el nuevo recorte.
  estado.suscribir(async (filtros) => {
    pintarDateline(filtros.desde, filtros.hasta);
    if (!vistaActiva) return;
    try {
      await vistaActiva.modulo.actualizar(filtros);
    } catch (error) {
      console.error("[main] fallo al actualizar la vista", error);
    }
  });

  window.addEventListener("hashchange", () => irA(nombreDeVistaEnUrl()));

  if (!window.location.hash) {
    window.history.replaceState(null, "", `${window.location.search}#/${VISTA_POR_DEFECTO}`);
  }
  await irA(nombreDeVistaEnUrl());
}

arrancar();
