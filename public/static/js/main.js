/* EarthScape Climate System - Main JavaScript */

var _notifPollTimer = null;
var _notifCountUrl = null;

function _updateNotifBadge(count) {
    var badge = document.getElementById('alertBadge');
    if (badge) {
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'inline';
        } else {
            badge.style.display = 'none';
        }
    }
    var dot = document.getElementById('notifDot');
    if (dot) dot.style.display = count > 0 ? 'block' : 'none';
    var countEl = document.getElementById('notifCount');
    if (countEl) {
        countEl.textContent = count;
        countEl.style.display = count > 0 ? 'inline' : 'none';
    }
}

function checkNotifications() {
    if (!_notifCountUrl) return;
    fetch(_notifCountUrl)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _updateNotifBadge(data.count || 0);
        })
        .catch(function() {});
}

function startNotifPolling(countUrl, intervalMs) {
    if (_notifPollTimer) return;
    var cfg = document.getElementById('notifConfig');
    var enabled = cfg ? (cfg.getAttribute('data-realtime-enabled') !== 'false') : true;
    var interval = intervalMs || (cfg ? parseInt(cfg.getAttribute('data-refresh-interval') || '30000', 10) : 30000);
    if (!enabled) return;
    _notifCountUrl = countUrl;
    checkNotifications();
    _notifPollTimer = setInterval(checkNotifications, interval || 30000);
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            clearInterval(_notifPollTimer);
            _notifPollTimer = null;
        } else {
            if (!_notifPollTimer) {
                checkNotifications();
                _notifPollTimer = setInterval(checkNotifications, interval || 30000);
            }
        }
    });
}

function stopNotifPolling() {
    if (_notifPollTimer) {
        clearInterval(_notifPollTimer);
        _notifPollTimer = null;
    }
}

/* Toggle the notification dropdown opened from the header bell. */
function toggleNotifDropdown(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    var dd = document.getElementById('notifDropdown');
    if (!dd) return;
    var isOpen = dd.style.display === 'block';
    dd.style.display = isOpen ? 'none' : 'block';
    if (!isOpen) loadNotifList();
}

