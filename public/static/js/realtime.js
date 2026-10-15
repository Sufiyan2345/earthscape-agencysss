/* Realtime data streaming with SSE support and anomaly detection */
let realtimeInterval = null;
let eventSource = null;

function startRealtimeUpdates(streamId, baseUrl) {
    if (realtimeInterval) clearInterval(realtimeInterval);
    if (eventSource) { eventSource.close(); eventSource = null; }

    var url = (baseUrl || '') + '/' + streamId + '/data';

    // Try SSE first for true streaming
    if (typeof(EventSource) !== 'undefined') {
        try {
            var sseUrl = (baseUrl || '') + '/' + streamId + '/stream';
            eventSource = new EventSource(sseUrl);
            eventSource.onmessage = function(e) {
                var data = JSON.parse(e.data);
                updateRealtimeDisplay(data.readings || data);
                if (data.anomalies && data.anomalies.length > 0) {
                    updateAnomalyDisplay(data.anomalies);
                }
            };
            eventSource.onerror = function() {
                if (eventSource) { eventSource.close(); eventSource = null; }
                // Fallback to polling
                startPolling(streamId, baseUrl);
            };
            return;
        } catch(e) {
            // Fallback to polling
        }
    }

    startPolling(streamId, baseUrl);
}

function startPolling(streamId, baseUrl) {
    if (realtimeInterval) clearInterval(realtimeInterval);
    var url = (baseUrl || '') + '/' + streamId + '/data';
    realtimeInterval = setInterval(function() {
        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                var data = resp.readings || resp;
                updateRealtimeDisplay(data);
                if (resp.anomalies && resp.anomalies.length > 0) {
                    updateAnomalyDisplay(resp.anomalies);
                }
            })
            .catch(function() {});
    }, 3000);
}

function updateRealtimeDisplay(data) {
    if (!data || data.length === 0) return;
    const latest = data[0];
    const tempEl = document.getElementById('rt-temp');
    const humEl = document.getElementById('rt-humidity');
    const windEl = document.getElementById('rt-wind');
    const aqiEl = document.getElementById('rt-aqi');
    if (tempEl && latest.temperature !== null) tempEl.textContent = latest.temperature + '°C';
    if (humEl && latest.humidity !== null) humEl.textContent = latest.humidity + '%';
    if (windEl && latest.wind_speed !== null) windEl.textContent = latest.wind_speed + ' km/h';
    if (aqiEl && latest.air_quality_index !== null) aqiEl.textContent = latest.air_quality_index;
}

function updateAnomalyDisplay(anomalies) {
    var anomalyCount = document.getElementById('anomalies');
    if (anomalyCount && anomalies) {
        anomalyCount.textContent = anomalies.length;
        anomalyCount.style.color = anomalies.length > 0 ? 'var(--danger)' : '';
    }
}

function stopRealtimeUpdates() {
    if (realtimeInterval) { clearInterval(realtimeInterval); realtimeInterval = null; }
    if (eventSource) { eventSource.close(); eventSource = null; }
}

document.addEventListener('DOMContentLoaded', function() {
    var autoRefresh = document.getElementById('autoRefresh');
    if (autoRefresh) {
        autoRefresh.addEventListener('change', function() {
            var el = document.getElementById('rtData');
            var streams = JSON.parse(el.getAttribute('data-streams') || '[]');
            var baseUrl = el.getAttribute('data-base') || '';
            if (streams.length === 0) return;
            var streamId = streams[0].id;
            if (this.checked) { startRealtimeUpdates(streamId, baseUrl); }
            else { stopRealtimeUpdates(); }
        });
    }
});
