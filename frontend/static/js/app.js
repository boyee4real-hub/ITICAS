function updateClock(){
  const now = new Date();
  document.getElementById("clock").textContent =
    now.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
}

async function refreshSummary(){
  const button = document.querySelector(".primary-btn");
  const original = button.textContent;
  button.textContent = "Refreshing...";
  button.disabled = true;

  try{
    const res = await fetch("/api/dashboard/summary");
    if(!res.ok) throw new Error("Could not retrieve summary");
    const d = await res.json();
    document.getElementById("monitored").textContent = d.monitored_locations ?? 0;
    document.getElementById("free-flow").textContent = d.free_flow ?? 0;
    document.getElementById("moderate").textContent = d.moderate ?? 0;
    document.getElementById("heavy-severe").textContent = (d.heavy ?? 0) + (d.severe ?? 0);
    document.getElementById("data-status").textContent = d.data_status || "Ready";
    document.getElementById("network-status").textContent = "Ready";
  }catch(err){
    document.getElementById("network-status").textContent = "Check backend";
    document.getElementById("data-status").textContent = err.message;
  }finally{
    button.textContent = original;
    button.disabled = false;
  }
}

setInterval(updateClock, 1000);
updateClock();
refreshSummary();
