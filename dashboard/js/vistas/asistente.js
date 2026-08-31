/* Vista: asistente de IA generativa.  Issue #3 - Cristian.
 *
 * Es la unica vista que ESCRIBE contra la API (POST /api/asistente/preguntar);
 * las otras cuatro solo leen. De ahi salen casi todas sus diferencias:
 *
 * 1. No se dispara sola. Las demas vistas refetchean en cada cambio de filtro;
 *    aca cada llamada consume cuota de un proveedor pago, asi que la peticion
 *    sale UNICAMENTE cuando el usuario manda la pregunta. actualizar() solo
 *    repinta el aviso de filtros.
 * 2. Lleva token CSRF. Al ser un POST autenticado por cookie, api.js le agrega
 *    el header X-CSRF-Token (ver backend/auth.py).
 * 3. Tolera la espera. El LLM puede tardar decenas de segundos, asi que el
 *    turno se pinta primero en estado "pensando" y despues se completa.
 *
 * Por que se ven las fuentes
 * --------------------------
 * El backend cortocircuita y NO llama al modelo cuando no encuentra noticias
 * que citar. Lo que se muestra debajo de cada respuesta son las noticias
 * reales que se le pasaron como contexto: sin esa lista, la respuesta seria
 * indistinguible de una alucinacion y no se podria auditar.
 *
 * La respuesta del LLM y los titulares son entrada NO confiable: todo el DOM
 * se arma con el() de ui.js, que inserta cualquier string como nodo de texto.
 */

import * as api from "../api.js";
import { el, formatearFecha, formatearNumero, limpiar, mostrarError } from "../ui.js";

const LARGO_MAXIMO = 500; // igual que LARGO_MAXIMO_PREGUNTA en el backend
const CONTEXTO_POR_DEFECTO = 20;

// Preguntas de arranque. No son decorado: una pantalla de chat en blanco no
// dice que puede responder.
//
// Estan VERIFICADAS contra el corpus recolectado: las tres recuperan noticias
// hoy. No es un detalle menor -- las tres primeras que se escribieron aca
// devolvian cero, y una sugerencia que responde "no tengo datos suficientes"
// hace parecer roto al asistente justo en el primer clic. Si el corpus cambia
// mucho, conviene volver a comprobarlas.
//
// Cada una ejercita una capacidad distinta del recuperador:
//   1. filtro por tema + comparacion entre medios
//   2. filtro por tema, sin ningun termino de busqueda
//   3. busqueda por texto libre
//
// Y una que NO conviene sugerir: nada con "esta semana" o "hoy". El corpus se
// llena cuando corre el scraper, asi que si hace dias que no corre, cualquier
// pregunta anclada al presente devuelve cero -- correctamente, pero parece un
// error. Ver el aviso de periodo en el cabezote.
const SUGERENCIAS = [
  "¿Qué publicó cada medio sobre seguridad?",
  "Resumime las noticias de deportes",
  "¿Qué pasó con el operativo policial?",
];

let contenedor = null;
let nodoAviso = null;
let nodoHilo = null;
let campoPregunta = null;
let contadorLargo = null;
let botonEnviar = null;
let filtrosActuales = {};
let enviando = false;

// El hilo vive a nivel de modulo y no dentro del contenedor: asi cambiar de
// vista y volver no borra la conversacion. Cada turno es
// { pregunta, estado: "pensando" | "lista" | "error", datos, mensaje }.
let hilo = [];

/* -------------------------------------------------------------------------
   Armazon: se construye una sola vez (ver el comentario de buscador.js sobre
   por que el formulario no se puede repintar en cada actualizacion).
   ------------------------------------------------------------------------- */

function contarCaracteres() {
  const largo = campoPregunta.value.length;
  contadorLargo.textContent = `${formatearNumero(largo)} / ${formatearNumero(LARGO_MAXIMO)}`;
  contadorLargo.classList.toggle("asistente__contador--tope", largo >= LARGO_MAXIMO);
}

