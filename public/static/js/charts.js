/* EarthScape Chart Factory - Creates charts from real data with export support */
var EarthScapeCharts = (function() {
    var instances = {};

    var COLORS = {
        temperature: '#f87171',
        humidity: '#60a5fa',
        rainfall: '#2dd4bf',
        wind_speed: '#fbbf24',
        pressure: '#a78bfa',
        co2_level: '#38bdf8',
        air_quality_index: '#fb923c',
        visibility: '#818cf8',
        uv_index: '#f472b6',
        soil_moisture: '#4ade80',
        cloud_cover: '#94a3b8',
        snow_depth: '#22d3ee'
    };

    var LABELS = {
        temperature: 'Temperature (°C)',
        humidity: 'Humidity (%)',
        rainfall: 'Rainfall (mm)',
        wind_speed: 'Wind Speed (km/h)',
        pressure: 'Pressure (hPa)',
        co2_level: 'CO2 Level (ppm)',
        air_quality_index: 'Air Quality Index',
        visibility: 'Visibility (km)',
        uv_index: 'UV Index',
        soil_moisture: 'Soil Moisture (%)',
        cloud_cover: 'Cloud Cover (%)',
        snow_depth: 'Snow Depth (cm)'
    };

    function getColor(variable) {
        return COLORS[variable] || '#6b7280';
    }

    function getLabel(variable) {
        return LABELS[variable] || variable.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
    }

    function drawMessage(canvasId, message) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var ctx2d = canvas.getContext('2d');
        if (!ctx2d) return;
        var w = canvas.clientWidth || canvas.width || 300;
        var h = canvas.clientHeight || canvas.height || 150;
        if (canvas.width !== w) canvas.width = w;
        if (canvas.height !== h) canvas.height = h;
        ctx2d.clearRect(0, 0, w, h);
        ctx2d.fillStyle = '#9ca3af';
        ctx2d.font = '14px system-ui, sans-serif';
        ctx2d.textAlign = 'center';
        ctx2d.textBaseline = 'middle';
        ctx2d.fillText(message, w / 2, h / 2);
    }

    function createChart(canvasId, config) {
        var ctx = document.getElementById(canvasId);
        if (!ctx) return null;
        if (typeof Chart === 'undefined') {
            drawMessage(canvasId, 'Chart library failed to load');
            return null;
        }
        if (instances[canvasId]) {
            instances[canvasId].destroy();
        }
        var chart = new Chart(ctx, config);
        instances[canvasId] = chart;
        return chart;
    }

    function buildTimeSeriesChart(labels, datasets, options) {
        options = options || {};
        return {
            type: options.chartType || 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 0 },
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: datasets.length > 1,
                        position: 'top',
                        labels: {
                            color: '#dbeafe',
                            usePointStyle: true,
                            boxWidth: 10,
                            boxHeight: 10,
                            padding: 16
                        }
                    },
                    tooltip: {
                        enabled: true,
                        backgroundColor: 'rgba(7, 17, 32, 0.96)',
                        titleColor: '#f8fbff',
                        bodyColor: '#dbeafe',
                        borderColor: 'rgba(84,168,255,0.4)',
                        borderWidth: 1,
                        padding: 10
                    }
                },
                scales: {
                    y: {
                        beginAtZero: options.beginAtZero || false,
                        grid: { color: 'rgba(148, 163, 184, 0.12)', drawBorder: false },
                        ticks: { color: '#a8bfd8' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#a8bfd8' }
                    }
                }
            }
        };
    }

    function buildBarChart(labels, datasets, options) {
        options = options || {};
        return {
            type: 'bar',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 0 },
                plugins: {
                    legend: {
                        display: datasets.length > 1,
                        position: 'top',
                        labels: {
                            color: '#dbeafe',
                            usePointStyle: true,
                            boxWidth: 10,
                            boxHeight: 10,
                            padding: 16
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: options.beginAtZero !== false,
                        grid: { color: 'rgba(148, 163, 184, 0.12)', drawBorder: false },
                        ticks: { color: '#a8bfd8' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#a8bfd8' }
                    }
                }
            }
        };
    }

    function buildRadarChart(labels, datasets) {
        return {
            type: 'radar',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'top' } },
                scales: { r: { beginAtZero: true } }
            }
        };
    }

    function buildPolarAreaChart(labels, data, colors) {
        return {
            type: 'polarArea',
            data: {
                labels: labels,
                datasets: [{ data: data, backgroundColor: colors || labels.map(function(_, i) {
                    return 'rgba(' + (50 + i * 30) + ',' + (100 + i * 20) + ',' + (150 + i * 15) + ',0.7)';
                })}]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } }
            }
        };
    }

    function buildDoughnutChart(labels, data, colors) {
        return {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{ data: data, backgroundColor: colors || ['#10b981','#f59e0b','#f97316','#ef4444','#3b82f6'], borderWidth: 0 }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } },
                cutout: '65%'
            }
        };
    }

    function seriesMax(values) {
        var mx = 0;
        for (var i = 0; i < values.length; i++) {
            var n = values[i];
            if (n !== null && n !== undefined && !isNaN(n)) {
                var a = Math.abs(n);
                if (a > mx) mx = a;
            }
        }
        return mx;
    }

    function planAxes(variables, seriesMap) {
        // Group variables whose value ranges are within ~20x of each other so
        // they can share one Y axis. Wildly different scales (e.g. pressure
        // ~1000 vs UV index ~5) get separate axes instead of flattening the
        // smaller series into an invisible line at zero.
        var plan = { multi: false, axisFor: {}, axes: [] };
        if (variables.length === 1) {
            plan.axisFor[variables[0]] = 'y';
            return plan;
        }
        var groups = [];
        variables.forEach(function(v) {
            var mx = seriesMax(seriesMap[v]) || 1;
            var placed = false;
            for (var g = 0; g < groups.length; g++) {
                var hi = Math.max(groups[g].max, mx);
                var lo = Math.min(groups[g].max, mx);
                if (lo > 0 && hi / lo <= 20) {
                    groups[g].max = hi;
                    groups[g].vars.push(v);
                    placed = true;
                    break;
                }
            }
            if (!placed) groups.push({ max: mx, vars: [v] });
        });
        if (groups.length < 2) {
            variables.forEach(function(v) { plan.axisFor[v] = 'y'; });
            return plan;
        }
        // Keep the chart readable: at most 4 axes, merge overflow groups
        while (groups.length > 4) {
            var mergeAt = groups.length - 2;
            groups[mergeAt].vars = groups[mergeAt].vars.concat(groups[mergeAt + 1].vars);
            groups[mergeAt].max = Math.max(groups[mergeAt].max, groups[mergeAt + 1].max);
            groups.splice(mergeAt + 1, 1);
        }
        plan.multi = true;
        groups.forEach(function(grp, gi) {
            var axisId = gi === 0 ? 'y' : 'y' + gi;
            grp.vars.forEach(function(v) { plan.axisFor[v] = axisId; });
            plan.axes.push({
                id: axisId,
                title: grp.vars.map(function(v) { return getLabel(v); }).join(' / ')
            });
        });
        return plan;
    }

    function renderFromAPI(canvasId, apiUrl, variables, chartType) {
        chartType = chartType || 'line';
        fetch(apiUrl)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || data.length === 0) {
                    drawMessage(canvasId, 'No data available for the selected filters');
                    return;
                }
                var labels = data.map(function(d) { return d.period; });
                var seriesMap = {};
                variables.forEach(function(v) {
                    seriesMap[v] = data.map(function(d) {
                        return d[v] !== null && d[v] !== undefined ? Math.round(d[v] * 10) / 10 : null;
                    });
                });
                var axisPlan = chartType === 'radar'
                    ? { multi: false, axisFor: {}, axes: [] }
                    : planAxes(variables, seriesMap);
                var datasets = variables.map(function(v) {
                    var ds = {
                        label: getLabel(v),
                        data: seriesMap[v],
                        borderColor: getColor(v),
                        backgroundColor: chartType === 'bar' ? getColor(v) + '99' : getColor(v) + '1a',
                        fill: chartType === 'line' || chartType === 'area',
                        tension: 0.4,
                        pointRadius: 3,
                        spanGaps: true
                    };
                    if (chartType === 'stepped') { ds.stepped = true; ds.tension = 0; }
                    if (axisPlan.multi) {
                        ds.yAxisID = axisPlan.axisFor[v] || 'y';
                    }
                    return ds;
                });
                var config;
                if (chartType === 'bar') {
                    config = buildBarChart(labels, datasets);
                } else if (chartType === 'radar') {
                    config = buildRadarChart(labels, datasets);
                } else {
                    config = buildTimeSeriesChart(labels, datasets);
                }
                if (axisPlan.multi) {
                    config.options.scales.y.title = { display: true, text: axisPlan.axes[0].title };
                    for (var ai = 1; ai < axisPlan.axes.length; ai++) {
                        config.options.scales[axisPlan.axes[ai].id] = {
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: axisPlan.axes[ai].title }
                        };
                    }
                }
                createChart(canvasId, config);
            })
            .catch(function(err) {
                console.error('Chart data fetch error:', err);
                drawMessage(canvasId, 'Failed to load chart data');
            });
    }

    function renderMonthly(canvasId, monthlyData, variables, chartType) {
        // Renders server-side monthly trend payloads ({labels, temperatures,
        // rainfall, humidity, wind_speed, ...}) with the same multi-axis and
        // gap-spanning treatment as renderFromAPI.
        chartType = chartType || 'line';
        var labels = (monthlyData && monthlyData.labels) || [];
        if (labels.length === 0) {
            drawMessage(canvasId, 'No data available for the selected filters');
            return;
        }
        var seriesMap = {};
        var usable = [];
        variables.forEach(function(v) {
            var key = v === 'temperature' ? 'temperatures' : v;
            var arr = monthlyData[key] || [];
            var hasValue = false;
            for (var i = 0; i < arr.length; i++) {
                if (arr[i] !== null && arr[i] !== undefined) { hasValue = true; break; }
            }
            if (hasValue) {
                seriesMap[v] = arr;
                usable.push(v);
            }
        });
        if (usable.length === 0) {
            drawMessage(canvasId, 'No data recorded for the selected variables in this dataset');
            return;
        }
        var axisPlan = chartType === 'radar'
            ? { multi: false, axisFor: {}, axes: [] }
            : planAxes(usable, seriesMap);
        var datasets = usable.map(function(v) {
            var ds = {
                label: getLabel(v),
                data: seriesMap[v],
                borderColor: getColor(v),
                backgroundColor: chartType === 'bar' ? getColor(v) + '99' : getColor(v) + '1a',
                fill: chartType === 'line' || chartType === 'area',
                tension: 0.4,
                pointRadius: 3,
                spanGaps: true
            };
            if (chartType === 'stepped') { ds.stepped = true; ds.tension = 0; }
            if (axisPlan.multi) {
                ds.yAxisID = axisPlan.axisFor[v] || 'y';
            }
            return ds;
        });
        var config;
        if (chartType === 'bar') {
            config = buildBarChart(labels, datasets);
        } else if (chartType === 'radar') {
            config = buildRadarChart(labels, datasets);
        } else {
            config = buildTimeSeriesChart(labels, datasets);
        }
        if (axisPlan.multi) {
            config.options.scales.y.title = { display: true, text: axisPlan.axes[0].title };
            for (var ai = 1; ai < axisPlan.axes.length; ai++) {
                config.options.scales[axisPlan.axes[ai].id] = {
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: axisPlan.axes[ai].title }
                };
            }
        }
        createChart(canvasId, config);
    }

    function renderRegionalChart(canvasId, regionalData, variable, chartType) {
        if (!regionalData || regionalData.length === 0) {
            drawMessage(canvasId, 'No regional data available');
            return;
        }
        var labels = regionalData.map(function(d) { return d.station_name; });
        var key = variable || 'avg_temp';
        var data = regionalData.map(function(d) { return d[key] !== null ? Math.round(d[key] * 10) / 10 : 0; });
        var colors = labels.map(function(_, i) {
            return 'rgba(' + (13 + i * 25) + ',' + (148 - i * 10) + ',' + (136 + i * 15) + ',0.7)';
        });
        var config;
        if (chartType === 'radar') {
            config = buildRadarChart(labels, [{
                label: getLabel(key),
                data: data,
                borderColor: getColor(key),
                backgroundColor: getColor(key) + '33',
                pointBackgroundColor: getColor(key)
            }]);
        } else if (chartType === 'polarArea') {
            config = buildPolarAreaChart(labels, data, colors);
        } else {
            config = buildBarChart(labels, [{
                label: getLabel(key),
                data: data,
                backgroundColor: colors,
                borderColor: colors.map(function(c) { return c.replace('0.7', '1'); }),
                borderWidth: 1,
                borderRadius: 6
            }]);
        }
        createChart(canvasId, config);
    }

    function renderAnomalyChart(canvasId, anomalyData) {
        if (!anomalyData || anomalyData.length === 0) {
            drawMessage(canvasId, 'No anomalies detected at this threshold');
            return;
        }
        var labels = anomalyData.map(function(a) { return (a.date || a.timestamp || '').substring(0, 10); });
        var config = {
            type: 'scatter',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Temp Z-Score',
                        data: anomalyData.map(function(a) { return { x: labels.indexOf((a.date || a.timestamp || '').substring(0, 10)), y: a.temp_z_score || 0 }; }),
                        backgroundColor: '#ef4444',
                        pointRadius: 6
                    },
                    {
                        label: 'Rain Z-Score',
                        data: anomalyData.map(function(a) { return { x: labels.indexOf((a.date || a.timestamp || '').substring(0, 10)), y: a.rain_z_score || 0 }; }),
                        backgroundColor: '#3b82f6',
                        pointRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'top' } },
                scales: {
                    y: { title: { display: true, text: 'Z-Score' }, grid: { color: 'rgba(0,0,0,0.05)' } },
                    x: { title: { display: true, text: 'Date' }, grid: { display: false } }
                }
            }
        };
        createChart(canvasId, config);
    }

    // Prediction results are stored as JSON strings with keys that vary by
    // model path ('predicted_avg_temp' / 'predicted_temperature' etc.).
    // These helpers normalize every stored shape into plain values.
    function parsePrediction(p) {
        try {
            var result = typeof p.prediction_result === 'string' ? JSON.parse(p.prediction_result) : p.prediction_result;
            return (result && typeof result === 'object') ? result : null;
        } catch (e) { return null; }
    }

    function predLabel(p) {
        return p.created_at ? String(p.created_at).substring(0, 10) : 'P' + p.id;
    }

    // Live forecast entries are recomputed server-side from the latest data,
    // so they always take priority over stored ML snapshots when present.
    function liveToPreds(liveForecast, key) {
        var out = [];
        (liveForecast || []).forEach(function(f) {
            var v = f ? f[key] : undefined;
            if (v !== undefined && v !== null && !isNaN(parseFloat(v))) {
                out.push({ label: f.period, value: Math.round(parseFloat(v) * 10) / 10, confidence: 0.8 });
            }
        });
        return out;
    }

    function extractTempPredictions(predictions, liveForecast) {
        var live = liveToPreds(liveForecast, 'predicted_avg_temp');
        if (live.length > 0) return live;
        var out = [];
        (predictions || []).forEach(function(p) {
            var result = parsePrediction(p);
            if (!result) return;
            var value = result.predicted_avg_temp !== undefined ? result.predicted_avg_temp
                      : (result.predicted_temperature !== undefined ? result.predicted_temperature
                      : (result.unit === '°C' ? result.predicted_value : undefined));
            if (value !== undefined && value !== null && !isNaN(parseFloat(value))) {
                out.push({ label: predLabel(p), value: Math.round(parseFloat(value) * 10) / 10, confidence: p.confidence || 0 });
            }
        });
        return out;
    }

    function extractRainPredictions(predictions, liveForecast) {
        var live = liveToPreds(liveForecast, 'predicted_rainfall_mm');
        if (live.length > 0) return live;
        var out = [];
        (predictions || []).forEach(function(p) {
            var result = parsePrediction(p);
            if (!result) return;
            var value = result.predicted_rainfall_mm !== undefined ? result.predicted_rainfall_mm
                      : (result.predicted_rainfall !== undefined ? result.predicted_rainfall : undefined);
            if (value !== undefined && value !== null) {
                out.push({ label: predLabel(p), value: Math.round(parseFloat(value) * 10) / 10, confidence: p.confidence || 0 });
            }
        });
        return out;
    }

    function renderForecastChart(canvasId, historical, predictions, liveForecast) {
        if (!historical || historical.length === 0) {
            drawMessage(canvasId, 'No historical data available');
            return;
        }
        var labels = historical.map(function(h) { return h.period; });
        var tempData = historical.map(function(h) { return h.avg_temp !== null ? Math.round(h.avg_temp * 10) / 10 : null; });
        var rainData = historical.map(function(h) { return h.total_rainfall !== null ? Math.round(h.total_rainfall * 10) / 10 : null; });
        var forecastTemps = extractTempPredictions(predictions, liveForecast);
        var allLabels = labels.slice();
        forecastTemps.forEach(function(f) { if (allLabels.indexOf(f.label) === -1) allLabels.push(f.label); });
        var forecastTempLine = new Array(allLabels.length).fill(null);
        forecastTemps.forEach(function(f) {
            var idx = allLabels.indexOf(f.label);
            if (idx >= 0) forecastTempLine[idx] = f.value;
        });
        // Anchor the dashed forecast line at the last actual reading so it
        // visually continues from the historical series.
        if (forecastTemps.length > 0) {
            for (var i = tempData.length - 1; i >= 0; i--) {
                if (tempData[i] !== null) { forecastTempLine[i] = tempData[i]; break; }
            }
        }
        var datasets = [
            { label: 'Historical Temp (°C)', data: tempData.concat(new Array(allLabels.length - tempData.length).fill(null)), borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)', fill: false, tension: 0.4 },
            { label: 'Historical Rainfall (mm)', data: rainData.concat(new Array(allLabels.length - rainData.length).fill(null)), borderColor: '#0d9488', backgroundColor: 'rgba(13,148,136,0.1)', fill: false, tension: 0.4 },
            { label: 'Forecast Temp (°C)', data: forecastTempLine, borderColor: '#ef4444', borderDash: [5, 5], backgroundColor: 'transparent', fill: false, tension: 0.4, pointStyle: 'triangle', pointRadius: 6 }
        ];
        var config = buildTimeSeriesChart(allLabels, datasets);
        createChart(canvasId, config);
    }

    function exportChart(canvasId, filename) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var link = document.createElement('a');
        link.download = filename || 'chart-' + Date.now() + '.png';
        link.href = canvas.toDataURL('image/png');
        link.click();
    }

    function getChart(canvasId) {
        return instances[canvasId] || null;
    }

    function destroyChart(canvasId) {
        if (instances[canvasId]) {
            instances[canvasId].destroy();
            delete instances[canvasId];
        }
    }

    return {
        create: createChart,
        timeSeries: buildTimeSeriesChart,
        bar: buildBarChart,
        radar: buildRadarChart,
        polarArea: buildPolarAreaChart,
        doughnut: buildDoughnutChart,
        renderFromAPI: renderFromAPI,
        renderMonthly: renderMonthly,
        renderRegional: renderRegionalChart,
        renderAnomaly: renderAnomalyChart,
        renderForecast: renderForecastChart,
        forecastTemps: extractTempPredictions,
        forecastRains: extractRainPredictions,
        export: exportChart,
        message: drawMessage,
        get: getChart,
        destroy: destroyChart,
        getColor: getColor,
        getLabel: getLabel,
        COLORS: COLORS,
        LABELS: LABELS
    };
})();
