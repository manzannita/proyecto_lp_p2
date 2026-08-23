/* Tema visual UNICO de todos los graficos del proyecto.
 *
 * Las tres vistas (issues #6, #7 y #8) construyen sus graficos con estos
 * helpers y no configuran Chart.js por su cuenta: si cada quien pusiera sus
 * colores y sus ejes, el dashboard se leeria como tres trabajos distintos.
 *
 * Reglas de datos que este modulo hace cumplir:
 *   - Los colores salen de las variables CSS (--serie-1..8), asi que el CSS es
 *     la unica fuente de verdad de la paleta.
 *   - El ORDEN de la paleta es fijo y no se cicla. Esta validada con el script
 *     validate_palette.js sobre la superficie #f8f6f0: pares adyacentes con
 *     separacion suficiente tambien para daltonismo protan/deutan.
 *   - El color sigue a la ENTIDAD, no a su posicion en el ranking: filtrar una
 *     serie no repinta a las que quedan.
 *   - Una sola serie -> un solo color, nunca una rampa por valor.
 *   - Grilla y ejes en filete solido de un tono sobre el papel, jamas punteados.
 */

const raiz = getComputedStyle(document.documentElement);
const token = (nombre) => raiz.getPropertyValue(nombre).trim();

export const TOKENS = {
  tinta: token("--tinta"),
  tinta2: token("--tinta-2"),
  tinta3: token("--tinta-3"),
  regla: token("--regla"),
  reglaFuerte: token("--regla-fuerte"),
  papelTarjeta: token("--papel-tarjeta"),
  bermellon: token("--bermellon"),
  mono: token("--mono"),
  display: token("--display"),
};

/** Paleta categorica en orden fijo. */
export const PALETA = Array.from({ length: 8 }, (_, i) => token(`--serie-${i + 1}`));

/** Color del slot pedido. Pasado el octavo NO se generan ni se reciclan hues:
 *  el catalogo de temas tiene 8 entradas y la octava es justamente "otros". */
export function colorDeSerie(indice) {
  if (indice >= PALETA.length) {
    console.warn(
      `[graficos] Se pidio el color ${indice + 1} y la paleta tiene ${PALETA.length}. ` +
        `Agrupa el resto en "otros" o divide el grafico en varios.`
    );
    return TOKENS.tinta3;
  }
  return PALETA[indice];
}

const sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Etiquetas al final de la barra. Chart.js no las trae, y sin ellas el valor
   solo se puede leer pasando el mouse: un tooltip nunca puede ser la unica
   forma de leer un dato. Si la etiqueta no cabe fuera de la barra, se dibuja
   dentro en color papel en vez de desbordarse o quedar cortada. */
const etiquetasAlFinal = {
  id: "etiquetasAlFinal",
  afterDatasetsDraw(chart, _args, opciones) {
    if (!opciones || opciones.activo !== true) return;

    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.font = `500 11px ${TOKENS.mono}`;
    ctx.textBaseline = "middle";

    chart.data.datasets.forEach((dataset, indiceSerie) => {
      const meta = chart.getDatasetMeta(indiceSerie);
      if (meta.hidden) return;

      meta.data.forEach((elemento, i) => {
        const valor = dataset.data[i];
        if (valor === null || valor === undefined) return;

        const texto = opciones.formato ? opciones.formato(valor, i) : String(valor);
        const ancho = ctx.measureText(texto).width;
        const cabeAfuera = elemento.x + 8 + ancho < chartArea.right;

        ctx.fillStyle = cabeAfuera ? TOKENS.tinta2 : TOKENS.papelTarjeta;
        ctx.textAlign = cabeAfuera ? "left" : "right";
        ctx.fillText(texto, cabeAfuera ? elemento.x + 8 : elemento.x - 8, elemento.y);
      });
    });

    ctx.restore();
  },
};

let inicializado = false;

/** Aplica el tema a Chart.js. main.js la llama una sola vez al arrancar. */
export function inicializar() {
  if (inicializado) return;
  if (typeof window.Chart === "undefined") {
    throw new Error("Chart.js no se cargo: revisa vendor/chart.umd.min.js");
  }
  const { Chart } = window;

  Chart.defaults.font.family = TOKENS.mono;
  Chart.defaults.font.size = 11;
  Chart.defaults.color = TOKENS.tinta3;
  Chart.defaults.animation = sinMovimiento ? false : { duration: 380 };
  Chart.defaults.maintainAspectRatio = false;

  // Tooltip con la misma voz que el resto: tinta sobre papel, mono, sin sombra.
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: TOKENS.tinta,
    titleColor: "#f8f6f0",
    bodyColor: "#e7e2d5",
    titleFont: { family: TOKENS.mono, size: 11, weight: "600" },
    bodyFont: { family: TOKENS.mono, size: 12 },
    padding: 10,
    cornerRadius: 3,
    displayColors: true,
    boxWidth: 8,
    boxHeight: 8,
    boxPadding: 4,
  });

  Object.assign(Chart.defaults.plugins.legend, {
    position: "top",
    align: "start",
    labels: {
      usePointStyle: true,
      pointStyle: "rect",
      boxWidth: 9,
      boxHeight: 9,
      padding: 14,
      color: TOKENS.tinta2,
      font: { family: TOKENS.mono, size: 11 },
    },
  });

  Chart.register(etiquetasAlFinal);
  inicializado = true;
}

