(function () {
    function startCityScan() {
        var canvas = document.getElementById('cityScanCanvas');
        var cfg = document.getElementById('analyticsCfg');
        if (!canvas || !cfg || !window.THREE) return;

        var radarCard = canvas.closest('.city-scan');
        var fullscreenButton = radarCard ? radarCard.querySelector('.city-scan-fullscreen-btn') : null;
        var stateUrl = cfg.getAttribute('data-state-url');

        if (fullscreenButton) {
            fullscreenButton.addEventListener('click', function () {
                if (!document.fullscreenElement) {
                    if (radarCard.requestFullscreen) {
                        radarCard.requestFullscreen();
                    }
                } else if (document.exitFullscreen) {
                    document.exitFullscreen();
                }
            });
            document.addEventListener('fullscreenchange', function () {
                var isFullscreen = !!document.fullscreenElement && document.fullscreenElement === radarCard;
                radarCard.classList.toggle('is-fullscreen', isFullscreen);
                var icon = fullscreenButton.querySelector('i');
                if (!icon) return;
                icon.classList.toggle('fa-expand', !isFullscreen);
                icon.classList.toggle('fa-compress', isFullscreen);
                fullscreenButton.setAttribute('aria-label', isFullscreen ? 'Exit full screen' : 'Open full screen');
                fullscreenButton.title = isFullscreen ? 'Exit full screen' : 'Open full screen';
            });
        }
        var scene = new THREE.Scene();
        scene.fog = new THREE.Fog(0x07131d, 18, 52);
        var initialWidth = canvas.clientWidth || 640;
        var initialHeight = canvas.clientHeight || 390;
        var camera = new THREE.PerspectiveCamera(42, initialWidth / initialHeight, 0.1, 100);
        camera.position.set(0, 1.4, 10.5);
        camera.lookAt(0, 0, 0);
        var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
        renderer.setSize(initialWidth, initialHeight, false);
        renderer.setClearColor(0x020d17, 1);
        renderer.outputColorSpace = THREE.SRGBColorSpace;

        var globe = new THREE.Group();
        globe.rotation.set(0.25, -0.2, 0);
        globe.position.y = 0.2;
        scene.add(globe);
        var group = new THREE.Group();
        globe.add(group);
        var hitTargets = [];
        var raycaster = new THREE.Raycaster();
        var pointer = new THREE.Vector2();
        var dragging = false;
        var lastPointer = { x: 0, y: 0 };
        var rotationVelocity = 0.08;
        var latestState = { stations: [], anomalies: [] };
        var metricLabels = {
            temperature: 'Temperature', rainfall: 'Rainfall', humidity: 'Humidity',
            wind_speed: 'Wind speed', pressure: 'Pressure', co2_level: 'CO2',
            air_quality_index: 'Air quality'
        };
        scene.add(new THREE.HemisphereLight(0x7ee7d0, 0x06101a, 1.2));
        var key = new THREE.DirectionalLight(0x54a8ff, 1.5);
        key.position.set(5, 12, 8);
        scene.add(key);

        var earthMaterial = new THREE.MeshStandardMaterial({
            color: 0x2d7e9f, emissive: 0x06202d, emissiveIntensity: 0.7, roughness: 0.82, metalness: 0.12
        });
        var earth = new THREE.Mesh(new THREE.SphereGeometry(3.6, 72, 42), earthMaterial);
        globe.add(earth);
        var glowShell = new THREE.Mesh(
            new THREE.SphereGeometry(3.5, 48, 32),
            new THREE.MeshBasicMaterial({ color: 0x6ec6ff, transparent: true, opacity: 0.12, side: THREE.BackSide })
        );
        globe.add(glowShell);
        var textureLoader = new THREE.TextureLoader();
        textureLoader.setCrossOrigin('anonymous');
        textureLoader.load(
            'https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg',
            function (texture) {
                earthMaterial.map = texture;
                earthMaterial.color.set(0xffffff);
                earthMaterial.needsUpdate = true;
            },
            undefined,
            function () {
                earthMaterial.color.set(0x17627b);
                earthMaterial.needsUpdate = true;
            }
        );
        var cloudMaterial = new THREE.MeshBasicMaterial({
            color: 0xffffff, transparent: true, opacity: 0.22, depthWrite: false
        });
        var cloudLayer = new THREE.Mesh(new THREE.SphereGeometry(3.3, 48, 30), cloudMaterial);
        globe.add(cloudLayer);
        var wire = new THREE.Mesh(new THREE.SphereGeometry(3.23, 28, 18), new THREE.MeshBasicMaterial({
            color: 0x54a8ff, wireframe: true, transparent: true, opacity: 0.18
        }));
        globe.add(wire);
        var atmosphere = new THREE.Mesh(new THREE.SphereGeometry(3.42, 48, 28), new THREE.MeshBasicMaterial({
            color: 0x54a8ff, transparent: true, opacity: 0.12, side: THREE.BackSide
        }));
        globe.add(atmosphere);
        var sweep = new THREE.Mesh(new THREE.RingGeometry(3.44, 3.6, 120), new THREE.MeshBasicMaterial({
            color: 0x7ee7d0, transparent: true, opacity: 0.54, side: THREE.DoubleSide
        }));
        sweep.rotation.x = Math.PI / 2;
        globe.add(sweep);

        function buildLabelTexture(text, flagged) {
            var safeText = String(text || 'Unknown');
            var compactText = safeText.length > 16 ? safeText.slice(0, 16) + '…' : safeText;
            var width = Math.max(120, Math.min(220, compactText.length * 10 + 30));
            var height = 34;
            var canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            var ctx = canvas.getContext('2d');
            var inset = 4;
            ctx.clearRect(0, 0, width, height);
            ctx.shadowColor = flagged ? 'rgba(251, 113, 133, 0.8)' : 'rgba(110, 198, 255, 0.8)';
            ctx.shadowBlur = 10;
            ctx.fillStyle = 'rgba(11, 30, 40, 0.7)';
            drawRoundedRect(ctx, inset, inset, width - inset * 2, height - inset * 2, 10);
            ctx.fill();
            ctx.lineWidth = 1.2;
            ctx.strokeStyle = flagged ? 'rgba(251, 113, 133, 0.8)' : 'rgba(126, 231, 208, 0.85)';
            ctx.stroke();
            ctx.shadowBlur = 0;
            ctx.fillStyle = flagged ? '#ffe0e6' : '#dffcf6';
            ctx.font = '700 13px Arial';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(compactText, width / 2, height / 2 + 1);
            var texture = new THREE.CanvasTexture(canvas);
            texture.needsUpdate = true;
            return texture;
        }

        function drawRoundedRect(context, x, y, width, height, radius) {
            context.beginPath();
            context.moveTo(x + radius, y);
            context.lineTo(x + width - radius, y);
            context.quadraticCurveTo(x + width, y, x + width, y + radius);
            context.lineTo(x + width, y + height - radius);
            context.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
            context.lineTo(x + radius, y + height);
            context.quadraticCurveTo(x, y + height, x, y + height - radius);
            context.lineTo(x, y + radius);
            context.quadraticCurveTo(x, y, x + radius, y);
            context.closePath();
        }

        function rebuild(stations, anomalies, selectedMetric) {
            while (group.children.length) group.remove(group.children[0]);
            hitTargets = [];
            var metric = selectedMetric || (document.getElementById('cityScanMetricSelect') || {}).value || '';
            var points = Array.isArray(stations) ? stations : [];
            var anomalyNames = {};
            (anomalies || []).forEach(function (a) { anomalyNames[a.station_name] = true; });

            if (!metric) {
                var count = document.getElementById('cityScanCount');
                if (count) count.textContent = '0';
                var anomaliesCount = document.getElementById('cityScanAnomalies');
                if (anomaliesCount) anomaliesCount.textContent = '0';
                var status = document.getElementById('cityScanStatus');
                if (status) status.textContent = 'READY';
                var metricEl = document.getElementById('cityScanMetric');
                if (metricEl) metricEl.textContent = 'Select metric';
                var detail = document.getElementById('cityScanDetail');
                if (detail) {
                    detail.innerHTML = '<div class="city-scan-detail-empty"><i class="fas fa-globe-americas"></i><span>Choose a climate metric to load the 3D city scan.</span></div>';
                }
                return;
            }

            var prioritized = [];
            var normal = [];
            points.forEach(function (station) {
                var value = Number(station[metric]);
                if (!Number.isFinite(value)) return;
                var record = { station: station, value: value, flagged: !!anomalyNames[station.station_name] };
                if (record.flagged) prioritized.push(record); else normal.push(record);
            });
            prioritized.sort(function (a, b) { return b.value - a.value; });
            normal.sort(function (a, b) { return b.value - a.value; });
            var filtered = prioritized.concat(normal).slice(0, 12);

            filtered.forEach(function (item, index) {
                var station = item.station;
                var latitude = Number(station.latitude) || 0;
                var longitude = Number(station.longitude) || 0;
                var phi = (90 - latitude) * Math.PI / 180;
                var theta = (longitude + 180) * Math.PI / 180;
                var surface = new THREE.Vector3(
                    -3.25 * Math.sin(phi) * Math.cos(theta),
                    3.25 * Math.cos(phi),
                    3.25 * Math.sin(phi) * Math.sin(theta)
                );
                var rawValue = Number(station[metric]);
                var normalized = metric === 'temperature' ? (rawValue + 20) / 18 :
                    metric === 'pressure' ? (rawValue - 950) / 35 :
                    metric === 'rainfall' ? (rawValue + 3) / 18 :
                    metric === 'humidity' ? rawValue / 55 :
                    metric === 'wind_speed' ? rawValue / 30 :
                    metric === 'co2_level' ? rawValue / 700 :
                    metric === 'air_quality_index' ? rawValue / 100 :
                    metric === 'visibility' ? rawValue / 12 :
                    metric === 'uv_index' ? rawValue / 4 :
                    metric === 'soil_moisture' ? rawValue / 40 : rawValue / 20;
                var height = 0.8 + (Number.isFinite(normalized) ? normalized : 1.2);
                height = Math.max(0.9, Math.min(6.8, height));
                var flagged = !!anomalyNames[station.station_name];
                var glowColor = flagged ? 0xfb7185 : (metric === 'temperature' ? 0x7cc9ff : 0x7ee7d0);
                var material = new THREE.MeshStandardMaterial({
                    color: flagged ? 0xfb7185 : (metric === 'temperature' ? 0x60b4ff : 0x7ee7d0),
                    emissive: flagged ? 0x7f1d35 : 0x0c4d78,
                    emissiveIntensity: flagged ? 0.9 : 0.7,
                    metalness: 0.6,
                    roughness: 0.26
                });
                var building = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.17, height, 10), material);
                building.position.copy(surface.clone().normalize().multiplyScalar(3.25 + height / 2));
                building.castShadow = false;
                building.receiveShadow = false;
                group.add(building);

                var lineMaterial = new THREE.LineBasicMaterial({
                    color: glowColor,
                    transparent: true,
                    opacity: 0.7,
                    linewidth: 1
                });
                var connector = new THREE.Line(
                    new THREE.BufferGeometry().setFromPoints([
                        surface.clone().multiplyScalar(1.02),
                        surface.clone().normalize().multiplyScalar(3.25 + height * 0.7)
                    ]),
                    lineMaterial
                );
                group.add(connector);

                var beacon = new THREE.Mesh(
                    new THREE.SphereGeometry(flagged ? 0.15 : 0.09, 14, 10),
                    new THREE.MeshBasicMaterial({ color: glowColor, transparent: true, opacity: 0.98 })
                );
                beacon.position.copy(surface.clone().normalize().multiplyScalar(3.34 + height));
                beacon.userData.station = station;
                beacon.userData.flagged = flagged;
                group.add(beacon);
                hitTargets.push(beacon);

                var labelTexture = buildLabelTexture(station.station_name || 'Unknown', flagged);
                var label = new THREE.Sprite(new THREE.SpriteMaterial({
                    map: labelTexture,
                    transparent: true,
                    depthTest: false,
                    depthWrite: false,
                    opacity: 1,
                }));
                var normal = surface.clone().normalize();
                var tangent = new THREE.Vector3(0, 1, 0).cross(normal).normalize();
                if (tangent.lengthSq() < 0.0001) {
                    tangent.set(1, 0, 0);
                }
                var lateralShift = (index % 5 - 2) * 0.28;
                var spread = (index % 3) * 0.18;
                label.position.copy(normal.clone().multiplyScalar(3.75 + height * 0.7 + spread).add(tangent.clone().multiplyScalar(lateralShift)));
                label.scale.set(labelTexture.image.width / 55, labelTexture.image.height / 28, 1);
                group.add(label);
            });
            var count = document.getElementById('cityScanCount');
            if (count) count.textContent = String(filtered.length);
            var anomaliesCount = document.getElementById('cityScanAnomalies');
            if (anomaliesCount) anomaliesCount.textContent = String(filtered.filter(function (item) { return item.flagged; }).length);
            var status = document.getElementById('cityScanStatus');
            if (status) status.textContent = (metricLabels[metric] || metric).toUpperCase();
            var metricEl = document.getElementById('cityScanMetric');
            if (metricEl) metricEl.textContent = metricLabels[metric] || metric;
        }

        var params = new URLSearchParams();
        var start = document.getElementById('startDate');
        var end = document.getElementById('endDate');
        var region = document.getElementById('regionSelect');
        if (start && start.value) params.set('start_date', start.value);
        if (end && end.value) params.set('end_date', end.value);
        if (region && region.value) params.set('region', region.value);
        fetch(stateUrl + '?' + params.toString()).then(function (response) { return response.json(); }).then(function (state) {
            latestState = state;
            var cityScanSelect = document.getElementById('cityScanMetricSelect');
            rebuild(state.stations || [], state.anomalies || [], cityScanSelect ? cityScanSelect.value : '');
        }).catch(function () { rebuild([], [], ''); });

        function showDetails(station, flagged) {
            var detail = document.getElementById('cityScanDetail');
            if (!detail || !station) return;
            var stationName = String(station.station_name || 'Unknown station');
            var fallbackImage = 'https://images.unsplash.com/photo-1449824913935-59a10b8d2000?auto=format&fit=crop&w=640&q=75';
            function value(key, unit, digits) {
                var raw = Number(station[key]);
                return Number.isFinite(raw) ? raw.toFixed(digits || 1) + (unit || '') : 'N/A';
            }
            detail.innerHTML = '<img class="city-scan-image" src="' + fallbackImage + '" alt="City location" onerror="this.style.display=\'none\'">' +
                '<h4>' + stationName + '</h4>' +
                '<small>' + (flagged ? 'Priority signal' : 'Live station') + '</small>' +
                '<span class="city-scan-location">Locating city and country... · ' +
                value('latitude', '°', 2) + ', ' + value('longitude', '°', 2) + '</span>' +
                '<div class="city-scan-detail-grid">' +
                '<div><span>Temperature</span><strong>' + value('temperature', '°C') + '</strong></div>' +
                '<div><span>Humidity</span><strong>' + value('humidity', '%') + '</strong></div>' +
                '<div><span>Rainfall</span><strong>' + value('rainfall', ' mm') + '</strong></div>' +
                '<div><span>Air quality</span><strong>' + value('air_quality_index', '') + '</strong></div>' +
                '<div><span>Wind speed</span><strong>' + value('wind_speed', ' km/h') + '</strong></div>' +
                '<div><span>Reading date</span><strong>' + (station.date || 'N/A') + '</strong></div></div>';
            var locationEl = detail.querySelector('.city-scan-location');
            var imageEl = detail.querySelector('.city-scan-image');
            var lat = Number(station.latitude);
            var lon = Number(station.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
            fetch('https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=10&lat=' + lat + '&lon=' + lon)
                .then(function (response) { return response.ok ? response.json() : null; })
                .then(function (place) {
                    if (!place) return;
                    var address = place.address || {};
                    var city = address.city || address.town || address.village || address.municipality || stationName;
                    var country = address.country || 'Unknown country';
                    if (locationEl) locationEl.textContent = city + ', ' + country;
                    var query = encodeURIComponent(city + ' ' + country);
                    return fetch('https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=' + query + '&gsrnamespace=6&gsrlimit=1&prop=imageinfo&iiprop=url&iiurlwidth=640&format=json&origin=*');
                })
                .then(function (response) { return response && response.ok ? response.json() : null; })
                .then(function (images) {
                    var pages = images && images.query && images.query.pages;
                    var first = pages && pages[Object.keys(pages)[0]];
                    var imageUrl = first && first.imageinfo && first.imageinfo[0] && (first.imageinfo[0].thumburl || first.imageinfo[0].url);
                    if (imageUrl && imageEl) imageEl.src = imageUrl;
                })
                .catch(function () {
                    if (locationEl) locationEl.textContent = 'Coordinates: ' + lat.toFixed(2) + '°, ' + lon.toFixed(2) + '°';
                });
        }

        canvas.addEventListener('pointerdown', function (event) {
            dragging = true;
            lastPointer.x = event.clientX;
            lastPointer.y = event.clientY;
            canvas.setPointerCapture(event.pointerId);
        });
        canvas.addEventListener('pointermove', function (event) {
            if (!dragging) return;
            var horizontalDelta = event.clientX - lastPointer.x;
            globe.rotation.y += horizontalDelta * 0.008;
            rotationVelocity = horizontalDelta * 0.45;
            globe.rotation.x = Math.max(-0.55, Math.min(0.55, globe.rotation.x + (event.clientY - lastPointer.y) * 0.004));
            lastPointer.x = event.clientX;
            lastPointer.y = event.clientY;
        });
        canvas.addEventListener('pointerup', function (event) {
            dragging = false;
            canvas.releasePointerCapture(event.pointerId);
        });
        canvas.addEventListener('pointerleave', function () { dragging = false; });
        canvas.addEventListener('wheel', function (event) {
            event.preventDefault();
            camera.position.z = Math.max(5.3, Math.min(14, camera.position.z + event.deltaY * 0.006));
            camera.lookAt(0, 0, 0);
        }, { passive: false });
        canvas.addEventListener('click', function (event) {
            var rect = canvas.getBoundingClientRect();
            pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
            raycaster.setFromCamera(pointer, camera);
            var hits = raycaster.intersectObjects(hitTargets, false);
            if (hits.length) showDetails(hits[0].object.userData.station, hits[0].object.userData.flagged);
        });

        var metricSelect = document.getElementById('mapMetric');
        if (metricSelect) metricSelect.addEventListener('change', function () { rebuild(latestState.stations, latestState.anomalies, (document.getElementById('cityScanMetricSelect') || {}).value || ''); });

        var cityScanMetricSelect = document.getElementById('cityScanMetricSelect');
        if (cityScanMetricSelect) {
            cityScanMetricSelect.addEventListener('change', function () {
                rebuild(latestState.stations, latestState.anomalies, this.value || '');
            });
        }

        function resize() {
            var width = canvas.clientWidth || 640;
            var height = canvas.clientHeight || 360;
            camera.aspect = width / height;
            camera.updateProjectionMatrix();
            renderer.setSize(width, height, false);
        }
        window.addEventListener('resize', resize);
        if (window.ResizeObserver) new ResizeObserver(resize).observe(canvas.parentElement);
        var clock = new THREE.Clock();
        function animate() {
            requestAnimationFrame(animate);
            var elapsed = clock.getElapsedTime();
            if (!dragging) {
                rotationVelocity = rotationVelocity * 0.96 + 0.08 * 0.04;
                globe.rotation.y += rotationVelocity * 0.01;
            }
            cloudLayer.rotation.y += 0.00035;
            sweep.rotation.z = -elapsed * 0.65;
            renderer.render(scene, camera);
        }
        resize();
        animate();
    }

    function loadThree() {
        if (window.THREE) return startCityScan();
        var script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
        script.onload = startCityScan;
        script.onerror = function () {
            var empty = document.getElementById('cityScanStatus');
            if (empty) empty.textContent = '3D engine unavailable';
        };
        document.head.appendChild(script);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadThree);
    else loadThree();
})();
