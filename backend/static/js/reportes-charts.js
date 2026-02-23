/**
 * Reportes Charts — Sprint 4 (6.1)
 * Gráficas interactivas con Chart.js 4.x
 * Cada reporte invoca initXxxChart() tras cargar la página.
 */
(function () {
  'use strict';

  /* ─── Theme palette ────────────────────────────── */
  const COLORS = {
    primary:   '#A6192E',
    secondary: '#0A3D62',
    accent:    '#507C36',
    light:     '#FAF3E0',
    dark:      '#1E1E1E',
  };

  const PALETTE = [
    '#A6192E', '#0A3D62', '#507C36', '#E8A838', '#6C3483',
    '#1ABC9C', '#E74C3C', '#3498DB', '#F39C12', '#2ECC71',
    '#9B59B6', '#E67E22', '#1F618D', '#D35400', '#27AE60',
    '#8E44AD', '#2980B9', '#C0392B', '#16A085', '#F1C40F',
  ];

  /* ─── Chart.js global defaults ─────────────────── */
  Chart.defaults.font.family = "'Segoe UI', Roboto, 'Helvetica Neue', sans-serif";
  Chart.defaults.responsive = true;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.padding = 12;
  Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(16, 24, 40, 0.9)';
  Chart.defaults.plugins.tooltip.titleFont = { size: 14, weight: 'bold' };
  Chart.defaults.plugins.tooltip.bodyFont = { size: 13 };
  Chart.defaults.plugins.tooltip.boxPadding = 6;
  Chart.defaults.scale.grid.color = 'rgba(0, 0, 0, 0.05)';
  Chart.defaults.scale.grid.drawBorder = false;

  /* ─── Helpers ──────────────────────────────────── */
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function currency(v) {
    return '$' + Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function createGradient(ctx, colorHex) {
    const canvas = ctx.canvas || ctx;
    const context = canvas.getContext('2d');
    const gradient = context.createLinearGradient(0, 0, 0, canvas.height || 400);
    gradient.addColorStop(0, colorHex + '80'); // 50% opacity
    gradient.addColorStop(1, colorHex + '00'); // 0% opacity
    return gradient;
  }

  /** Fetch JSON from API endpoint with current date range. */
  async function fetchData(endpoint) {
    const params = new URLSearchParams(window.location.search);
    const fi = params.get('fecha_inicio') || '';
    const ff = params.get('fecha_fin') || '';
    const url = `/admin/reportes/api/${endpoint}?fecha_inicio=${fi}&fecha_fin=${ff}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Error ${res.status}`);
    return res.json();
  }

  /** Export chart canvas to PNG download. */
  function exportPNG(chart, filename) {
    const link = document.createElement('a');
    link.download = filename || 'chart.png';
    link.href = chart.toBase64Image();
    link.click();
  }

  /** Toggle table/chart visibility. */
  function setupToggle(btnId, tableId, chartContainerId) {
    const btn = document.getElementById(btnId);
    const table = document.getElementById(tableId);
    const chartC = document.getElementById(chartContainerId);
    if (!btn || !table || !chartC) return;

    let showingChart = true;
    btn.addEventListener('click', function () {
      showingChart = !showingChart;
      table.style.display = showingChart ? 'none' : '';
      chartC.style.display = showingChart ? '' : 'none';
      btn.innerHTML = showingChart
        ? '<i class="fas fa-table me-1"></i>Ver Tabla'
        : '<i class="fas fa-chart-bar me-1"></i>Ver Gráfica';
    });
    // Start with chart visible
    table.style.display = 'none';
    chartC.style.display = '';
  }

  /* ─── VENTAS ──────────────────────────────────── */
  window.initVentasCharts = async function () {
    try {
      const data = await fetchData('ventas');

      // Line chart — ventas por día
      const ctxDia = document.getElementById('chartVentasDia');
      if (ctxDia) {
        const chartDia = new Chart(ctxDia, {
          type: 'line',
          data: {
            labels: data.por_dia.labels,
            datasets: [{
              label: 'Ventas ($)',
              data: data.por_dia.totales,
              borderColor: COLORS.primary,
              backgroundColor: createGradient(ctxDia, COLORS.primary),
              fill: true,
              tension: 0.4,
              pointRadius: 4,
              pointHoverRadius: 6,
              borderWidth: 3,
            }],
          },
          options: {
            plugins: {
              tooltip: {
                callbacks: { label: ctx => currency(ctx.parsed.y) },
              },
            },
            scales: {
              x: { grid: { display: false } },
              y: { 
                grid: { borderDash: [4, 4] },
                ticks: { callback: v => currency(v) } 
              },
            },
          },
        });

        const btnExportDia = document.getElementById('btnExportVentasDia');
        if (btnExportDia) btnExportDia.addEventListener('click', () => exportPNG(chartDia, 'ventas_dia.png'));
      }

      // Bar chart — ventas por hora
      const ctxHora = document.getElementById('chartVentasHora');
      if (ctxHora) {
        const chartHora = new Chart(ctxHora, {
          type: 'bar',
          data: {
            labels: data.por_hora.labels,
            datasets: [{
              label: 'Ventas ($)',
              data: data.por_hora.totales,
              backgroundColor: COLORS.secondary + 'CC',
              borderColor: COLORS.secondary,
              borderWidth: 1,
              borderRadius: 4,
            }],
          },
          options: {
            plugins: {
              tooltip: {
                callbacks: { label: ctx => currency(ctx.parsed.y) + ` (${data.por_hora.cantidades[ctx.dataIndex]} órdenes)` },
              },
            },
            scales: {
              y: { ticks: { callback: v => currency(v) } },
            },
          },
        });

        const btnExportHora = document.getElementById('btnExportVentasHora');
        if (btnExportHora) btnExportHora.addEventListener('click', () => exportPNG(chartHora, 'ventas_hora.png'));
      }

      setupToggle('btnToggleVentas', 'tablaVentasDia', 'chartsVentas');
    } catch (err) {
      console.error('Error cargando gráficas de ventas:', err);
    }
  };

  /* ─── PRODUCTOS ───────────────────────────────── */
  window.initProductosCharts = async function () {
    try {
      const data = await fetchData('productos');

      // Horizontal bar — top productos
      const ctxTop = document.getElementById('chartTopProductos');
      if (ctxTop) {
        const chartTop = new Chart(ctxTop, {
          type: 'bar',
          data: {
            labels: data.top_productos.labels,
            datasets: [{
              label: 'Cantidad vendida',
              data: data.top_productos.cantidades,
              backgroundColor: PALETTE.slice(0, data.top_productos.labels.length),
              borderRadius: 4,
            }],
          },
          options: {
            indexAxis: 'y',
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  afterLabel: ctx => 'Ingreso: ' + currency(data.top_productos.ingresos[ctx.dataIndex]),
                },
              },
            },
            scales: {
              x: { beginAtZero: true },
            },
          },
        });

        const btnExportTop = document.getElementById('btnExportTopProductos');
        if (btnExportTop) btnExportTop.addEventListener('click', () => exportPNG(chartTop, 'top_productos.png'));
      }

      // Pie — categorías
      const ctxCat = document.getElementById('chartCategorias');
      if (ctxCat) {
        const chartCat = new Chart(ctxCat, {
          type: 'doughnut',
          data: {
            labels: data.categorias.labels,
            datasets: [{
              data: data.categorias.ingresos,
              backgroundColor: PALETTE.slice(0, data.categorias.labels.length),
              borderWidth: 2,
              borderColor: '#fff',
            }],
          },
          options: {
            plugins: {
              tooltip: {
                callbacks: { label: ctx => ctx.label + ': ' + currency(ctx.parsed) },
              },
            },
          },
        });

        const btnExportCat = document.getElementById('btnExportCategorias');
        if (btnExportCat) btnExportCat.addEventListener('click', () => exportPNG(chartCat, 'categorias.png'));
      }

      setupToggle('btnToggleProductos', 'tablaProductos', 'chartsProductos');
    } catch (err) {
      console.error('Error cargando gráficas de productos:', err);
    }
  };

  /* ─── MESEROS ─────────────────────────────────── */
  window.initMeserosCharts = async function () {
    try {
      const data = await fetchData('meseros');

      const ctx = document.getElementById('chartMeseros');
      if (ctx) {
        const chart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: data.labels,
            datasets: [
              {
                label: 'Total Ventas ($)',
                data: data.totales,
                backgroundColor: COLORS.primary + 'CC',
                borderColor: COLORS.primary,
                borderWidth: 1,
                borderRadius: 4,
                yAxisID: 'y',
              },
              {
                label: '# Ventas',
                data: data.num_ventas,
                backgroundColor: COLORS.secondary + 'CC',
                borderColor: COLORS.secondary,
                borderWidth: 1,
                borderRadius: 4,
                yAxisID: 'y1',
              },
            ],
          },
          options: {
            plugins: {
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    if (ctx.datasetIndex === 0) return currency(ctx.parsed.y);
                    return ctx.parsed.y + ' ventas';
                  },
                },
              },
            },
            scales: {
              y: {
                type: 'linear',
                position: 'left',
                ticks: { callback: v => currency(v) },
              },
              y1: {
                type: 'linear',
                position: 'right',
                grid: { drawOnChartArea: false },
                ticks: { precision: 0 },
              },
            },
          },
        });

        const btnExport = document.getElementById('btnExportMeseros');
        if (btnExport) btnExport.addEventListener('click', () => exportPNG(chart, 'meseros.png'));
      }

      setupToggle('btnToggleMeseros', 'tablaMeseros', 'chartsMeseros');
    } catch (err) {
      console.error('Error cargando gráficas de meseros:', err);
    }
  };

  /* ─── PAGOS ───────────────────────────────────── */
  window.initPagosCharts = async function () {
    try {
      const data = await fetchData('pagos');

      const ctx = document.getElementById('chartPagos');
      if (ctx) {
        const chart = new Chart(ctx, {
          type: 'doughnut',
          data: {
            labels: data.labels,
            datasets: [{
              data: data.totales,
              backgroundColor: [COLORS.accent, COLORS.primary, COLORS.secondary, '#E8A838', '#6C3483'],
              borderWidth: 2,
              borderColor: '#fff',
            }],
          },
          options: {
            cutout: '55%',
            plugins: {
              tooltip: {
                callbacks: {
                  label: ctx => ctx.label + ': ' + currency(ctx.parsed) + ` (${data.cantidades[ctx.dataIndex]} txn)`,
                },
              },
            },
          },
        });

        const btnExport = document.getElementById('btnExportPagos');
        if (btnExport) btnExport.addEventListener('click', () => exportPNG(chart, 'pagos.png'));
      }

      setupToggle('btnTogglePagos', 'tablaPagos', 'chartsPagos');
    } catch (err) {
      console.error('Error cargando gráficas de pagos:', err);
    }
  };

  /* ─── INVENTARIO / MERMAS ─────────────────────── */
  window.initInventarioCharts = async function () {
    try {
      const data = await fetchData('inventario');

      const ctx = document.getElementById('chartMermas');
      if (ctx) {
        const chart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: data.labels,
            datasets: [{
              label: 'Total Merma',
              data: data.totales,
              backgroundColor: COLORS.primary + 'CC',
              borderColor: COLORS.primary,
              borderWidth: 1,
              borderRadius: 4,
            }],
          },
          options: {
            indexAxis: 'y',
            plugins: {
              legend: { display: false },
            },
            scales: {
              x: { beginAtZero: true },
            },
          },
        });

        const btnExport = document.getElementById('btnExportMermas');
        if (btnExport) btnExport.addEventListener('click', () => exportPNG(chart, 'mermas.png'));
      }

      setupToggle('btnToggleInventario', 'tablaInventario', 'chartsInventario');
    } catch (err) {
      console.error('Error cargando gráficas de inventario:', err);
    }
  };

})();