/* Load recent notifications into the dropdown list. */
function loadNotifList() {
    var cfg = document.getElementById('notifConfig');
    var listEl = document.getElementById('notifList');
    if (!cfg || !listEl) return;
    var url = cfg.getAttribute('data-recent-url');
    if (!url) return;
    fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var items = data.notifications || data.alerts || [];
            if (!items.length) {
                listEl.innerHTML = '<p style="text-align:center;color:rgba(140,193,233,0.6);padding:16px;font-size:13px;">No notifications</p>';
                return;
            }
            listEl.innerHTML = items.map(function (n) {
                var msg = n.message || n.title || '';
                var time = n.time || n.created_at || '';
                var linkStart = n.link ? '<a href="' + n.link + '" style="display:flex;gap:10px;flex:1;color:inherit;text-decoration:none;">' : '<div style="display:flex;gap:10px;flex:1;">';
                var linkEnd = n.link ? '</a>' : '</div>';
                return '<div style="padding:10px 12px;border-bottom:1px solid rgba(26,58,110,0.5);display:flex;gap:10px;">' + linkStart +
                    '<i class="fas fa-bell" style="color:#8CC1E9;margin-top:3px;"></i>' +
                    '<div><div style="font-size:13px;color:#e2e8f0;">' + msg + '</div>' +
                    '<div style="font-size:11px;color:#8CC1E9;">' + time + '</div></div>' + linkEnd + '</div>';
            }).join('');
        })
        .catch(function () {
            listEl.innerHTML = '<p style="text-align:center;color:rgba(140,193,233,0.6);padding:16px;font-size:13px;">Failed to load</p>';
        });
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.alert').forEach(function(alert) {
        setTimeout(function() {
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            setTimeout(function() { alert.remove(); }, 300);
        }, 5000);
    });

    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const appWrapper = document.querySelector('.app-wrapper');
    if (sidebarToggle && sidebar && appWrapper) {
        const storedSidebarState = localStorage.getItem('earthscape.sidebarCollapsed') === 'true';
        sidebar.classList.toggle('collapsed', storedSidebarState);
        appWrapper.classList.toggle('sidebar-collapsed', storedSidebarState);
        sidebarToggle.setAttribute('aria-expanded', String(!storedSidebarState));

        sidebarToggle.addEventListener('click', function(e) {
            e.preventDefault();
            const isCollapsed = sidebar.classList.toggle('collapsed');
            appWrapper.classList.toggle('sidebar-collapsed', isCollapsed);
            sidebarToggle.setAttribute('aria-expanded', String(!isCollapsed));
            localStorage.setItem('earthscape.sidebarCollapsed', String(isCollapsed));
        });
    }

    document.addEventListener('click', function(e) {
        if (sidebar && window.matchMedia('(max-width: 768px)').matches && !sidebar.classList.contains('collapsed')) {
            if (!sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
                sidebar.classList.add('collapsed');
                if (appWrapper) appWrapper.classList.add('sidebar-collapsed');
                if (sidebarToggle) sidebarToggle.setAttribute('aria-expanded', 'false');
                localStorage.setItem('earthscape.sidebarCollapsed', 'true');
            }
        }
    });

    document.addEventListener('click', function(e) {
        var dd = document.getElementById('notifDropdown');
        if (!dd || dd.style.display !== 'block') return;
        var bell = document.getElementById('bellBtn');
        if (bell && !bell.contains(e.target) && !dd.contains(e.target)) {
            dd.style.display = 'none';
        }
    });

    function setModalState(modal, isOpen) {
        if (!modal) return;
        modal.classList.toggle('active', isOpen);
        modal.classList.toggle('is-open', isOpen);
        if (modal.classList.contains('modal-overlay')) {
            document.body.style.overflow = isOpen ? 'hidden' : '';
        }
    }

    document.querySelectorAll('[data-modal]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const modalId = this.getAttribute('data-modal');
            const modal = document.getElementById(modalId);
            if (modal) {
                setModalState(modal, true);
            }
        });
    });

    document.querySelectorAll('.modal-close, .modal-overlay').forEach(function(el) {
        el.addEventListener('click', function(e) {
            if (e.target === this || this.classList.contains('modal-close')) {
                setModalState(this.closest('.modal-overlay'), false);
            }
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key !== 'Escape') return;
        var openModal = document.querySelector('.modal-overlay.active, .modal-overlay.is-open');
        if (openModal) setModalState(openModal, false);
    });

    var confirmState = null;
    function closePanelConfirm() {
        var backdrop = document.querySelector('.panel-confirm-backdrop');
        if (!backdrop) return;
        backdrop.classList.remove('is-visible');
        document.body.style.overflow = '';
        setTimeout(function() { backdrop.remove(); }, 160);
        confirmState = null;
    }

    function openPanelConfirm(message, continueAction) {
        closePanelConfirm();
        var backdrop = document.createElement('div');
        backdrop.className = 'panel-confirm-backdrop';
        backdrop.setAttribute('role', 'presentation');
        backdrop.innerHTML = '<section class="panel-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="panelConfirmTitle" aria-describedby="panelConfirmMessage">' +
            '<div class="panel-confirm-icon"><i class="fas fa-shield-halved"></i></div>' +
            '<h3 id="panelConfirmTitle">Please confirm</h3>' +
            '<p id="panelConfirmMessage"></p>' +
            '<div class="panel-confirm-actions"><button type="button" class="panel-confirm-cancel">Cancel</button><button type="button" class="panel-confirm-approve">Continue</button></div>' +
            '</section>';
        backdrop.querySelector('#panelConfirmMessage').textContent = message;
        document.body.appendChild(backdrop);
        document.body.style.overflow = 'hidden';
        confirmState = continueAction;
        backdrop.querySelector('.panel-confirm-cancel').addEventListener('click', closePanelConfirm);
        backdrop.querySelector('.panel-confirm-approve').addEventListener('click', function() {
            var action = confirmState;
            closePanelConfirm();
            if (action) action();
        });
        backdrop.addEventListener('click', function(e) { if (e.target === backdrop) closePanelConfirm(); });
        document.addEventListener('keydown', function handleConfirmKey(e) {
            if (!document.body.contains(backdrop)) { document.removeEventListener('keydown', handleConfirmKey); return; }
            if (e.key === 'Escape') { closePanelConfirm(); document.removeEventListener('keydown', handleConfirmKey); }
        });
        requestAnimationFrame(function() { backdrop.classList.add('is-visible'); backdrop.querySelector('.panel-confirm-cancel').focus(); });
    }

    /* Convert legacy inline confirmations before the browser can execute them. */
    document.querySelectorAll('form[onsubmit], [onclick]').forEach(function(element) {
        var attribute = element.hasAttribute('onsubmit') ? 'onsubmit' : 'onclick';
        var handler = element.getAttribute(attribute) || '';
        if (/confirm\s*\(/i.test(handler)) {
            element.dataset.panelConfirmHandler = handler;
            element.dataset.panelConfirmAttribute = attribute;
            element.removeAttribute(attribute);
        }
    });

    document.addEventListener('submit', function(e) {
        var form = e.target;
        var handler = form.dataset.panelConfirmHandler || '';
        if (!handler || form.dataset.panelConfirmApproved === 'true') return;
        e.preventDefault();
        openPanelConfirm(handler.match(/confirm\s*\(\s*['"]([\s\S]*?)['"]\s*\)/i)?.[1] || 'This action cannot be undone.', function() {
            form.dataset.panelConfirmApproved = 'true';
            form.submit();
        });
    }, true);

    document.addEventListener('click', function(e) {
        var target = e.target.closest ? e.target.closest('[onclick]') : null;
        if (!target || !target.dataset.panelConfirmHandler) return;
        e.preventDefault();
        var handler = target.dataset.panelConfirmHandler;
        openPanelConfirm(handler.match(/confirm\s*\(\s*['"]([\s\S]*?)['"]\s*\)/i)?.[1] || 'This action cannot be undone.', function() {
            var form = target.form;
            if (form) form.dataset.panelConfirmApproved = 'true';
            Function('event', handler).call(target, e);
            if (form && target.type === 'submit') form.requestSubmit(target);
            if (form) delete form.dataset.panelConfirmApproved;
        });
    }, true);

    const uploadZone = document.querySelector('.upload-zone');
    if (uploadZone) {
        ['dragenter', 'dragover'].forEach(function(evt) {
            uploadZone.addEventListener(evt, function(e) {
                e.preventDefault();
                this.classList.add('dragover');
            });
        });

        ['dragleave', 'drop'].forEach(function(evt) {
            uploadZone.addEventListener(evt, function(e) {
                e.preventDefault();
                this.classList.remove('dragover');
            });
        });

        uploadZone.addEventListener('drop', function(e) {
            const files = e.dataTransfer.files;
            const fileInput = document.querySelector('.upload-zone input[type="file"]');
            if (fileInput && files.length > 0) {
                fileInput.files = files;
                const fileName = files[0].name;
                this.querySelector('h4').textContent = fileName;
            }
        });
    }

    document.querySelectorAll('[data-confirm]').forEach(function(el) {
        el.addEventListener('click', function(e) {
            if (!confirm(this.getAttribute('data-confirm'))) {
                e.preventDefault();
            }
        });
    });

    const tooltipElements = document.querySelectorAll('[data-tooltip]');
    tooltipElements.forEach(function(el) {
        el.addEventListener('mouseenter', function() {
            const tip = document.createElement('div');
            tip.className = 'tooltip-popup';
            tip.textContent = this.getAttribute('data-tooltip');
            tip.style.cssText = 'position:absolute;background:#1f2937;color:white;padding:6px 12px;border-radius:6px;font-size:12px;z-index:9999;pointer-events:none;';
            document.body.appendChild(tip);
            const rect = this.getBoundingClientRect();
            tip.style.left = rect.left + 'px';
            tip.style.top = (rect.top - 36) + 'px';
            this._tooltip = tip;
        });
        el.addEventListener('mouseleave', function() {
            if (this._tooltip) {
                this._tooltip.remove();
                this._tooltip = null;
            }
        });
    });

    const notifConfig = document.getElementById('notifConfig');
    const countUrl = notifConfig && notifConfig.getAttribute('data-count-url');
    if (countUrl) {
        startNotifPolling(countUrl, 60000);
    }

    console.log('EarthScape Climate System initialized.');
});
