const API = `http://${location.hostname}:8000`;
const CTR = [26.9124, 75.7873]; 

let map, mkr, pos = [...CTR], addrDone = false;
let jActive=false, destCoords=null, destMkr=null;
let rLayers=[], routes=[], rEvals=[], selR=0;

let CLOUD = localStorage.getItem('ss_cloud') || '';
let PRESET = localStorage.getItem('ss_preset') || '';

document.addEventListener('DOMContentLoaded', () => {
    initMap(); initGPS(); renderContacts(); checkBackend();
});

// --- API Sync Helpers ---
async function checkBackend() {
    try {
        const r = await fetch(`${API}/`);
        if (r.ok) document.getElementById('bdot').className = 'backend-dot ok';
    } catch { document.getElementById('bdot').className = 'backend-dot fail'; }
}

function initMap() {
    map = L.map('map', { zoomControl: false }).setView(CTR, 14);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
    mkr = L.marker(CTR).addTo(map);
}

function initGPS() {
    navigator.geolocation.watchPosition(p => {
        pos = [p.coords.latitude, p.coords.longitude];
        mkr.setLatLng(pos);
        fetch(`${API}/location`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: pos[0], longitude: pos[1] })
        }).catch(() => {});
    }, null, { enableHighAccuracy: true });
}

// --- Evidence Bridge ---
async function uploadAndSync(blob, type) {
    if (!CLOUD || !PRESET) return showToast("⚙️ Setup Cloudinary First");
    
    const fd = new FormData();
    fd.append('file', blob);
    fd.append('upload_preset', PRESET);

    try {
        const resp = await fetch(`https://api.cloudinary.com/v1_1/${CLOUD}/auto/upload`, { method: 'POST', body: fd });
        const data = await resp.json();
        
        await fetch(`${API}/evidence`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: data.secure_url,
                type: type,
                latitude: pos[0].toString(),
                longitude: pos[1].toString()
            })
        });
        showToast(" Evidence Secured");
    } catch (e) { showToast("Upload Failed"); }
}

// --- AI Safety Routing ---
async function findRoutes() {
    if (!destCoords) return showToast("Set a destination");
    rLayers.forEach(l => map.removeLayer(l));
    rLayers = [];

    showLoader("Analyzing Safe Routes...");
    const osrm = await fetch(`https://router.project-osrm.org/route/v1/driving/${pos[1]},${pos[0]};${destCoords.lng},${destCoords.lat}?overview=full&geometries=geojson&alternatives=true`);
    const data = await osrm.json();

    const aiRes = await fetch(`${API}/filter-routes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            routes: data.routes.map((r, i) => ({ index: i, distance: r.distance, time: r.duration }))
        })
    });
    const prediction = await aiRes.json();

    data.routes.forEach((rt, i) => {
        const ev = prediction.evaluations.find(e => e.index === i);
        const line = L.polyline(rt.geometry.coordinates.map(c => [c[1], c[0]]), {
            color: ev.color,
            weight: i === prediction.recommended_index ? 7 : 3,
            opacity: i === prediction.recommended_index ? 1 : 0.4
        }).addTo(map);
        rLayers.push(line);
    });
    hideLoader();
    document.getElementById('routeModal').classList.remove('hidden');
}

// --- SOS Package ---
async function triggerSOS() {
    try {
        const r = await fetch(`${API}/sos-package?lat=${pos[0]}&lng=${pos[1]}`);
        const pkg = await r.json();
        let msg = ` *EMERGENCY SOS* \n📍 Location: ${pkg.location.maps_link}\n`;
        if (pkg.evidence.length > 0) {
            msg += `\n📁 Evidence:\n` + pkg.evidence.map((e, i) => `${i+1}. ${e.url}`).join('\n');
        }
        window.open(`https://wa.me/${pkg.contacts[0]?.phone}?text=${encodeURIComponent(msg)}`, '_blank');
    } catch (e) { showToast("Check Backend Connection"); }
}

// --- UI Helpers ---
function showToast(m) { alert(m); }
function showLoader(t) { console.log(t); }
function hideLoader() { console.log("Done"); }