/** Ejes con grilla capilar en un solo sentido y sin borde grueso. */
function ejes({ horizontal = false, apilado = false, formatoValor } = {}) {
  const ejeValor = {
    stacked: apilado,
    beginAtZero: true,
    border: { display: false },
    grid: { color: TOKENS.regla, drawTicks: false },
    ticks: {
      color: TOKENS.tinta3,
      precision: 0,
      padding: 8,
      callback: formatoValor,
    },
  };

  const ejeCategoria = {
    stacked: apilado,
    border: { color: TOKENS.reglaFuerte },
    // La grilla del eje de categorias solo agrega ruido: la separacion entre
    // barras ya la da el espacio en blanco.
    grid: { display: false },
    ticks: { color: TOKENS.tinta2, padding: 8, autoSkip: false },
  };

  return horizontal
    ? { x: ejeValor, y: ejeCategoria }
    : { x: ejeCategoria, y: ejeValor };
}

/** Barras. horizontal:true para ranking (la etiqueta se lee de corrido). */
export function crearBarras(canvas, config) {
  const {
    etiquetas,
    series,
    horizontal = false,
    apilado = false,
    etiquetasDirectas = false,
    formatoValor,
    formatoTooltip,
  } = config;

  return new window.Chart(canvas, {
    type: "bar",
    data: {
      labels: etiquetas,
      datasets: series.map((serie, indice) => ({
        label: serie.etiqueta,
        data: serie.datos,
        backgroundColor: serie.color || colorDeSerie(indice),
        // Extremo del dato redondeado y anclado en la linea base: la esquina
        // redonda va solo del lado donde termina la barra.
        borderRadius: horizontal
          ? { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 }
          : { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
        borderSkipped: false,
        // Separacion de 2px hecha con el color del papel, no con un borde
        // oscuro alrededor de la marca.
        borderColor: TOKENS.papelTarjeta,
        borderWidth: apilado ? 2 : 0,
        // Marcas finas: una barra gruesa y saturada grita, y encima miente
        // sobre la precision del dato.
        maxBarThickness: horizontal ? 26 : 42,
        categoryPercentage: 0.78,
        barPercentage: 0.86,
      })),
    },
    options: {
      indexAxis: horizontal ? "y" : "x",
      layout: { padding: { right: horizontal && etiquetasDirectas ? 52 : 8, top: 4 } },
      scales: ejes({ horizontal, apilado, formatoValor }),
      interaction: {
        // El area sensible es la banda entera de la categoria y no el pixel
        // exacto de la barra.
        mode: "nearest",
        axis: horizontal ? "y" : "x",
        intersect: false,
      },
      plugins: {
        // Una sola serie no necesita leyenda: el titulo de la tarjeta ya la nombra.
        legend: { display: series.length > 1 },
        tooltip: formatoTooltip ? { callbacks: { label: formatoTooltip } } : {},
        etiquetasAlFinal: {
          activo: horizontal && etiquetasDirectas,
          formato: formatoValor,
        },
      },
    },
  });
}

/** Lineas para series de tiempo (issue #8). */
export function crearLineas(canvas, config) {
  const { etiquetas, series, formatoValor, formatoTooltip } = config;

  return new window.Chart(canvas, {
    type: "line",
    data: {
      labels: etiquetas,
      datasets: series.map((serie, indice) => {
        const color = serie.color || colorDeSerie(indice);
        return {
          label: serie.etiqueta,
          data: serie.datos,
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          tension: 0.18,
          pointRadius: 4,
          pointHoverRadius: 6,
          // Anillo de 2px del color del papel para que dos puntos superpuestos
          // se distingan sin dibujarles un borde oscuro.
          pointBorderColor: TOKENS.papelTarjeta,
          pointBorderWidth: 2,
          // Marcadores distintos por serie: la identidad no puede depender
          // solo del color.
          pointStyle: ["circle", "rect", "triangle"][indice % 3],
          segment: serie.segmento,
        };
      }),
    },
    options: {
      scales: ejes({ formatoValor }),
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: series.length > 1 },
        tooltip: formatoTooltip ? { callbacks: { label: formatoTooltip } } : {},
      },
    },
  });
}

/** Destruye una instancia antes de volver a dibujar.
 *  Sin esto Chart.js acumula instancias sobre el mismo canvas y los tooltips
 *  empiezan a aparecer duplicados. */
export function destruir(grafico) {
  if (grafico) grafico.destroy();
  return null;
}
