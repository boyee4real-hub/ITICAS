const DEFAULT_PERMS=["traffic:view","traffic:acquire","monitoring:view","locations:view","validation:view"];
async function loadUsers(){
  const r=await fetch("/api/admin/users");
  const box=document.getElementById("users");
  if(!r.ok){box.textContent="Unable to load users.";return;}
  const users=await r.json();
  box.innerHTML=users.map(u=>`<div class="user"><div><strong>${u.username}</strong><div class="muted">${u.email}</div></div><div>${u.role}</div><div>${u.status}</div><div>${u.is_primary_admin?"Primary administrator":"Granular permissions available through API/UI expansion"}</div><div>${u.status==="pending"?`<button class="approve" onclick="approve(${u.id})">Approve</button>`:""}</div></div>`).join("")||"<p class='muted'>No users.</p>";
}
async function approve(id){
  const r=await fetch(`/api/admin/users/${id}/approve`,{method:"POST"});
  if(!r.ok){alert("Approval failed.");return;}
  await fetch(`/api/admin/users/${id}/permissions`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(DEFAULT_PERMS)});
  loadUsers();
}
loadUsers();
