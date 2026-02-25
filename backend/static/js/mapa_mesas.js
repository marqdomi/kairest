/**
 * Mapa Visual de Mesas — v7 Redesign
 * Auto-grid layout, snap-to-grid drag-and-drop, intuitive UX.
 */
(function () {
  'use strict';

  const mapContainer = document.getElementById('mapa-mesas');
  if (!mapContainer) return;

  const isAdmin = mapContainer.dataset.admin === 'true';
  const mesasApiUrl = '/admin/reservaciones/api/mesas';
  const ordenBaseUrl = '/meseros/ordenes/';
  const crearOrdenUrl = '/meseros/seleccionar_mesa';

  // Grid configuration
  const CELL = 120;        // grid cell size px
  const GAP = 16;          // gap between cells
  const MESA_W = 100;
  const MESA_H = 80;
  const PAD = 20;          // container padding

  let mesas = [];
  let dragTarget = null;
  let dragOffset = { x: 0, y: 0 };
  let isDragging = false;

  // ─── Load mesas ─────────────────────────────────────────────
  function fetchMesas() {
    fetch(mesasApiUrl)
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(data => {
        mesas = data;
        autoLayoutIfNeeded();
        renderMap();
        renderListView();
        if (window.lucide) lucide.createIcons();
      })
      .catch(err => {
        console.error('Error cargando mesas:', err);
        mapContainer.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:300px;gap:12px;opacity:.6;">
            <i data-lucide="wifi-off" style="width:40px;height:40px;"></i>
            <p style="margin:0;">Error al cargar mesas. Reintentando...</p>
          </div>`;
        if (window.lucide) lucide.createIcons();
      });
  }

  // ─── Auto-layout: assign grid positions to mesas without pos ─
  function autoLayoutIfNeeded() {
    const needsLayout = mesas.some(m => m.pos_x == null || m.pos_y == null);
    if (!needsLayout) return;

    // Calculate grid columns based on container width
    const containerW = mapContainer.clientWidth || 800;
    const cols = Math.max(2, Math.floor((containerW - PAD) / (CELL + GAP)));

    mesas.forEach((m, i) => {
      if (m.pos_x == null || m.pos_y == null) {
        const col = i % cols;
        const row = Math.floor(i / cols);
        m.pos_x = PAD + col * (CELL + GAP);
        m.pos_y = PAD + row * (CELL + GAP);
      }
    });

    // If admin, auto-save the layout
    if (isAdmin) {
      mesas.forEach(m => {
        if (m._autoSaved) return;
        saveMesaPositionSilent(m.id, m.pos_x, m.pos_y);
        m._autoSaved = true;
      });
    }
  }

  // ─── Snap to grid ──────────────────────────────────────────
  function snapToGrid(val) {
    const step = CELL + GAP;
    return Math.round((val - PAD) / step) * step + PAD;
  }

  // ─── Calculate container height ────────────────────────────
  function calcContainerHeight() {
    let maxY = 300;
    mesas.forEach(m => {
      const y = (m.pos_y || 0) + MESA_H + PAD;
      if (y > maxY) maxY = y;
    });
    mapContainer.style.minHeight = Math.max(400, maxY + 40) + 'px';
  }

  // ─── Render map ─────────────────────────────────────────────
  function renderMap() {
    mapContainer.innerHTML = '';
    calcContainerHeight();

    if (mesas.length === 0) {
      mapContainer.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:300px;gap:12px;opacity:.5;">
          <i data-lucide="layout-grid" style="width:48px;height:48px;"></i>
          <p style="font-size:15px;margin:0;">No hay mesas configuradas</p>
          <p style="font-size:12px;margin:0;">Ve a Admin → Mesas para crearlas.</p>
        </div>`;
      return;
    }

    mesas.forEach(m => {
      const el = document.createElement('div');
      el.className = `mesa-item estado-${m.estado}`;
      el.dataset.mesaId = m.id;
      el.style.left = (m.pos_x || PAD) + 'px';
      el.style.top = (m.pos_y || PAD) + 'px';
      el.setAttribute('tabindex', '0');
      el.setAttribute('role', 'button');
      el.setAttribute('aria-label',
        `Mesa ${m.numero}, ${m.capacidad} personas, ${m.estado}${m.zona ? ', zona ' + m.zona : ''}`);

      // Status icon
      const statusIcon = {
        disponible: 'circle-check',
        ocupada: 'utensils-crossed',
        reservada: 'calendar-clock',
        mantenimiento: 'wrench',
      }[m.estado] || 'circle';

      el.innerHTML = `
        <div class="mesa-status-icon"><i data-lucide="${statusIcon}" style="width:16px;height:16px;"></i></div>
        <span class="mesa-numero">${m.numero}</span>
        <span class="mesa-capacidad"><i data-lucide="users" style="width:10px;height:10px;"></i> ${m.capacidad}</span>
        ${m.zona ? `<span class="mesa-zona">${m.zona}</span>` : ''}
      `;

      // Click — but not if we were dragging
      el.addEventListener('click', (e) => {
        if (isDragging) { isDragging = false; return; }
        handleMesaClick(m);
      });
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleMesaClick(m);
        }
      });

      // Admin drag-and-drop
      if (isAdmin) {
        el.style.cursor = 'grab';
        el.addEventListener('mousedown', startDrag);
        el.addEventListener('touchstart', startDragTouch, { passive: false });
      }

      mapContainer.appendChild(el);
    });
  }

  // ─── List view for mobile ──────────────────────────────────
  function renderListView() {
    const listEl = document.getElementById('mapa-list-view');
    if (!listEl) return;

    listEl.innerHTML = '';
    mesas.forEach(m => {
      const row = document.createElement('a');
      row.href = '#';
      row.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center';
      row.innerHTML = `
        <div>
          <strong>Mesa ${m.numero}</strong>
          <small class="text-muted ms-2">${m.zona || ''}</small>
        </div>
        <div>
          <span class="badge bg-${estadoBadge(m.estado)} me-2">${capitalizeFirst(m.estado)}</span>
          <small>${m.capacidad} pers.</small>
        </div>
      `;
      row.addEventListener('click', (e) => {
        e.preventDefault();
        handleMesaClick(m);
      });
      listEl.appendChild(row);
    });
  }

  function estadoBadge(estado) {
    return { disponible: 'success', ocupada: 'danger', reservada: 'warning', mantenimiento: 'secondary' }[estado] || 'secondary';
  }

  function capitalizeFirst(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
  }

  // ─── Click handler ─────────────────────────────────────────
  function handleMesaClick(mesa) {
    if (mesa.estado === 'disponible') {
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = crearOrdenUrl;
      form.innerHTML = `<input type="hidden" name="csrf_token" value="${window.__csrfToken || ''}">
                         <input type="hidden" name="mesa_id" value="${mesa.id}">`;
      document.body.appendChild(form);
      form.submit();
    } else if (mesa.estado === 'ocupada') {
      fetch(`/api/ordenes/mesa/${mesa.id}`)
        .then(r => r.json())
        .then(data => {
          if (data.orden_id) {
            window.location.href = `${ordenBaseUrl}${data.orden_id}/detalle_orden`;
          } else {
            showMapToast(`Mesa ${mesa.numero} ocupada pero sin orden activa.`, 'warning');
          }
        })
        .catch(() => showMapToast('Error al buscar orden.', 'danger'));
    } else {
      showMapToast(`Mesa ${mesa.numero}: ${capitalizeFirst(mesa.estado)}`, 'info');
    }
  }

  // ─── Drag & Drop (admin) ───────────────────────────────────
  let dragStartX = 0, dragStartY = 0;

  function startDrag(e) {
    if (!isAdmin) return;
    e.preventDefault();
    dragTarget = e.currentTarget;
    dragTarget.classList.add('dragging');
    dragTarget.style.cursor = 'grabbing';
    const rect = dragTarget.getBoundingClientRect();
    dragOffset.x = e.clientX - rect.left;
    dragOffset.y = e.clientY - rect.top;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    isDragging = false;

    document.addEventListener('mousemove', onDrag);
    document.addEventListener('mouseup', endDrag);
  }

  function startDragTouch(e) {
    if (!isAdmin) return;
    e.preventDefault();
    const touch = e.touches[0];
    dragTarget = e.currentTarget;
    dragTarget.classList.add('dragging');
    const rect = dragTarget.getBoundingClientRect();
    dragOffset.x = touch.clientX - rect.left;
    dragOffset.y = touch.clientY - rect.top;
    dragStartX = touch.clientX;
    dragStartY = touch.clientY;
    isDragging = false;

    document.addEventListener('touchmove', onDragTouch, { passive: false });
    document.addEventListener('touchend', endDragTouch);
  }

  function onDrag(e) {
    if (!dragTarget) return;
    if (Math.abs(e.clientX - dragStartX) > 5 || Math.abs(e.clientY - dragStartY) > 5) {
      isDragging = true;
    }
    const containerRect = mapContainer.getBoundingClientRect();
    let x = e.clientX - containerRect.left - dragOffset.x;
    let y = e.clientY - containerRect.top - dragOffset.y;
    x = Math.max(0, Math.min(x, containerRect.width - MESA_W));
    y = Math.max(0, Math.min(y, containerRect.height - MESA_H));
    dragTarget.style.left = x + 'px';
    dragTarget.style.top = y + 'px';
  }

  function onDragTouch(e) {
    if (!dragTarget) return;
    e.preventDefault();
    const touch = e.touches[0];
    if (Math.abs(touch.clientX - dragStartX) > 5 || Math.abs(touch.clientY - dragStartY) > 5) {
      isDragging = true;
    }
    const containerRect = mapContainer.getBoundingClientRect();
    let x = touch.clientX - containerRect.left - dragOffset.x;
    let y = touch.clientY - containerRect.top - dragOffset.y;
    x = Math.max(0, Math.min(x, containerRect.width - MESA_W));
    y = Math.max(0, Math.min(y, containerRect.height - MESA_H));
    dragTarget.style.left = x + 'px';
    dragTarget.style.top = y + 'px';
  }

  function endDrag() {
    if (!dragTarget) return;
    finishDrag();
    document.removeEventListener('mousemove', onDrag);
    document.removeEventListener('mouseup', endDrag);
  }

  function endDragTouch() {
    if (!dragTarget) return;
    finishDrag();
    document.removeEventListener('touchmove', onDragTouch);
    document.removeEventListener('touchend', endDragTouch);
  }

  function finishDrag() {
    dragTarget.classList.remove('dragging');
    dragTarget.style.cursor = 'grab';

    if (isDragging) {
      // Snap to grid
      let x = parseInt(dragTarget.style.left) || 0;
      let y = parseInt(dragTarget.style.top) || 0;
      x = snapToGrid(x);
      y = snapToGrid(y);
      dragTarget.style.left = x + 'px';
      dragTarget.style.top = y + 'px';

      const mesaId = dragTarget.dataset.mesaId;
      saveMesaPosition(mesaId, x, y);

      // Update local data
      const mesa = mesas.find(m => String(m.id) === mesaId);
      if (mesa) { mesa.pos_x = x; mesa.pos_y = y; }
    }

    dragTarget = null;
  }

  function saveMesaPosition(mesaId, posX, posY) {
    const headers = { 'Content-Type': 'application/json' };
    if (window.__csrfToken) headers['X-CSRFToken'] = window.__csrfToken;
    fetch(`/admin/mesas/${mesaId}/posicion`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ pos_x: posX, pos_y: posY }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          showMapToast('Posición guardada', 'success');
        }
      })
      .catch(err => console.error('Error guardando posición:', err));
  }

  function saveMesaPositionSilent(mesaId, posX, posY) {
    const headers = { 'Content-Type': 'application/json' };
    if (window.__csrfToken) headers['X-CSRFToken'] = window.__csrfToken;
    fetch(`/admin/mesas/${mesaId}/posicion`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ pos_x: posX, pos_y: posY }),
    }).catch(() => { });
  }

  // ─── Auto-arrange button ──────────────────────────────────
  const autoBtn = document.getElementById('btnAutoArrange');
  if (autoBtn) {
    autoBtn.addEventListener('click', () => {
      const containerW = mapContainer.clientWidth || 800;
      const cols = Math.max(2, Math.floor((containerW - PAD) / (CELL + GAP)));

      mesas.forEach((m, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        m.pos_x = PAD + col * (CELL + GAP);
        m.pos_y = PAD + row * (CELL + GAP);
        saveMesaPositionSilent(m.id, m.pos_x, m.pos_y);
      });

      renderMap();
      if (window.lucide) lucide.createIcons();
      showMapToast('Mesas organizadas automáticamente', 'success');
    });
  }

  // ─── Toast helper ──────────────────────────────────────────
  function showMapToast(message, type) {
    if (window.showToast) { window.showToast(message, type); return; }
    const container = document.getElementById('toast-container');
    if (!container) {
      const t = document.createElement('div');
      t.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;padding:10px 20px;border-radius:8px;color:#fff;font-size:14px;font-weight:500;animation:fadeIn .3s;';
      const bg = { success: '#28a745', danger: '#dc3545', warning: '#ffc107', info: '#17a2b8' }[type] || '#17a2b8';
      t.style.backgroundColor = bg;
      if (type === 'warning') t.style.color = '#333';
      t.textContent = message;
      document.body.appendChild(t);
      setTimeout(() => t.remove(), 2500);
      return;
    }
    const bg = { success: 'bg-success', danger: 'bg-danger', warning: 'bg-warning text-dark', info: 'bg-info' }[type] || 'bg-info';
    const id = 'toast-' + Date.now();
    container.insertAdjacentHTML('beforeend', `
      <div id="${id}" class="toast align-items-center text-white ${bg} border-0" role="alert" data-bs-delay="2500">
        <div class="d-flex">
          <div class="toast-body">${message}</div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
      </div>`);
    new bootstrap.Toast(document.getElementById(id)).show();
    document.getElementById(id).addEventListener('hidden.bs.toast', function () { this.remove(); });
  }

  // ─── Zone filter ───────────────────────────────────────────
  document.querySelectorAll('[data-zone-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      const zone = btn.dataset.zoneFilter;
      document.querySelectorAll('[data-zone-filter]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      document.querySelectorAll('.mesa-item').forEach(el => {
        const mesaId = el.dataset.mesaId;
        const mesa = mesas.find(m => String(m.id) === mesaId);
        if (!zone || zone === 'todas') {
          el.style.display = '';
        } else {
          el.style.display = (mesa && mesa.zona === zone) ? '' : 'none';
        }
      });
    });
  });

  // ─── Socket.IO real-time ───────────────────────────────────
  if (typeof io !== 'undefined') {
    try {
      const socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
      socket.on('mesa_estado_actualizado', function (data) {
        const mesa = mesas.find(m => m.id === data.mesa_id);
        if (mesa) mesa.estado = data.estado;
        renderMap();
        renderListView();
        if (window.lucide) lucide.createIcons();
      });
    } catch (e) {
      console.warn('Socket.IO not available for mesa map');
    }
  }

  // ─── Init ──────────────────────────────────────────────────
  fetchMesas();
  setInterval(fetchMesas, 30000);

})();
