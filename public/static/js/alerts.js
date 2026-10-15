/* Alerts management JS */
function markAlertRead(alertId) {
    fetch('/admin/alerts/' + alertId + '/read', { method: 'POST' })
        .then(function() { location.reload(); })
        .catch(function() {});
}

function markAllRead() {
    fetch('/admin/alerts/read-all', { method: 'POST' })
        .then(function() { location.reload(); })
        .catch(function() {});
}
