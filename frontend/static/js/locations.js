let allLocations = [];

function esc(value){
  return String(value ?? "").replace(/[&<>"']/g, s => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[s]));
}

async function loadLocations(){
  const r = await fetch("/api/locations");
  allLocations = await r.json();
  renderLocations();
  document.getElementById("totalCount").textContent = allLocations.length;
  document.getElementById("resolvedCount").textContent = allLocations.filter(x => x.latitude != null && x.longitude != null).length;
  document.getElementById("activeCount").textContent = allLocations.filter(x => x.active).length;
  document.getElementById("stateCount").textContent = new Set(allLocations.map(x => x.state).filter(Boolean)).size;
}

function renderLocations(){
  const q = document.getElementById("searchBox").value.trim().toLowerCase();
  const rows = allLocations.filter(x =>
    `${x.name} ${x.road_name || ""} ${x.city || ""} ${x.state || ""}`.toLowerCase().includes(q)
  );
  const box = document.getElementById("locationTable");
  if(!rows.length){
    box.innerHTML = `<div class="location-row"><div class="muted">No matching monitoring locations.</div></div>`;
    return;
  }
  box.innerHTML = rows.map(x => {
    const hasCoord = x.latitude != null && x.longitude != null;
    const coord = hasCoord ? `${Number(x.latitude).toFixed(5)}, ${Number(x.longitude).toFixed(5)}` : "Awaiting coordinate verification";
    const place = [x.city, x.state].filter(Boolean).join(", ") || "Location not classified";
    const source = x.geocode_source || "Pending";
    return `<div class="location-row">
      <div><div class="location-name">${esc(x.name)}</div><div class="location-road">${esc(x.road_name || "—")}</div></div>
      <div><div class="location-name">${esc(place)}</div><div class="location-road">${esc(x.country || "Nigeria")}</div></div>
      <div><div class="coordinate">${esc(coord)}</div><div class="location-road">${esc(source)}</div></div>
      <div><span class="badge ${hasCoord ? "" : "pending"}">${hasCoord ? "Resolved" : "Pending"}</span></div>
      <div class="location-road">${esc(x.radius_m)} m</div>
      <button class="delete-button" onclick="deleteLocation(${x.id}, '${esc(x.name).replace(/'/g, "\\'")}')">Delete</button>
    </div>`;
  }).join("");
}

async function deleteLocation(id, name){
  if(!confirm(`Delete ${name} from the monitoring catalogue?`)) return;
  const r = await fetch(`/api/locations/${id}`, {method:"DELETE"});
  if(r.ok) await loadLocations();
}

document.getElementById("searchBox").addEventListener("input", renderLocations);

document.getElementById("locationForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const lat = document.getElementById("latitude").value;
  const lon = document.getElementById("longitude").value;
  const payload = {
    name: document.getElementById("name").value,
    road_name: document.getElementById("roadName").value || null,
    city: document.getElementById("city").value || null,
    state: document.getElementById("state").value || null,
    country: "Nigeria",
    latitude: lat === "" ? null : Number(lat),
    longitude: lon === "" ? null : Number(lon),
    radius_m: Number(document.getElementById("radius").value),
    active: true
  };
  const r = await fetch("/api/locations", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });
  const out = await r.json();
  const msg = document.getElementById("formMessage");
  if(!r.ok){ msg.textContent = out.detail || "Could not add location."; return; }
  msg.textContent = `${out.name} added successfully.`;
  e.target.reset();
  document.getElementById("radius").value = "1000";
  await loadLocations();
});

loadLocations();