function sugerencias() {
  return el(
    "div",
    { clase: "controles controles--bloque" },
    el("span", { clase: "controles__rotulo", texto: "Para empezar" }),
    el(
      "div",
      { clase: "fichas", role: "group", "aria-label": "Preguntas sugeridas" },
      SUGERENCIAS.map((texto) =>
        el("button", {
          clase: "ficha",
          type: "button",
          texto,
          onClick: () => {
            campoPregunta.value = texto;
            contarCaracteres();
            campoPregunta.focus();
          },
        })
      )
    )
  );
}

function formulario() {
  campoPregunta = el("textarea", {
    id: "asistente-pregunta",
    rows: 3,
    maxlength: LARGO_MAXIMO,
    // El ejemplo tambien tiene que ser respondible con lo recolectado: el
    // anterior preguntaba por el diesel, que no aparece en ninguna noticia.
    placeholder: "Ej.: ¿Qué se publicó sobre seguridad?",
    onInput: contarCaracteres,
    onKeyDown: (evento) => {
      // Enter manda, Shift+Enter hace salto de linea. En un textarea el
      // default es al reves, y aca la pregunta casi siempre es de una linea.
      if (evento.key === "Enter" && !evento.shiftKey) {
        evento.preventDefault();
        preguntar();
      }
    },
  });

  contadorLargo = el("span", { clase: "asistente__contador", "aria-hidden": "true" });
  botonEnviar = el("button", { clase: "boton", type: "submit", texto: "Preguntar" });
  contarCaracteres();

  return el(
    "form",
    {
      clase: "asistente__forma",
      onSubmit: (evento) => {
        evento.preventDefault();
        preguntar();
      },
    },
    el("label", {
      clase: "filtros__etiqueta",
      for: "asistente-pregunta",
      texto: "Tu pregunta sobre las noticias recolectadas",
    }),
    campoPregunta,
    el(
      "div",
      { clase: "asistente__pie" },
      el("span", {
        clase: "asistente__ayuda",
        texto: "Enter envía · Shift+Enter agrega una línea",
      }),
      contadorLargo,
      botonEnviar
    )
  );
}

/* El asistente arma su contexto leyendo la propia pregunta (ver
   backend/services/recuperador.py: detecta el tema y expresiones como "esta
   semana"), no la barra de filtros. Decirlo evita que alguien concluya que el
   asistente le miente cuando en realidad esta mirando otro recorte. */
function avisoDeFiltros() {
  const { desde, hasta, medio } = filtrosActuales;
  if (!desde && !hasta && !medio) return null;

  return el(
    "div",
    { clase: "sello surge", role: "status" },
    el("span", { clase: "sello__titulo", texto: "Filtros ignorados" }),
    el(
      "span",
      {},
      "El asistente busca en todas las noticias recolectadas: los filtros de la " +
        "barra de arriba no se le aplican. Para acotar el periodo o el medio, " +
        "decílo dentro de la pregunta (por ejemplo: “esta semana”)."
    )
  );
}

function armazon() {
  nodoAviso = el("div", {});
  nodoHilo = el("div", {
    clase: "hilo",
    // El turno nuevo aparece por JS; sin esto un lector de pantalla no se
    // entera de que llego la respuesta.
    "aria-live": "polite",
    "aria-busy": "false",
  });

  return el(
    "section",
    { clase: "tarjeta surge" },
    el(
      "header",
      { clase: "tarjeta__cabecera" },
      el(
        "div",
        {},
        el("h2", { clase: "tarjeta__titulo", id: "titulo-asistente", texto: "Asistente de IA" }),
        el("p", {
          clase: "tarjeta__pregunta",
          texto:
            "Preguntá en lenguaje natural sobre las noticias recolectadas. La " +
            "respuesta se construye únicamente con las noticias que aparecen " +
            "citadas debajo: si no hay ninguna, el asistente lo dice en vez de " +
            "inventar.",
        })
      )
    ),
    nodoAviso,
    formulario(),
    sugerencias(),
    nodoHilo
  );
}

/* -------------------------------------------------------------------------
   Hilo de la conversacion
   ------------------------------------------------------------------------- */

