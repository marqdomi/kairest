/**
 * Admin Dashboard — Sprint 10 (period selector + trends)
 * Fetches 9 API endpoints with period filter, renders 8 KPI widgets,
 * 2 charts, stock alerts, activity feed. Auto-refreshes every 30s.
 */
(function() {
  'use strict';

  const COLORS = {
    // v7 Design System palette
    red:     '#C41E3A',
    red2:    '#E5535A',
    gold:    '#C29E59',
    gold2:   '#D4B97A',
    green:   '#12B76A',
    yellow:  '#F79009',
    blue:    '#2E90FA',
    purple:  '#9B8AFB',
    // Chart backgrounds (translucent glow)
    redGlow:    'rgba(196,30,58,0.15)',
    goldGlow:   'rgba(194,158,89,0.10)',
    greenGlow:  'rgba(18,183,106,0.12)',
    // Chart grid/axis
    gridColor:  'rgba(255,255,255,0.05)',
    tickColor:  'rgba(255,255,255,0.35)',
    // Tooltip
    tooltipBg:  'rgba(13,14,20,0.95)',
  };
  const REFRESH_MS = 30000;
  let chart7Dias = null;
  let chartTop = null;
  let currentPeriod = 'today';

  // Currency formatter (Next-Gen)
  const currency = v => {
    const num = Number(v);
    const str = num.toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const parts = str.split('.');
    return `<span class="cl-money"><span class="cl-money-symbol">$</span>${parts[0]}<span class="cl-money-decimal">.${parts[1]}</span></span>`;
  };

  function createGradient(ctx, colorHex) {
    const canvas = ctx.canvas || ctx;
    const context = canvas.getContext('2d');
    const gradient = context.createLinearGradient(0, 0, 0, canvas.height || 220);
    gradient.addColorStop(0, colorHex + '80'); // 50% opacity
    gradient.addColorStop(1, colorHex + '00'); // 0% opacity
    return gradient;
  }

  // Fetch helper — appends period query param
  const api = endpoint => fetch(`/admin/api/dashboard/${endpoint}?period=${currentPeriod}`).then(r => r.json());

  // Estado badge helper
  function estadoBadge(estado) {
    const map = {
      pendiente: 'cl-badge cl-badge--warning',
      en_preparacion: 'cl-badge cl-badge--info',
      completada: 'cl-badge cl-badge--success',
      pagado: 'cl-badge cl-badge--primary',
      cancelada: 'cl-badge cl-badge--danger',
    };
    return `<span class="${map[estado] || 'cl-badge cl-badge--gray'}">${estado}</span>`;
  }

  // Period label for dynamic titles
  function periodLabel() {
    const labels = { today: 'Hoy', yesterday: 'Ayer', week: 'Últimos 7 días', month: 'Últimos 30 días' };
    return labels[currentPeriod] || 'Hoy';
  }

  // ---- KPI Updates ----
  async function refreshKPIs() {
    try {
      const [ventas, ordenes, ticket, propinas, mesas, cocina, stock, corte] = await Promise.all([
        api('ventas_hoy'),
        api('ordenes_hoy'),
        api('ticket_promedio'),
        api('propinas_hoy'),
        api('mesas_activas'),
        api('ordenes_cocina'),
        api('alertas_stock'),
        api('ultimo_corte'),
      ]);

      document.getElementById('kpi-ventasHoy').innerHTML = currency(ventas.ventasHoy);
      document.getElementById('kpi-ordenesHoy').textContent = ordenes.ordenesHoy;
      document.getElementById('kpi-ticketPromedio').innerHTML = currency(ticket.ticketPromedio);
      document.getElementById('kpi-propinasHoy').innerHTML = currency(propinas.propinas);

      // Mesas
      document.getElementById('kpi-mesasActivas').textContent = `${mesas.ocupadas}/${mesas.total}`;
      const mesRes = document.getElementById('mesasReservadas');
      if (mesRes) mesRes.textContent = mesas.reservadas > 0 ? `${mesas.reservadas} reservada(s)` : '';

      // Cocina
      document.getElementById('kpi-ordenesCocina').textContent = cocina.pendientes;
      const timerEl = document.getElementById('timerCocina');
      if (timerEl) timerEl.textContent = cocina.timer_promedio_min > 0
        ? `~${cocina.timer_promedio_min} min promedio`
        : 'Sin órdenes activas';

      // Stock alerts count
      const countEl = document.getElementById('kpi-alertasStockCount');
      if (!countEl) return;
      countEl.textContent = stock.count;
      countEl.classList.toggle('text-danger', stock.count > 0);

      // Stock alerts list
      const stockList = document.getElementById('stockAlertsList');
      const stockBadge = document.getElementById('alertasStockBadge');
      if (stockBadge) {
        stockBadge.textContent = stock.count;
        stockBadge.style.display = stock.count > 0 ? 'inline-flex' : 'none';
      }
      if (stock.count === 0) {
        stockList.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:10px;opacity:.5;">
            <i data-lucide="package-check" style="width:32px;height:32px;color:var(--cl-success-500);"></i>
            <p style="font-size:13px;color:var(--cl-text-tertiary);margin:0;">Sin alertas de inventario</p>
          </div>`;
        if (window.lucide) lucide.createIcons();
      } else {
        stockList.innerHTML = `<div class="cl-alert-list">` + stock.items.map(item => {
          const pct = item.minimo > 0 ? Math.min((item.stock / item.minimo) * 100, 100) : 0;
          const dotColor = pct < 30 ? 'var(--cl-error-500)' : pct < 70 ? 'var(--cl-warning-500)' : 'var(--cl-success-500)';
          const barColor = dotColor;
          return `
            <div class="cl-alert-item">
              <div class="cl-alert-dot" style="background:${dotColor};"></div>
              <div class="cl-alert-name">${item.nombre}</div>
              <div class="cl-bar-wrap" style="width:80px;">
                <div class="cl-bar-fill" style="width:${pct}%;background:${barColor};"></div>
              </div>
              <span class="cl-alert-qty">${item.stock}/${item.minimo} ${item.unidad}</span>
            </div>`;
        }).join('') + '</div>';
      }

      // Último corte KPI card
      const corteEl = document.getElementById('kpi-ultimoCorte');
      if (!corteEl) return;
      if (!corte.exists) {
        corteEl.innerHTML = '—';
        const subEl = corteEl.closest('.cl-kpi-card').querySelector('.cl-kpi-card__sub');
        if (subEl) subEl.textContent = 'Sin cortes registrados';
      } else {
        corteEl.innerHTML = currency(corte.total_ingresos);
        const sub = corteEl.closest('.cl-kpi-card').querySelector('.cl-kpi-card__sub');
        if (sub) sub.textContent = `${corte.fecha} · ${corte.usuario}`;
        // Add trend
        const hdr = corteEl.closest('.cl-kpi-card').querySelector('.cl-kpi-card__header');
        const trend = hdr ? hdr.querySelector('.cl-kpi-trend') : null;
        if (trend) {
          const isPos = corte.diferencia >= 0;
          trend.className = `cl-kpi-trend cl-kpi-trend--${isPos ? 'up' : 'down'}`;
          trend.innerHTML = `<i data-lucide="trending-${isPos ? 'up' : 'down'}" class="icon-xs"></i> ${isPos ? '+' : ''}${currency(corte.diferencia)}`;
          if (window.lucide) lucide.createIcons();
        }
      }

    } catch (err) {
      console.error('Error refreshing KPIs:', err);
    }
  }

  // ---- Charts ----
  async function refreshCharts() {
    try {
      const [ventas7, top] = await Promise.all([
        api('ventas_7dias'),
        api('top_productos'),
      ]);

      // 7-day sales line chart
      const ctx7 = document.getElementById('chart7Dias');
      if (chart7Dias) {
        chart7Dias.data.labels = ventas7.labels;
        chart7Dias.data.datasets[0].data = ventas7.data;
        chart7Dias.update();
      } else {
        chart7Dias = new Chart(ctx7, {
          type: 'line',
          data: {
            labels: ventas7.labels,
            datasets: [{
              label: 'Ventas ($)',
              data: ventas7.data,
              borderColor: COLORS.red,
              backgroundColor: createGradient(ctx7, COLORS.red),
              fill: true,
              tension: 0.4,
              pointRadius: 4,
              pointHoverRadius: 6,
              pointBackgroundColor: COLORS.red,
              pointBorderColor: '#0A0B10',
              pointBorderWidth: 2,
              borderWidth: 2.5,
            }]
          },
          options: {
            responsive: true,
            animation: { duration: 600, easing: 'easeInOutQuart' },
            plugins: {
              legend: { display: false },
              tooltip: { 
                backgroundColor: COLORS.tooltipBg,
                titleColor: '#F2F4F7',
                bodyColor: '#98A2B3',
                borderColor: 'rgba(255,255,255,0.08)',
                borderWidth: 1,
                padding: 12,
                cornerRadius: 10,
                callbacks: { label: ctx => ' $' + ctx.parsed.y.toLocaleString('es-MX', { minimumFractionDigits: 2 }) } 
              },
            },
            scales: {
              x: {
                grid: { color: COLORS.gridColor },
                ticks: { color: COLORS.tickColor, font: { size: 11 } }
              },
              y: { 
                beginAtZero: true, 
                grid: { color: COLORS.gridColor, borderDash: [3, 3] },
                ticks: { color: COLORS.tickColor, font: { size: 11 }, callback: v => '$' + v.toLocaleString('es-MX') } 
              }
            }
          }
        });
      }

      // Top products bar chart
      const ctxTop = document.getElementById('chartTopProductos');
      const topLabel = `Top 5 — ${periodLabel()}`;
      if (chartTop) {
        chartTop.data.labels = top.labels;
        chartTop.data.datasets[0].data = top.data;
        chartTop.update();
      } else {
        chartTop = new Chart(ctxTop, {
          type: 'bar',
          data: {
            labels: top.labels,
            datasets: [{
              label: 'Unidades',
              data: top.data,
              backgroundColor: [
                COLORS.red + 'CC',
                COLORS.gold + 'CC',
                COLORS.green + 'CC',
                COLORS.blue + 'CC',
                COLORS.purple + 'CC',
              ],
              borderRadius: 6,
              borderSkipped: false,
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            animation: { duration: 600 },
            plugins: {
              legend: { display: false },
              tooltip: {
                backgroundColor: COLORS.tooltipBg,
                titleColor: '#F2F4F7',
                bodyColor: '#98A2B3',
                borderColor: 'rgba(255,255,255,0.08)',
                borderWidth: 1,
                padding: 10, cornerRadius: 8,
              }
            },
            scales: {
              x: {
                beginAtZero: true,
                grid: { color: COLORS.gridColor },
                ticks: { color: COLORS.tickColor, font: { size: 11 }, stepSize: 1 }
              },
              y: {
                grid: { display: false },
                ticks: { color: COLORS.tickColor, font: { size: 11 } }
              }
            }
          }
        });
      }
    } catch (err) {
      console.error('Error refreshing charts:', err);
    }
  }

  // ---- Activity Feed (v7 markup) ----
  async function refreshActivity() {
    try {
      const data = await api('actividad_reciente');
      const feed = document.getElementById('activityFeed');
      if (!data.items.length) {
        feed.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;padding:24px;gap:8px;opacity:.4;">
            <i data-lucide="inbox" style="width:28px;height:28px;"></i>
            <p style="font-size:13px;color:var(--cl-text-tertiary);margin:0;">Sin actividad reciente</p>
          </div>`;
        if (window.lucide) lucide.createIcons();
        return;
      }
      feed.innerHTML = data.items.map(item => {
        const initials = (item.mesero || '').split(' ').map(w => w[0]||'').slice(0,2).join('').toUpperCase() || '?';
        const colors = ['#C41E3A','#C29E59','#12B76A','#2E90FA','#9B8AFB'];
        const avatarColor = colors[item.id % colors.length];
        const hasTotal = item.total > 0;
        return `
        <div class="cl-feed__item">
          <div class="cl-feed__avatar" style="background:${avatarColor};">${initials}</div>
          <div style="flex:1;min-width:0;">
            <div class="cl-feed__text">
              <strong>Orden #${item.id}</strong> · ${item.mesa ? 'Mesa ' + item.mesa : 'Para llevar'} · ${item.mesero}
            </div>
            <div class="cl-feed__time">${item.hora} &nbsp; ${estadoBadge(item.estado)}</div>
          </div>
          ${hasTotal ? `<div class="cl-feed__amount">${currency(item.total)}</div>` : ''}
        </div>`;
      }).join('');
      if (window.lucide) lucide.createIcons();
    } catch (err) {
      console.error('Error refreshing activity:', err);
    }
  }

  // ---- Period Selector ----
  function initPeriodSelector() {
    const container = document.getElementById('periodSelector');
    if (!container) return;
    container.addEventListener('click', (e) => {
      const pill = e.target.closest('.cl-period-pill');
      if (!pill) return;
      container.querySelectorAll('.cl-period-pill').forEach(p => {
        p.classList.remove('active');
        p.setAttribute('aria-pressed', 'false');
      });
      pill.classList.add('active');
      pill.setAttribute('aria-pressed', 'true');
      currentPeriod = pill.dataset.period;
      // Update chart title
      const titleEl = document.getElementById('chartTitle');
      const labels = { today: 'Hoy', yesterday: 'Ayer', week: 'Últimos 7 días', month: 'Últimos 30 días' };
      if (titleEl) titleEl.textContent = `Ventas — ${labels[currentPeriod] || 'Hoy'}`;
      refreshAll();
    });
    // Manual refresh button
    const btn = document.getElementById('dashRefreshBtn');
    if (btn) btn.addEventListener('click', refreshAll);
  }

  // ---- Auto-refresh ----
  function refreshAll() {
    refreshKPIs();
    refreshCharts();
    refreshActivity();
  }

  document.addEventListener('DOMContentLoaded', () => {
    initPeriodSelector();
    refreshAll();
    setInterval(refreshAll, REFRESH_MS);
  });

})();