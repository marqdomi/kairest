$(document).ready(function() {
    console.log('meseros.js cargado.');

    // =============================================
    // Toast helper (Sprint 5 — improved)
    // =============================================
    function showToast(message, type = 'info') {
        const container = $('#toast-container');
        if (!container.length) {
            $('body').append('<div id="toast-container" class="position-fixed top-0 end-0 p-3" style="z-index:1200;" role="alert" aria-live="polite"></div>');
        }

        const ICONS = {
            success: '✅',
            danger:  '❌',
            warning: '⚠️',
            info:    'ℹ️',
            confetti:'🎉'
        };
        const BG = {
            success: 'bg-success',
            danger:  'bg-danger',
            warning: 'bg-warning text-dark',
            info:    'bg-primary',
            confetti:'bg-success toast-confetti'
        };

        const icon = ICONS[type] || ICONS.info;
        const bg   = BG[type]   || BG.info;

        const id = 'toast-' + Date.now();
        $('#toast-container').append(`
            <div id="${id}" class="toast align-items-center text-white ${bg} border-0" role="alert" aria-atomic="true" data-bs-delay="3000">
                <div class="d-flex">
                    <div class="toast-body"><span class="me-1">${icon}</span>${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
                </div>
            </div>`);
        new bootstrap.Toast(document.getElementById(id)).show();
        document.getElementById(id).addEventListener('hidden.bs.toast', function() { $(this).remove(); });
    }

    // =============================================
    // Sound notification
    // =============================================
    var notifAudio = null;
    try { notifAudio = new Audio('/static/audio/notif.wav'); notifAudio.volume = 0.5; } catch(e) {}

    var soundEnabled = localStorage.getItem('meseros_sound') !== 'off';
    function updateSoundIcon() {
        var icon = document.getElementById('soundIcon');
        var btn = document.getElementById('btnToggleSound');
        if (icon && btn) {
            icon.setAttribute('data-lucide', soundEnabled ? 'volume-2' : 'volume-x');
            btn.title = soundEnabled ? 'Sonido activado' : 'Sonido desactivado';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
    updateSoundIcon();
    $(document).on('click', '#btnToggleSound', function(e) {
        e.stopPropagation();
        soundEnabled = !soundEnabled;
        localStorage.setItem('meseros_sound', soundEnabled ? 'on' : 'off');
        updateSoundIcon();
    });

    function playNotif() {
        if (soundEnabled && notifAudio) notifAudio.play().catch(function(){});
    }

    // =============================================
    // Card flash + auto-scroll helpers
    // =============================================
    function flashCard(ordenId) {
        var card = document.getElementById('orden-card-' + ordenId);
        if (!card) return;
        card.classList.remove('cl-order-card--flash');
        void card.offsetWidth; // force reflow
        card.classList.add('cl-order-card--flash');
        card.addEventListener('animationend', function() {
            card.classList.remove('cl-order-card--flash');
        }, { once: true });
    }

    function glowCardReady(ordenId) {
        var card = document.getElementById('orden-card-' + ordenId);
        if (!card) return;
        card.classList.remove('cl-order-card--ready-glow');
        void card.offsetWidth;
        card.classList.add('cl-order-card--ready-glow');
        card.addEventListener('animationend', function() {
            card.classList.remove('cl-order-card--ready-glow');
        }, { once: true });
    }

    function scrollToCard(ordenId) {
        var card = document.getElementById('orden-card-' + ordenId);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // =============================================
    // Hide scroll-hint on scroll
    // =============================================
    document.querySelectorAll('.cl-card-items-list').forEach(function(list) {
        list.addEventListener('scroll', function() {
            var hint = list.querySelector('.cl-scroll-hint');
            if (hint) hint.style.display = 'none';
        }, { once: true });
    });

    // =============================================
    // Auto-refresh timer (30s fallback)
    // =============================================
    var AUTO_REFRESH_SECS = 30;
    var refreshCountdown = AUTO_REFRESH_SECS;
    var autoRefreshLabel = document.getElementById('autoRefreshLabel');

    setInterval(function() {
        // Pause auto-refresh when modal is open (cobro, descuento, etc.)
        if ($('.modal.show').length > 0) {
            refreshCountdown = AUTO_REFRESH_SECS;
            if (autoRefreshLabel) autoRefreshLabel.textContent = 'pausado';
            return;
        }
        refreshCountdown--;
        if (autoRefreshLabel) {
            autoRefreshLabel.textContent = refreshCountdown + 's';
        }
        if (refreshCountdown <= 0) {
            refreshCountdown = AUTO_REFRESH_SECS;
            window.location.reload();
        }
    }, 1000);

    // =============================================
    // Socket.IO
    // =============================================
    if (typeof io !== 'undefined') {
        const socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);

        // Connection indicator
        var liveDot = document.getElementById('liveDot');
        var liveLabel = document.getElementById('liveLabel');

        socket.on('connect', function() {
            console.log('Meseros Socket.IO conectado');
            if (liveDot) liveDot.classList.remove('cl-live-dot--off');
            if (liveLabel) liveLabel.textContent = 'En vivo';
        });
        socket.on('disconnect', function() {
            console.warn('Meseros Socket.IO desconectado');
            if (liveDot) liveDot.classList.add('cl-live-dot--off');
            if (liveLabel) liveLabel.textContent = 'Desconectado';
        });

        socket.on('nueva_orden_cocina', function(data) {
            showToast(`Orden #${data.orden_id} enviada a cocina.`, 'info');
            // Reset auto-refresh countdown on activity
            refreshCountdown = AUTO_REFRESH_SECS;
        });

        socket.on('item_listo_notificacion', function(data) {
            playNotif();
            showToast(`¡${data.producto_nombre} de orden #${data.orden_id} listo!`, 'success');
            refreshCountdown = AUTO_REFRESH_SECS;
            var row = $('#product-item-' + data.item_id);
            if (row.length) {
                // Update badge in card layout
                row.find('.estado-producto-texto').html('<span class="cl-badge cl-badge--green" style="font-size:9px;padding:1px 6px;">Listo</span>');
                // Update status dot to green
                row.find('span[style*="border-radius:50%"]').first().css('background', 'var(--cl-success-500)');
                // Inject Entregar button
                row.find('.accion-producto').html(
                    `<button type="button" class="btn-entregar-item" data-detalle-id="${data.item_id}" data-orden-id="${data.orden_id}"
                      style="font-size:10px;padding:2px 8px;border-radius:6px;border:none;background:var(--cl-primary-500);color:#fff;cursor:pointer;font-weight:600;">
                      Entregar</button>`
                );
                row.removeClass('detalle-pendiente-cocina detalle-entregado').addClass('detalle-listo-cocina');
                updateCardProgress(data.orden_id);
                updateFilterCounters();
                verificarEstadoParaCobro(data.orden_id);
                flashCard(data.orden_id);
                scrollToCard(data.orden_id);
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        });

        socket.on('orden_en_preparacion', function(data) {
            var card = $('#orden-card-' + data.orden_id);
            if (card.length) {
                card.find('.cl-status').html('<i data-lucide="chef-hat" style="width:10px;height:10px;"></i> En cocina')
                    .attr('class', 'cl-status cl-status--kitchen').css({'font-size':'10px','padding':'2px 8px'});
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        });

        socket.on('item_progreso', function(data) {
            var card = $('#orden-card-' + data.orden_id);
            if (card.length) {
                // Light feedback — update status dot for in-progress items
                data.items_estados && data.items_estados.forEach(function(it) {
                    var row = $('#product-item-' + it.detalle_id);
                    if (row.length && it.estado === 'en_preparacion') {
                        row.find('span[style*="border-radius:50%"]').first().css('background', 'var(--cl-warning-500)');
                    }
                });
            }
        });

        socket.on('orden_completa_lista', function(data) {
            playNotif();
            showToast(`¡Orden #${data.orden_id} lista en cocina! Entrega los productos.`, 'success');
            refreshCountdown = AUTO_REFRESH_SECS;
            // Card glow + scroll to draw attention
            glowCardReady(data.orden_id);
            scrollToCard(data.orden_id);
            updateCardProgress(data.orden_id);
            updateFilterCounters();
            // Update card status badge
            var card = $('#orden-card-' + data.orden_id);
            if (card.length) {
                card.find('.cl-status').html('<i data-lucide="check-circle" style="width:10px;height:10px;"></i> Lista')
                    .attr('class', 'cl-status cl-status--ready').css({'font-size':'10px','padding':'2px 8px'});
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        });

        socket.on('orden_actualizada_para_cobro', function(data) {
            refreshCountdown = AUTO_REFRESH_SECS;
            if (data.estado_orden === 'completada') {
                playNotif();
                showToast(`Orden #${data.orden_id} lista para cobro.`, 'confetti');
                verificarEstadoParaCobro(data.orden_id);
                glowCardReady(data.orden_id);
                scrollToCard(data.orden_id);
                // Update card status badge
                var card = $('#orden-card-' + data.orden_id);
                if (card.length) {
                    card.find('.cl-status').html('<i data-lucide="check-circle" style="width:10px;height:10px;"></i> Completada')
                        .attr('class', 'cl-status cl-status--done').css({'font-size':'10px','padding':'2px 8px'});
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                }
            }
        });

        // Listen for paid orders — move card to pagadas grid
        socket.on('orden_pagada_notificacion', function(data) {
            refreshCountdown = AUTO_REFRESH_SECS;
            moveCardToPagadas(data.orden_id);
        });
    }

    // =============================================
    // Move active card to paid grid (reusable)
    // =============================================
    function moveCardToPagadas(ordenId) {
        var card = document.getElementById('orden-card-' + ordenId);
        if (!card) { console.log('moveCardToPagadas: card not found for orden', ordenId); return; }

        // Read data attributes (reliable, set by Jinja template)
        var orderNumText = card.dataset.ordenNum || ('#' + ordenId);
        var mesaLabel = card.dataset.mesaLabel || '';
        var mesaIcon = card.dataset.mesaIcon || 'armchair';
        var totalText = '$' + (card.dataset.total || '0.00');
        var totalItems = parseInt(card.dataset.itemsCount || '0', 10);

        // Build items summary from product-item elements
        var itemEls = card.querySelectorAll('[id^="product-item-"]');
        var itemsHtml = '';
        itemEls.forEach(function(el, i) {
            if (i >= 4) return;
            var nameEl = el.querySelector('.cl-item-name');
            var qtyEl = el.querySelector('.cl-item-qty');
            var name = nameEl ? nameEl.textContent.trim() : '';
            var qty = qtyEl ? qtyEl.textContent.trim() : '';
            if (name) {
                itemsHtml += '<div style="display:flex;align-items:center;gap:8px;font-size:13px;">' +
                    '<span style="width:6px;height:6px;border-radius:50%;background:var(--cl-success-500);flex-shrink:0;opacity:0.5;"></span>' +
                    '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--cl-text-tertiary);font-weight:500;">' + name + '</span>' +
                    (qty ? '<span style="flex-shrink:0;font-size:12px;color:var(--cl-text-tertiary);">' + qty + '</span>' : '') +
                    '</div>';
            }
        });
        if (totalItems > 4) {
            itemsHtml += '<span style="font-size:11px;color:var(--cl-text-tertiary);">+' + (totalItems - 4) + ' más...</span>';
        }

        var now = new Date();
        var timeStr = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');

        // Animate removal from active grid
        card.style.transition = 'opacity 0.5s, transform 0.5s';
        card.style.opacity = '0';
        card.style.transform = 'scale(0.9)';
        setTimeout(function() {
            card.remove();
            updateFilterCounters();

            // Create paid card in pagadas grid
            var pagadasGrid = document.getElementById('ordenesPagadasGrid');
            if (pagadasGrid) {
                // Remove "no orders" empty state if present
                var emptyState = pagadasGrid.querySelector('[style*="grid-column"]');
                if (emptyState) emptyState.remove();

                var paidCard = document.createElement('div');
                paidCard.className = 'cl-order-card cl-order-card--paid';
                paidCard.id = 'orden-paid-' + ordenId;
                paidCard.setAttribute('data-orden-id', ordenId);
                paidCard.setAttribute('data-filters', 'pagadas');
                paidCard.innerHTML =
                    '<div style="padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,0.07);display:flex;align-items:flex-start;justify-content:space-between;">' +
                        '<div>' +
                            '<div style="font-family:var(--cl-font-mono);font-size:20px;font-weight:900;letter-spacing:-0.02em;line-height:1;color:var(--cl-text-secondary);">' + orderNumText + '</div>' +
                            '<div style="font-size:12px;color:var(--cl-text-tertiary);margin-top:4px;display:flex;align-items:center;gap:4px;">' +
                                '<i data-lucide="' + mesaIcon + '" style="width:11px;height:11px;"></i> ' + mesaLabel +
                            '</div>' +
                        '</div>' +
                        '<div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px;">' +
                            '<span class="cl-status cl-status--paid" style="font-size:10px;padding:2px 8px;">' +
                                '<i data-lucide="circle-check" style="width:10px;height:10px;"></i> Pagada' +
                            '</span>' +
                        '</div>' +
                    '</div>' +
                    '<div style="padding:12px 16px;">' +
                        '<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:10px;">' + itemsHtml + '</div>' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:var(--cl-text-tertiary);">' +
                            '<div style="display:flex;align-items:center;gap:4px;"><i data-lucide="clock" style="width:11px;height:11px;"></i> Pagada ' + timeStr + '</div>' +
                            '<span>' + totalItems + ' ítem' + (totalItems !== 1 ? 's' : '') + '</span>' +
                            '<span style="font-family:var(--cl-font-mono);color:var(--cl-success-500);font-weight:700;opacity:0.8;">' + totalText + '</span>' +
                        '</div>' +
                    '</div>' +
                    '<div style="padding:10px 14px 12px;display:flex;gap:8px;" class="card-actions-row">' +
                        '<button type="button" class="cl-btn--v7-outline cl-btn--sm btn-cobrar-orden" style="flex:1;justify-content:center;text-align:center;" data-orden-id="' + ordenId + '" title="Ver ticket de pago">' +
                            '<i data-lucide="receipt" style="width:12px;height:12px;"></i> Ver Ticket' +
                        '</button>' +
                    '</div>';

                pagadasGrid.prepend(paidCard);
                updatePagadasCounter();
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        }, 500);
    }

    // Update pagadas pill counter
    function updatePagadasCounter() {
        var pagadasGrid = document.getElementById('ordenesPagadasGrid');
        var count = pagadasGrid ? pagadasGrid.querySelectorAll('.cl-order-card--paid').length : 0;
        var pill = document.getElementById('pillCountPagadas');
        if (pill) pill.textContent = count;
    }

    // =============================================
    // Entregar item
    // =============================================
    $(document).on('click', '.btn-entregar-item', function(e) {
        e.stopPropagation();
        e.preventDefault();
        var btn = $(this);
        var detalleId = btn.data('detalle-id');
        var ordenId = btn.data('orden-id');
        if (!detalleId || !ordenId) return;

        btn.prop('disabled', true).text('...');

        $.ajax({
            type: 'POST',
            url: `/meseros/entregar_item/${ordenId}/${detalleId}`,
            success: function(res) {
                if (res.success) {
                    showToast(res.message, 'success');
                    var row = $('#product-item-' + detalleId);
                    row.find('.estado-producto-texto').html('<span class="cl-badge cl-badge--gray" style="font-size:9px;padding:1px 6px;"><i data-lucide="check" style="width:10px;height:10px;"></i></span>');
                    row.find('.accion-producto').html('<span style="font-size:10px;color:var(--cl-success-500);font-weight:600;"><i data-lucide="check-circle" style="width:10px;height:10px;"></i></span>');
                    row.removeClass('detalle-listo-cocina').addClass('detalle-entregado');
                    updateCardProgress(ordenId);
                    updateFilterCounters();
                    verificarEstadoParaCobro(ordenId);
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                } else {
                    showToast(res.message, 'warning');
                    btn.prop('disabled', false).text('Entregar');
                }
            },
            error: function(xhr) {
                showToast(xhr.responseJSON?.message || 'Error al entregar.', 'danger');
                btn.prop('disabled', false).text('Entregar');
            }
        });
    });

    // =============================================
    // Entregar TODOS los items listos de una orden
    // =============================================
    $(document).on('click', '.btn-entregar-todos', function(e) {
        e.stopPropagation();
        e.preventDefault();
        var btn = $(this);
        var ordenId = btn.data('orden-id');
        if (!ordenId) return;
        btn.prop('disabled', true).text('...');

        // Find all visible Entregar buttons for this order
        var card = $('#orden-card-' + ordenId);
        var entregarBtns = card.find('.btn-entregar-item');
        var total = entregarBtns.length;
        var done = 0;

        if (total === 0) {
            btn.prop('disabled', false).text('Entregar todos');
            return;
        }

        entregarBtns.each(function() {
            var itemBtn = $(this);
            var detalleId = itemBtn.data('detalle-id');
            itemBtn.prop('disabled', true).text('...');

            $.ajax({
                type: 'POST',
                url: `/meseros/entregar_item/${ordenId}/${detalleId}`,
                success: function(res) {
                    if (res.success) {
                        var row = $('#product-item-' + detalleId);
                        row.find('.estado-producto-texto').html('<span class="cl-badge cl-badge--gray" style="font-size:9px;padding:1px 6px;"><i data-lucide="check" style="width:10px;height:10px;"></i></span>');
                        row.find('.accion-producto').html('<span style="font-size:10px;color:var(--cl-success-500);font-weight:600;"><i data-lucide="check-circle" style="width:10px;height:10px;"></i></span>');
                        row.removeClass('detalle-listo-cocina').addClass('detalle-entregado');
                    }
                },
                complete: function() {
                    done++;
                    if (done >= total) {
                        showToast(`Todos los ítems de orden #${ordenId} entregados.`, 'confetti');
                        updateCardProgress(ordenId);
                        updateFilterCounters();
                        verificarEstadoParaCobro(ordenId);
                        btn.remove(); // Remove "Entregar todos" button
                        if (typeof lucide !== 'undefined') lucide.createIcons();
                    }
                }
            });
        });
    });

    // =============================================
    // Update progress bar in card
    // =============================================
    function updateCardProgress(ordenId) {
        var card = $('#orden-card-' + ordenId);
        if (!card.length) return;
        var items = card.find('[id^="product-item-"]');
        var total = items.length;
        var done = 0;
        items.each(function() {
            var hasGray = $(this).find('.cl-badge--gray').length > 0;
            var hasGreen = $(this).find('.cl-badge--green').length > 0;
            if (hasGray || hasGreen) done++;
        });
        var pct = total > 0 ? Math.round(done * 100 / total) : 0;
        var allEntregado = card.find('.cl-badge--gray').length === total && total > 0;

        var progressRow = card.find('.cl-progress-row');
        progressRow.find('.cl-progress-fill').css({
            'width': pct + '%',
            'background': allEntregado ? 'var(--cl-success-500)' : (pct > 0 ? 'var(--cl-warning-500)' : 'transparent')
        });
        progressRow.find('.cl-progress-label').text(done + '/' + total);

        // Remove "Entregar todos" if no more listo items
        var listoCount = card.find('.cl-badge--green').length;
        if (listoCount === 0) {
            progressRow.find('.btn-entregar-todos').remove();
        }
    }

    // =============================================
    // Verificar estado para cobro
    // =============================================
    window.verificarEstadoParaCobro = function(ordenId) {
        // Support both card layout (Sprint 9) and legacy accordion
        var el = $('#orden-card-' + ordenId);
        if (!el.length) el = $('#orden-acordeon-' + ordenId);
        if (!el.length) return;
        var todos = true;
        var items = el.find('.estado-producto-texto');
        if (!items.length) { todos = false; }
        else {
            items.each(function() {
                var txt = $(this).text().trim().toLowerCase();
                if (txt !== 'entregado' && txt !== '') {
                    // Check for the check icon (entregado badge has no text, just icon)
                    var hasBadgeGray = $(this).find('.cl-badge--gray').length > 0;
                    if (!hasBadgeGray) {
                        todos = false; return false;
                    }
                }
            });
        }
        var btn = el.find('.btn-cobrar-orden');
        if (btn.length) {
            btn.prop('disabled', !todos);
            if (todos) {
                btn.css({'opacity': '1', 'pointer-events': 'auto', 'cursor': 'pointer'});
                btn.removeAttr('title');
            } else {
                btn.css({'opacity': '0.4', 'pointer-events': 'none', 'cursor': 'not-allowed'});
                btn.attr('title', 'Espera a que todos los ítems sean entregados');
            }
        }
    };

    // =============================================
    // Mostrar modal de cobro (con IVA, descuentos, multi-pago)
    // =============================================
    window.mostrarCobro = async function(ordenId) {
        const body = $('#modalCobroBody');
        const el = document.getElementById('modalCobro');
        if (!body.length || !el) return;

        body.html('<div style="display:flex;justify-content:center;padding:40px;"><div class="spinner-border" style="color:var(--cl-red-500);" role="status"><span class="visually-hidden">Cargando...</span></div></div>');
        (bootstrap.Modal.getInstance(el) || new bootstrap.Modal(el)).show();

        try {
            const res = await fetch(`/meseros/ordenes/${ordenId}/cobrar_info`);
            if (!res.ok) throw new Error('Error cargando datos');
            const data = await res.json();

            let html = `
                <div style="text-align:center;margin-bottom:16px;">
                    <img src="/static/img/logoCasaLeones.svg" alt="Logo" style="max-height:36px;opacity:0.8;">
                </div>
                <div style="font-size:16px;font-weight:700;color:var(--cl-text-primary);letter-spacing:-0.02em;">
                    Orden #${data.orden_id}${data.mesa_numero ? ' — Mesa ' + data.mesa_numero : ' — Para Llevar'}
                </div>
                <div style="height:1px;background:var(--cl-border-color);margin:14px 0;"></div>

                <!-- Products table -->
                <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <thead>
                        <tr style="color:var(--cl-text-tertiary);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">
                            <td style="padding:6px 0;">Producto</td>
                            <td style="padding:6px 0;text-align:center;">Cant</td>
                            <td style="padding:6px 0;text-align:right;">Precio</td>
                            <td style="padding:6px 0;text-align:right;">Subtotal</td>
                        </tr>
                    </thead>
                    <tbody>`;

            data.detalles.forEach(item => {
                html += `<tr style="border-bottom:1px solid var(--cl-border-color);">
                    <td style="padding:8px 0;color:var(--cl-text-primary);font-weight:500;">${item.nombre}</td>
                    <td style="padding:8px 0;text-align:center;color:var(--cl-text-secondary);">${item.cantidad}</td>
                    <td style="padding:8px 0;text-align:right;color:var(--cl-text-secondary);">$${item.precio.toFixed(2)}</td>
                    <td style="padding:8px 0;text-align:right;color:var(--cl-text-primary);font-weight:600;">$${item.subtotal.toFixed(2)}</td>
                </tr>`;
            });

            html += `</tbody></table>

                <!-- Totals section -->
                <div style="margin-top:14px;display:flex;flex-direction:column;gap:6px;">
                    <div style="display:flex;justify-content:space-between;font-size:13px;">
                        <span style="color:var(--cl-text-secondary);">Subtotal</span>
                        <span style="color:var(--cl-text-primary);">$${data.subtotal.toFixed(2)}</span>
                    </div>`;

            if (data.descuento_pct > 0) {
                html += `<div style="display:flex;justify-content:space-between;font-size:13px;">
                    <span style="color:var(--cl-error-500);">Descuento (${data.descuento_pct}%)</span>
                    <span style="color:var(--cl-error-500);">-</span>
                </div>`;
            }
            if (data.descuento_monto > 0) {
                html += `<div style="display:flex;justify-content:space-between;font-size:13px;">
                    <span style="color:var(--cl-error-500);">Descuento fijo</span>
                    <span style="color:var(--cl-error-500);">-$${data.descuento_monto.toFixed(2)}</span>
                </div>`;
            }

            html += `
                    <div style="display:flex;justify-content:space-between;font-size:13px;">
                        <span style="color:var(--cl-text-secondary);">IVA (${data.iva_rate}%)</span>
                        <span style="color:var(--cl-text-primary);">$${data.iva.toFixed(2)}</span>
                    </div>
                    <div style="height:1px;background:var(--cl-border-color);margin:4px 0;"></div>
                    <div style="display:flex;justify-content:space-between;font-size:18px;font-weight:800;letter-spacing:-0.02em;">
                        <span style="color:var(--cl-text-primary);">Total</span>
                        <span style="color:var(--cl-text-primary);">$${data.total.toFixed(2)}</span>
                    </div>
                </div>`;

            // Pagos previos (split)
            if (data.pagos.length > 0) {
                html += `<div style="height:1px;background:var(--cl-border-color);margin:16px 0;"></div>
                    <div style="font-size:13px;font-weight:700;color:var(--cl-text-primary);margin-bottom:8px;">Pagos registrados</div>`;
                data.pagos.forEach(p => {
                    html += `<div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--cl-surface-3);border-radius:var(--cl-radius-sm);margin-bottom:6px;border:1px solid var(--cl-border-color);">
                        <span style="color:var(--cl-text-secondary);font-size:13px;">${p.metodo}${p.referencia ? ' ('+p.referencia+')' : ''}</span>
                        <span style="color:var(--cl-text-primary);font-size:13px;font-weight:600;">$${p.monto.toFixed(2)}</span>
                    </div>`;
                });
                html += `
                    <div style="display:flex;justify-content:space-between;font-size:13px;margin-top:8px;">
                        <span style="color:var(--cl-text-secondary);font-weight:600;">Pagado</span>
                        <span style="color:var(--cl-success-500);font-weight:700;">$${data.total_pagado.toFixed(2)}</span>
                    </div>`;
                if (data.saldo_pendiente > 0) {
                    html += `<div style="display:flex;justify-content:space-between;font-size:14px;font-weight:700;">
                        <span style="color:var(--cl-warning-500);">Saldo pendiente</span>
                        <span style="color:var(--cl-warning-500);">$${data.saldo_pendiente.toFixed(2)}</span>
                    </div>`;
                } else if (data.cambio > 0) {
                    html += `<div style="display:flex;justify-content:space-between;font-size:14px;font-weight:700;">
                        <span style="color:var(--cl-success-500);">Cambio</span>
                        <span style="color:var(--cl-success-500);">$${data.cambio.toFixed(2)}</span>
                    </div>`;
                }
            }

            if (data.saldo_pendiente <= 0 && data.pagos.length > 0) {
                html += `<div style="margin-top:16px;padding:14px;background:rgba(18,183,106,0.1);border:1px solid rgba(18,183,106,0.2);border-radius:var(--cl-radius-sm);text-align:center;color:var(--cl-success-500);font-weight:600;font-size:14px;">
                    <i data-lucide="check-circle" style="width:16px;height:16px;margin-right:6px;vertical-align:-3px;"></i>Orden completamente pagada
                </div>`;
            } else {
                // Propina section
                html += `
                <div style="height:1px;background:var(--cl-border-color);margin:16px 0;"></div>
                <div style="font-size:13px;font-weight:700;color:var(--cl-text-primary);margin-bottom:10px;">Propina</div>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px;">
                    <button type="button" class="cl-propina-btn active" data-pct="0" data-orden="${ordenId}">Sin</button>
                    <button type="button" class="cl-propina-btn" data-pct="10" data-orden="${ordenId}">10%</button>
                    <button type="button" class="cl-propina-btn" data-pct="15" data-orden="${ordenId}">15%</button>
                    <button type="button" class="cl-propina-btn" data-pct="20" data-orden="${ordenId}">20%</button>
                </div>
                <div style="margin-bottom:14px;">
                    <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Propina personalizada ($)</label>
                    <input type="number" step="0.01" min="0" id="propina_monto_${ordenId}" class="cl-input" value="0" placeholder="0.00">
                </div>

                <!-- Registrar Pago section -->
                <div style="height:1px;background:var(--cl-border-color);margin:16px 0;"></div>
                <div style="font-size:13px;font-weight:700;color:var(--cl-text-primary);margin-bottom:10px;">Registrar Pago</div>
                <div style="margin-bottom:10px;">
                    <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Método de pago</label>
                    <select id="pago_metodo_${ordenId}" class="cl-input">
                        <option value="efectivo">Efectivo</option>
                        <option value="tarjeta">Tarjeta</option>
                        <option value="transferencia">Transferencia</option>
                    </select>
                </div>
                <div style="margin-bottom:10px;display:none;" id="referencia_group_${ordenId}">
                    <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Referencia (últimos 4 dígitos / folio)</label>
                    <input type="text" id="pago_referencia_${ordenId}" class="cl-input" maxlength="20">
                </div>
                <div style="margin-bottom:14px;">
                    <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Monto</label>
                    <input type="number" step="0.01" id="pago_monto_${ordenId}" class="cl-input"
                           value="${data.saldo_pendiente.toFixed(2)}" min="0.01">
                </div>
                <div style="display:flex;gap:8px;">
                    <button class="cl-btn--v7-success btn-registrar-pago" data-orden-id="${ordenId}" style="flex:1;justify-content:center;padding:10px 18px;font-size:14px;">
                        <i data-lucide="banknote" style="width:15px;height:15px;"></i> Registrar Pago
                    </button>
                    <button class="cl-btn--v7-outline btn-aplicar-descuento" data-orden-id="${ordenId}" style="padding:10px 14px;">
                        <i data-lucide="percent" style="width:14px;height:14px;"></i> Descuento
                    </button>
                </div>`;
            }

            html += `<div style="margin-top:10px;">
                <button class="cl-btn--v7-ghost btn-imprimir-ticket" data-orden-id="${ordenId}" style="width:100%;justify-content:center;padding:8px;font-size:12px;">
                    <i data-lucide="printer" style="width:13px;height:13px;"></i> Imprimir Ticket
                </button>
            </div>`;

            body.html(html);

            // Lucide icons
            if (typeof lucide !== 'undefined') lucide.createIcons();

            // Toggle referencia field
            $(`#pago_metodo_${ordenId}`).on('change', function() {
                $(`#referencia_group_${ordenId}`).toggle($(this).val() !== 'efectivo');
            });

            // Registrar pago handler
            body.find('.btn-registrar-pago').on('click', function() { registrarPago(ordenId); });

            // Descuento handler
            body.find('.btn-aplicar-descuento').on('click', function() { mostrarFormDescuento(ordenId); });

            // Print handler
            body.find('.btn-imprimir-ticket').on('click', function() { imprimirTicket(ordenId); });

            // Propina percentage buttons
            body.find('.cl-propina-btn').on('click', function() {
                body.find('.cl-propina-btn').removeClass('active');
                $(this).addClass('active');
                const pct = parseFloat($(this).data('pct'));
                const propinaVal = (data.total * pct / 100);
                $(`#propina_monto_${ordenId}`).val(propinaVal.toFixed(2));
            });

        } catch (err) {
            body.html(`<div style="padding:20px;text-align:center;color:var(--cl-error-500);font-weight:600;">Error: ${err.message}</div>`);
        }
    };

    // =============================================
    // Registrar pago (multi-método / split)
    // =============================================
    async function registrarPago(ordenId) {
        const metodo = $(`#pago_metodo_${ordenId}`).val();
        const monto = parseFloat($(`#pago_monto_${ordenId}`).val());
        const referencia = $(`#pago_referencia_${ordenId}`).val() || '';
        const propina = parseFloat($(`#propina_monto_${ordenId}`).val()) || 0;

        if (isNaN(monto) || monto <= 0) {
            showToast('Ingresa un monto válido.', 'warning'); return;
        }

        try {
            const res = await fetch(`/meseros/ordenes/${ordenId}/pago`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ metodo, monto, referencia, propina }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message);

            if (data.orden_pagada) {
                const modalEl = document.getElementById('modalCobro');
                const inst = bootstrap.Modal.getInstance(modalEl);
                if (inst) inst.hide();
                let cambioMsg = data.cambio > 0 ? ` Cambio: $${data.cambio.toFixed(2)}` : '';
                showToast(`Orden #${ordenId} pagada.${cambioMsg}`, 'confetti');
                // Move card to pagadas grid instead of reloading
                moveCardToPagadas(ordenId);
            } else {
                showToast(`Pago de $${data.monto.toFixed(2)} (${metodo}) registrado. Saldo: $${data.saldo_pendiente.toFixed(2)}`, 'info');
                // Refresh modal
                mostrarCobro(ordenId);
            }
        } catch (err) {
            showToast(err.message, 'danger');
        }
    }

    // =============================================
    // Formulario de descuento (con autorización)
    // =============================================
    function mostrarFormDescuento(ordenId) {
        const body = $('#modalCobroBody');
        const prev = body.html();
        body.html(`
            <div style="font-size:16px;font-weight:700;color:var(--cl-text-primary);letter-spacing:-0.02em;">
                Aplicar Descuento — Orden #${ordenId}
            </div>
            <div style="height:1px;background:var(--cl-border-color);margin:14px 0;"></div>
            <div style="margin-bottom:12px;">
                <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Tipo</label>
                <select id="desc_tipo" class="cl-input">
                    <option value="porcentaje">Porcentaje (%)</option>
                    <option value="monto">Monto fijo ($)</option>
                </select>
            </div>
            <div style="margin-bottom:12px;">
                <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Valor</label>
                <input type="number" step="0.01" id="desc_valor" class="cl-input" min="0" placeholder="Ej: 10">
            </div>
            <div style="margin-bottom:12px;">
                <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Motivo</label>
                <input type="text" id="desc_motivo" class="cl-input" placeholder="Cortesía, error de cocina...">
            </div>
            <div style="height:1px;background:var(--cl-border-color);margin:14px 0;"></div>
            <div style="font-size:13px;font-weight:700;color:var(--cl-text-primary);margin-bottom:10px;">
                <i data-lucide="shield-check" style="width:14px;height:14px;vertical-align:-2px;margin-right:4px;"></i>Autorización (Admin/Superadmin)
            </div>
            <div style="margin-bottom:10px;">
                <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Email autorizador</label>
                <input type="email" id="desc_auth_email" class="cl-input" placeholder="admin@casaleones.com">
            </div>
            <div style="margin-bottom:14px;">
                <label style="display:block;font-size:12px;color:var(--cl-text-tertiary);margin-bottom:4px;font-weight:500;">Contraseña</label>
                <input type="password" id="desc_auth_pass" class="cl-input" placeholder="••••••••">
            </div>
            <div style="display:flex;gap:8px;">
                <button class="cl-btn--v7-success" id="btnConfirmarDesc" style="flex:1;justify-content:center;padding:10px 18px;font-size:14px;">
                    <i data-lucide="check" style="width:14px;height:14px;"></i> Confirmar Descuento
                </button>
                <button class="cl-btn--v7-outline" id="btnCancelarDesc" style="padding:10px 14px;">
                    Cancelar
                </button>
            </div>
        `);

        if (typeof lucide !== 'undefined') lucide.createIcons();        $('#btnCancelarDesc').on('click', function() { mostrarCobro(ordenId); });
        $('#btnConfirmarDesc').on('click', async function() {
            try {
                const res = await fetch(`/meseros/ordenes/${ordenId}/descuento`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        tipo: $('#desc_tipo').val(),
                        valor: parseFloat($('#desc_valor').val()) || 0,
                        motivo: $('#desc_motivo').val(),
                        auth_email: $('#desc_auth_email').val(),
                        auth_password: $('#desc_auth_pass').val(),
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.message);
                showToast('Descuento aplicado.', 'success');
                mostrarCobro(ordenId);
            } catch (err) {
                showToast(err.message, 'danger');
            }
        });
    }

    // =============================================
    // Imprimir ticket (Item 10)
    // =============================================
    window.imprimirTicket = async function(ordenId) {
        try {
            const res = await fetch(`/meseros/ordenes/${ordenId}/cobrar_info`);
            if (!res.ok) throw new Error('No se pudieron cargar los datos');
            const data = await res.json();

            const win = window.open('', '_blank', 'width=350,height=600');
            let html = `<!DOCTYPE html><html><head><meta charset="utf-8">
                <title>Ticket #${data.orden_id}</title>
                <style>
                    body{font-family:'Courier New',monospace;font-size:12px;width:280px;margin:0 auto;padding:10px;}
                    .center{text-align:center;}
                    .bold{font-weight:bold;}
                    .line{border-top:1px dashed #000;margin:5px 0;}
                    table{width:100%;border-collapse:collapse;}
                    td{padding:2px 0;}
                    .right{text-align:right;}
                    .total-row td{font-weight:bold;font-size:14px;padding-top:5px;}
                    @media print{body{margin:0;padding:5px;}}
                </style></head><body>
                <div class="center bold" style="font-size:16px;">CASA LEONES</div>
                <div class="center">Ticket de Venta</div>
                <div class="line"></div>
                <div>Orden: #${data.orden_id}</div>
                <div>${data.mesa_numero ? 'Mesa: ' + data.mesa_numero : 'Para Llevar'}</div>
                <div>Fecha: ${new Date().toLocaleString('es-MX')}</div>
                <div class="line"></div>
                <table>
                    <tr class="bold"><td>Producto</td><td class="right">Cant</td><td class="right">P.U.</td><td class="right">Importe</td></tr>`;

            data.detalles.forEach(item => {
                html += `<tr><td>${item.nombre}</td><td class="right">${item.cantidad}</td><td class="right">$${item.precio.toFixed(2)}</td><td class="right">$${item.subtotal.toFixed(2)}</td></tr>`;
            });

            html += `</table>
                <div class="line"></div>
                <table>
                    <tr><td>Subtotal</td><td class="right">$${data.subtotal.toFixed(2)}</td></tr>`;

            if (data.descuento_pct > 0) {
                html += `<tr><td>Descuento (${data.descuento_pct}%)</td><td class="right">-</td></tr>`;
            }
            if (data.descuento_monto > 0) {
                html += `<tr><td>Descuento</td><td class="right">-$${data.descuento_monto.toFixed(2)}</td></tr>`;
            }

            html += `<tr><td>IVA (${data.iva_rate}%)</td><td class="right">$${data.iva.toFixed(2)}</td></tr>
                    <tr class="total-row"><td>TOTAL</td><td class="right">$${data.total.toFixed(2)}</td></tr>
                </table>`;

            if (data.pagos.length > 0) {
                html += `<div class="line"></div><div class="bold">Pagos:</div>`;
                data.pagos.forEach(p => {
                    html += `<div>${p.metodo}: $${p.monto.toFixed(2)}${p.referencia ? ' ('+p.referencia+')' : ''}</div>`;
                });
            }

            html += `<div class="line"></div>
                <div class="center">¡Gracias por su visita!</div>
                <div class="center" style="font-size:10px;">Casa Leones POS v2.0</div>
                <script>window.onload=function(){window.print();}<\/script>
                </body></html>`;

            win.document.write(html);
            win.document.close();
        } catch (err) {
            showToast('Error generando ticket: ' + err.message, 'danger');
        }
    };

    // =============================================
    // Delegación botón cobrar
    // =============================================
    $(document).on('click', '.btn-cobrar-orden:not(:disabled)', function() {
        var ordenId = $(this).data('orden-id');
        if (ordenId) mostrarCobro(ordenId);
    });

    // Modal cleanup
    const modalCobroEl = document.getElementById('modalCobro');
    if (modalCobroEl) {
        modalCobroEl.addEventListener('hidden.bs.modal', () => {
            document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
        });
    }

    // Verificar cobro al cargar — support both card and accordion layouts
    $('[id^="orden-card-"], .accordion-item[id^="orden-acordeon-"]').each(function() {
        var id = $(this).attr('id');
        var ordenId = id.replace('orden-card-', '').replace('orden-acordeon-', '');
        if (ordenId) verificarEstadoParaCobro(ordenId);
    });

    // =============================================
    // Filter counter real-time updates
    // =============================================
    function updateFilterCounters() {
        var cards = $('[id^="orden-card-"]');
        var totalCount = cards.length;
        var enCocinaCount = 0;
        var listasCount = 0;

        cards.each(function() {
            var statusEl = $(this).find('.cl-status');
            var statusText = statusEl.text().trim().toLowerCase();
            if (statusText.indexOf('cocina') >= 0 || statusText.indexOf('preparación') >= 0 || statusText.indexOf('enviado') >= 0) {
                enCocinaCount++;
            } else if (statusText.indexOf('lista') >= 0 || statusText.indexOf('completada') >= 0) {
                listasCount++;
            }
        });

        // Update header counter chips
        var counterTotal = document.getElementById('counterTotal');
        var counterCocina = document.getElementById('counterCocina');
        var counterListas = document.getElementById('counterListas');
        if (counterTotal) counterTotal.innerHTML = '<i data-lucide="clipboard-list" style="width:11px;height:11px;"></i> ' + totalCount + ' activa' + (totalCount !== 1 ? 's' : '');
        if (counterCocina) {
            counterCocina.innerHTML = '<i data-lucide="clock" style="width:11px;height:11px;"></i> ' + enCocinaCount + ' en cocina';
            counterCocina.style.display = enCocinaCount > 0 ? '' : 'none';
        }
        if (counterListas) {
            counterListas.innerHTML = '<i data-lucide="check-circle" style="width:11px;height:11px;"></i> ' + listasCount + (listasCount === 1 ? ' lista' : ' listas');
            counterListas.style.display = listasCount > 0 ? '' : 'none';
        }

        // Update filter pill counters
        var pillAll = document.getElementById('pillCountAll');
        var pillCocina = document.getElementById('pillCountCocina');
        var pillListas = document.getElementById('pillCountListas');
        if (pillAll) pillAll.textContent = totalCount;
        if (pillCocina) pillCocina.textContent = enCocinaCount;
        if (pillListas) pillListas.textContent = listasCount;

        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    // Initial counter update
    updateFilterCounters();

    // =============================================
    // Keyboard shortcuts
    // =============================================
    $(document).on('keydown', function(e) {
        // Ignore if typing in input/textarea/modal
        var tag = e.target.tagName.toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
        if ($('.modal.show').length > 0) return;

        switch(e.key.toLowerCase()) {
            case 'r':
                e.preventDefault();
                location.reload();
                break;
            case '1':
                e.preventDefault();
                $('[data-filter="all"]').click();
                break;
            case '2':
                e.preventDefault();
                $('[data-filter="cocina"]').click();
                break;
            case '3':
                e.preventDefault();
                $('[data-filter="lista"]').click();
                break;
            case '4':
                e.preventDefault();
                $('[data-filter="pagadas"]').click();
                break;
            case 's':
                e.preventDefault();
                $('#btnToggleSound').click();
                break;
        }
    });

});