/** Plural en castellano, sin el "(s)" de programador. */
function plural(cantidad, singular, enPlural) {
  return `${formatearNumero(cantidad)} ${cantidad === 1 ? singular : enPlural}`;
}

/**
 * Convierte los **negritas** de markdown en nodos <strong>.
 *
 * El modelo estructura sus respuestas con markdown por su cuenta, y antes se
 * veian los asteriscos literales en pantalla. NO se resuelve con innerHTML: la
 * respuesta de un LLM es entrada no confiable como cualquier otra, asi que se
 * parte el texto y se emiten nodos. Se reconoce solo la negrita, que es lo
 * unico que el modelo usa de forma consistente; lo que no calce queda como
 * texto plano, que es un peor caso aceptable.
 */
function conNegritas(texto) {
  const nodos = [];
  const patron = /\*\*(.+?)\*\*/g;
  let ultimo = 0;
  let calce;

  while ((calce = patron.exec(texto)) !== null) {
    if (calce.index > ultimo) nodos.push(texto.slice(ultimo, calce.index));
    nodos.push(el("strong", { texto: calce[1] }));
    ultimo = calce.index + calce[0].length;
  }

  if (ultimo < texto.length) nodos.push(texto.slice(ultimo));
  return nodos.length ? nodos : [texto];
}

/** El texto del modelo viene con saltos de linea: se respetan como parrafos. */
function parrafos(texto) {
  return String(texto || "")
    .split(/\n{2,}/)
    .map((bloque) => bloque.trim())
    .filter(Boolean)
    .map((bloque) => el("p", {}, conNegritas(bloque)));
}

function fuente(nota) {
  return el(
    "article",
    { clase: "nota" },
    el(
      "p",
      { clase: "nota__meta" },
      el("span", { clase: "nota__medio", texto: nota.medio }),
      el("span", { texto: formatearFecha(nota.fecha) })
    ),
    el(
      "h4",
      { clase: "nota__titular" },
      el(
        "a",
        { href: nota.url, target: "_blank", rel: "noopener noreferrer" },
        nota.titular
      )
    )
  );
}

function fuentes(datos) {
  if (!datos.fuentes?.length) return null;

  return el(
    "details",
    { clase: "tabla-datos" },
    el("summary", {
      texto:
        `Ver ${plural(datos.fuentes.length, "la noticia", "las noticias")} ` +
        `que fundamenta${datos.fuentes.length === 1 ? "" : "n"} la respuesta`,
    }),
    el("div", { clase: "notas" }, datos.fuentes.map(fuente))
  );
}

function pieDelTurno(datos) {
  const partes = [
    `${plural(datos.noticias_consultadas, "noticia", "noticias")} ` +
      `consultada${datos.noticias_consultadas === 1 ? "" : "s"}`,
  ];
  // Sin modelo = el backend cortocircuito y nunca llamo al LLM. Se dice, para
  // que quede claro que esa respuesta no la escribio el modelo.
  partes.push(datos.modelo ? `modelo: ${datos.modelo}` : "sin llamada al modelo");
  return el("p", { clase: "turno__meta", texto: partes.join(" · ") });
}

function pintarTurno(turno) {
  const cuerpo = el("div", { clase: "turno__respuesta" });

  if (turno.estado === "pensando") {
    cuerpo.append(
      el("p", { clase: "turno__pensando", texto: "Consultando las noticias y redactando…" })
    );
  } else if (turno.estado === "error") {
    mostrarError(cuerpo, {
      mensaje: turno.mensaje,
      alReintentar: () => reintentar(turno),
    });
  } else {
    cuerpo.append(...parrafos(turno.datos.respuesta), pieDelTurno(turno.datos), fuentes(turno.datos));
  }

  return el(
    "article",
    { clase: "turno" },
    el("p", { clase: "turno__pregunta", texto: turno.pregunta }),
    cuerpo
  );
}

