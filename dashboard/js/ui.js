/* Piezas de interfaz compartidas: construccion de DOM, estados y formateo.
 *
 * Todo el DOM del dashboard se arma con el() y nunca con innerHTML. No es
 * preferencia de estilo: los titulares vienen de sitios externos, o sea que son
 * entrada NO confiable, y concatenarlos en HTML seria un XSS de manual. el()
 * usa append(), que inserta cualquier string como texto.
 */

/* -------------------------------------------------------------------------
   Construccion de DOM
   ------------------------------------------------------------------------- */

/**
 * Crea un elemento.
 *   el("p", { clase: "cifra__nota", texto: "131 noticias" })
 *   el("div", { clase: "tarjeta" }, titulo, canvas)
 *
 * Propiedades especiales: clase, texto, estilo y cualquier on<Evento>.
 * El resto se aplica como atributo, asi que los aria-* funcionan directo.
 */
export function el(etiqueta, propiedades = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);

  for (const [clave, valor] of Object.entries(propiedades)) {
    if (valor === undefined || valor === null || valor === false) continue;

    if (clave === "clase") nodo.className = valor;
    else if (clave === "texto") nodo.textContent = valor;
    else if (clave === "estilo") Object.assign(nodo.style, valor);
    else if (clave.startsWith("on") && typeof valor === "function") {
      nodo.addEventListener(clave.slice(2).toLowerCase(), valor);
    } else nodo.setAttribute(clave, valor === true ? "" : valor);
  }

  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    nodo.append(hijo); // un string entra como nodo de TEXTO, nunca como HTML
  }

  return nodo;
}

/** Deja el contenedor vacio antes de volver a pintarlo. */
export function limpiar(contenedor) {
  contenedor.replaceChildren();
  return contenedor;
}

/* -------------------------------------------------------------------------
   Tabla equivalente
   ------------------------------------------------------------------------- */

/**
 * El gemelo accesible de un grafico: los mismos numeros en una tabla.
 * Un <canvas> no existe para un lector de pantalla, y ademas asi se puede
 * copiar los datos al reporte del avance.
 *
 * columnas: [{ titulo, valor: (fila) => string | Node }]
 */
export function tablaEquivalente({ resumen, columnas, filas, abierta = false }) {
  const cabecera = el(
    "tr",
    {},
    columnas.map((columna) => el("th", { scope: "col", texto: columna.titulo }))
  );

  const cuerpo = filas.map((fila) =>
    el(
      "tr",
      {},
      columnas.map((columna, indice) => {
        const contenido = columna.valor(fila);
        const celda = indice === 0 ? el("th", { scope: "row" }) : el("td", {});
        celda.append(contenido ?? "");
        return celda;
      })
    )
  );

  return el(
    "details",
    { clase: "tabla-datos", open: abierta },
    el("summary", { texto: "Ver los datos en tabla" }),
    el(
      "div",
      { clase: "tabla-envoltura" },
      el(
        "table",
        { clase: "datos" },
        resumen ? el("caption", { texto: resumen }) : null,
        el("thead", {}, cabecera),
        el("tbody", {}, cuerpo)
      )
    )
  );
}

/* -------------------------------------------------------------------------
   Estados
   ------------------------------------------------------------------------- */

/** Primera carga: esqueleto. No hay render anterior que atenuar. */
export function mostrarCargando(contenedor, { conCifras = true } = {}) {
  limpiar(contenedor).append(
    ...(conCifras ? [el("div", { clase: "esqueleto esqueleto--cifras" })] : []),
    el("div", { clase: "esqueleto esqueleto--grafico" }),
    el("p", {
      clase: "visualmente-oculto",
      role: "status",
      texto: "Cargando datos…",
    })
  );
}

/**
 * Recargas posteriores: se mantiene el render anterior atenuado.
 * Un esqueleto en cada cambio de filtro produce parpadeo y salto de layout.
 */
export function marcarCargando(elemento, activo) {
  if (elemento) elemento.classList.toggle("esta-cargando", Boolean(activo));
}

export function mostrarError(contenedor, { mensaje, alReintentar }) {
  limpiar(contenedor).append(
    el(
      "div",
      { clase: "estado estado--error", role: "alert" },
      el("p", { clase: "estado__titulo", texto: "No se pudieron cargar los datos" }),
      el("p", { clase: "estado__texto", texto: mensaje }),
      alReintentar
        ? el("button", { clase: "boton", type: "button", onClick: alReintentar, texto: "Reintentar" })
        : null
    )
  );
}

export function mostrarVacio(contenedor, { titulo = "Sin datos en este periodo", mensaje }) {
  limpiar(contenedor).append(
    el(
      "div",
      { clase: "estado", role: "status" },
      el("p", { clase: "estado__titulo", texto: titulo }),
      el("p", { clase: "estado__texto", texto: mensaje })
    )
  );
}

/** Vista que todavia no existe porque es de otro issue del avance. */
export function mostrarPendiente(contenedor, { titulo, issue, responsable }) {
  limpiar(contenedor).append(
    el(
      "div",
      { clase: "estado", role: "status" },
      el("p", { clase: "estado__titulo", texto: titulo }),
      el("p", {
        clase: "estado__texto",
        texto:
          `Esta vista es del issue #${issue} (${responsable}) del avance 2. ` +
          `La fundación del dashboard ya está lista, así que solo falta su módulo ` +
          `en dashboard/js/vistas/.`,
      })
    )
  );
}

/* -------------------------------------------------------------------------
   Formateo
   ------------------------------------------------------------------------- */

const numero = new Intl.NumberFormat("es-EC");
const decimal = new Intl.NumberFormat("es-EC", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function formatearNumero(valor) {
  return Number.isFinite(valor) ? numero.format(valor) : "—";
}

export function formatearPorcentaje(valor) {
  return Number.isFinite(valor) ? `${decimal.format(valor)} %` : "—";
}

/** Diferencia entre dos porcentajes: se mide en PUNTOS, no en porcentaje. */
export function formatearPuntos(valor) {
  return Number.isFinite(valor) ? `${decimal.format(valor)} puntos` : "—";
}

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/** "2026-08-23 14:03:00" o "2026-08-23" -> "23 ago 2026". */
export function formatearFecha(valor) {
  if (!valor) return "—";
  const [anio, mes, dia] = String(valor).slice(0, 10).split("-");
  if (!anio || !mes || !dia) return String(valor);
  return `${Number(dia)} ${MESES[Number(mes) - 1] || mes} ${anio}`;
}

export function formatearRango(desde, hasta) {
  if (!desde && !hasta) return "sin datos";
  return `${formatearFecha(desde)} — ${formatearFecha(hasta)}`;
}

/** Periodo para el cabezote, incluyendo los rangos abiertos de un solo lado. */
export function formatearPeriodo(desde, hasta) {
  if (desde && hasta) return formatearRango(desde, hasta);
  if (desde) return `desde ${formatearFecha(desde)}`;
  if (hasta) return `hasta ${formatearFecha(hasta)}`;
  return "todo el periodo recolectado";
}

/** "2026-W34" -> "sem. 34 / 2026". */
export function formatearSemanaIso(valor) {
  if (!valor) return "—";
  const [anio, semana] = String(valor).split("-W");
  return semana ? `sem. ${Number(semana)} / ${anio}` : String(valor);
}