function pintarHilo() {
  if (!nodoHilo) return;
  limpiar(nodoHilo);
  nodoHilo.setAttribute("aria-busy", String(hilo.some((turno) => turno.estado === "pensando")));

  if (hilo.length === 0) {
    nodoHilo.append(
      el(
        "div",
        { clase: "estado", role: "status" },
        el("p", { clase: "estado__titulo", texto: "Todavía no hay preguntas" }),
        el("p", {
          clase: "estado__texto",
          texto:
            "Escribí una pregunta arriba o tocá una de las sugeridas. Las respuestas " +
            "se quedan en esta pantalla mientras no recargues la página.",
        })
      )
    );
    return;
  }

  // Del turno mas nuevo al mas viejo: lo recien preguntado queda a la vista sin
  // tener que bajar por toda la conversacion.
  for (const turno of hilo) nodoHilo.prepend(pintarTurno(turno));
}

/* -------------------------------------------------------------------------
   Peticion
   ------------------------------------------------------------------------- */

function bloquearEnvio(activo) {
  enviando = activo;
  if (botonEnviar) {
    botonEnviar.disabled = activo;
    botonEnviar.textContent = activo ? "Preguntando…" : "Preguntar";
  }
}

/* Recibe el TURNO y no su indice a proposito: una peticion cancelada saca su
   turno del hilo, y un indice capturado antes de eso apuntaria al turno
   equivocado. La referencia al objeto sobrevive a cualquier reordenamiento. */
async function resolver(turno) {
  bloquearEnvio(true);

  try {
    turno.datos = await api.preguntarAsistente({
      pregunta: turno.pregunta,
      limiteContexto: CONTEXTO_POR_DEFECTO,
    });
    turno.estado = "lista";
  } catch (error) {
    // Otra pregunta cancelo esta: el turno nuevo ya se esta pintando, y dejar
    // este en "pensando" para siempre seria peor que borrarlo.
    if (error.name === "AbortError") {
      const posicion = hilo.indexOf(turno);
      if (posicion !== -1) hilo.splice(posicion, 1);
      pintarHilo();
      return;
    }
    turno.estado = "error";
    turno.mensaje = error.message;
  } finally {
    bloquearEnvio(false);
  }

  pintarHilo();
}

function reintentar(turno) {
  if (enviando || !hilo.includes(turno)) return;
  turno.estado = "pensando";
  pintarHilo();
  resolver(turno);
}

function preguntar() {
  if (enviando) return; // doble Enter no dispara dos llamadas al proveedor

  const pregunta = campoPregunta.value.trim();
  if (!pregunta) {
    campoPregunta.focus();
    return;
  }

  const turno = { pregunta, estado: "pensando", datos: null, mensaje: "" };
  hilo.push(turno);
  campoPregunta.value = "";
  contarCaracteres();
  pintarHilo();
  resolver(turno);
}

/* -------------------------------------------------------------------------
   Vista
   ------------------------------------------------------------------------- */

const vista = {
  id: "asistente",
  titulo: "Asistente de IA",

  montar(nodo) {
    contenedor = nodo;
    limpiar(contenedor).append(armazon());
    pintarHilo();
  },

  // Sin peticion: un cambio de filtro no puede gastar cuota del proveedor.
  // Lo unico que depende de los filtros es el aviso de que no se aplican.
  async actualizar(filtros) {
    filtrosActuales = filtros;
    // Se comprueba en vez de encadenar `|| ""`: append(null) inserta la cadena
    // "null" como texto, y un string vacio deja un nodo de texto de mas.
    limpiar(nodoAviso);
    const aviso = avisoDeFiltros();
    if (aviso) nodoAviso.append(aviso);
  },

  desmontar() {
    if (contenedor) limpiar(contenedor);
    contenedor = null;
    nodoAviso = null;
    nodoHilo = null;
    campoPregunta = null;
    contadorLargo = null;
    botonEnviar = null;
    // El hilo NO se borra: se vuelve a pintar al montar de nuevo. Una respuesta
    // que costo una llamada al LLM no se tira por cambiar de pestana.
    // Si quedo una peticion en vuelo, su turno sigue en "pensando" y se
    // completa igual porque resolver() no toca el DOM directamente.
  },
};

export default vista;
