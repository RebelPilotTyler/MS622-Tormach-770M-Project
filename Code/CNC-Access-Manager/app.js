/* =====================================================================
   CNC Access Manager — front-end (connected to the SQLite backend)
   ---------------------------------------------------------------------
   All user data now lives in cnc.db (SQLite) via server.py.
   Add / edit / delete / disable all write to the database and sync
   for anyone connecting to the same server.

   RUN:  python server.py   →   open http://localhost:8000
   Login: admin / admin
   Pages: 1 Login · 2 Users · 3 Add/Edit (modal) · 4 Logs · 5 Safety
   ===================================================================== */

const API = '';        // same origin (served by server.py). e.g. 'http://192.168.1.50:8000' for another PC
let TOKEN = null;      // set after login; sent on every write
let users = [];        // loaded from the server
let editingId = null;

/* ---- safety checklist stays client-side (a live gate, not stored) ---- */
const checklistItems = [
  { text: "Safety glasses on · no gloves · hair tied back", required: true },
  { text: "Correct bit loaded and tightened",              required: true },
  { text: "Speeds & feeds match the material",             required: true },
  { text: "Workpiece clamped securely",                    required: true },
  { text: "Tool probe / touch-off checked",                required: true },
  { text: "Work area clear · loose tools removed",         required: true },
  { text: "Simulation reviewed for errors (recommended)",  required: false },
];

/* ---------- tiny fetch helpers ---------- */
async function apiGet(path){
  const r = await fetch(API + path);
  if (!r.ok) throw new Error('GET ' + path + ' failed');
  return r.json();
}
async function apiSend(method, path, body){
  const r = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': TOKEN },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const msg = await r.json().catch(() => ({}));
    throw new Error(msg.error || (method + ' ' + path + ' failed'));
  }
  return r.json();
}

/* ================= PAGE 1: LOGIN ================= */
async function doLogin(e){
  e.preventDefault();
  const username = document.getElementById('l_user').value.trim();
  const password = document.getElementById('l_pass').value;
  try {
    const res = await fetch(API + '/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      TOKEN = data.token;
      document.getElementById('loginView').hidden = true;
      document.getElementById('appView').hidden = false;
      document.getElementById('loginError').hidden = true;
      await loadUsers();
      renderChecklist();
    } else {
      document.getElementById('loginError').hidden = false;
    }
  } catch (err) {
    document.getElementById('loginError').hidden = false;
    document.getElementById('loginError').textContent =
      'Cannot reach the server. Is server.py running?';
  }
}
function doLogout(){
  TOKEN = null;
  document.getElementById('appView').hidden = true;
  document.getElementById('loginView').hidden = false;
  document.getElementById('l_pass').value = '';
}

/* ================= NAV ================= */
function showPage(name){
  document.querySelectorAll('.page').forEach(p => p.hidden = true);
  document.getElementById('page-' + name).hidden = false;
  document.querySelectorAll('.tab').forEach(t =>
    t.classList.toggle('active', t.dataset.page === name));
  if (name === 'logs')   renderLogs();
  if (name === 'users')  loadUsers();
  if (name === 'system') renderSystem();
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ================= PAGE 2: USERS ================= */
async function loadUsers(){
  try { users = await apiGet('/api/users'); renderUsers(); }
  catch (e) { alert('Failed to load users: ' + e.message); }
}
function renderUsers(){
  const q = document.getElementById('search').value.trim().toLowerCase();
  const tbody = document.querySelector('#userTable tbody');
  const rows = users.filter(u =>
    u.name.toLowerCase().includes(q) || u.rfid_hex.toLowerCase().includes(q));

  tbody.innerHTML = rows.map(u => `
    <tr>
      <td>${escapeHtml(u.name)}</td>
      <td><code>${u.rfid_hex}</code></td>
      <td>${u.pin}</td>
      <td class="lvl-${u.cert_level}">${u.cert_level}</td>
      <td><span class="badge ${u.status}">${u.status}</span></td>
      <td class="actions">
        <button class="small" onclick="openForm(${u.id})">Edit</button>
        <button class="small" onclick="toggleStatus(${u.id})">${u.status === 'active' ? 'Disable' : 'Enable'}</button>
        <button class="small" onclick="deleteUser(${u.id})">Delete</button>
      </td>
    </tr>`).join('');

  document.getElementById('usersEmpty').hidden = rows.length !== 0;
  document.getElementById('userCount').textContent =
    `${users.length} users total (showing ${rows.length})`;
}
async function toggleStatus(id){
  const u = users.find(x => x.id === id);
  const updated = { ...u, status: u.status === 'active' ? 'disabled' : 'active' };
  try { await apiSend('PUT', '/api/users/' + id, updated); await loadUsers(); }
  catch (e) { alert('Update failed: ' + e.message); }
}
async function deleteUser(id){
  const u = users.find(x => x.id === id);
  if (!confirm(`Delete "${u.name}"?`)) return;
  try { await apiSend('DELETE', '/api/users/' + id); await loadUsers(); }
  catch (e) { alert('Delete failed: ' + e.message); }
}

/* ================= PAGE 3: ADD / EDIT (modal) ================= */
function openForm(id){
  editingId = (typeof id === 'number') ? id : null;
  const u = editingId ? users.find(x => x.id === editingId) : null;
  document.getElementById('formTitle').textContent = u ? 'Edit user' : 'Add user';
  document.getElementById('f_name').value   = u ? u.name : '';
  document.getElementById('f_rfid').value   = u ? u.rfid_hex : '';
  document.getElementById('f_pin').value    = u ? u.pin : '';
  document.getElementById('f_level').value  = u ? u.cert_level : 'A';
  document.getElementById('f_status').value = u ? u.status : 'active';
  document.getElementById('overlay').hidden = false;
}
function closeForm(){
  document.getElementById('overlay').hidden = true;
  editingId = null;
}
async function saveUser(e){
  e.preventDefault();
  const data = {
    name:       document.getElementById('f_name').value.trim(),
    rfid_hex:   document.getElementById('f_rfid').value.trim().toUpperCase(),
    pin:        document.getElementById('f_pin').value.trim(),
    cert_level: document.getElementById('f_level').value,
    status:     document.getElementById('f_status').value,
  };
  try {
    if (editingId) await apiSend('PUT', '/api/users/' + editingId, data);
    else           await apiSend('POST', '/api/users', data);
    closeForm();
    await loadUsers();
  } catch (err) {
    alert('Save failed: ' + err.message);   // e.g. duplicate card number
  }
}
/* Real enrollment: the reader (Pico in enroll mode) POSTs the scanned UID to
   /api/scan; this button pulls the card tapped *after* it was pressed. No reader
   connected → tells you to type it manually (never fabricates a fake ID). */
async function scanCard(){
  const hint = document.getElementById('scanHint');
  const t0 = Date.now();
  hint.textContent = 'Waiting for a card tap on the reader…';
  for (let i = 0; i < 20; i++) {          // poll ~12s
    try {
      const d = await apiGet('/api/last-scan');
      // accept only a scan that happened after this button was pressed
      if (d.uid && d.age != null && d.age <= (Date.now() - t0) / 1000 + 1) {
        document.getElementById('f_rfid').value = d.uid;
        hint.textContent = 'Card read: ' + d.uid;
        return;
      }
    } catch (e) { /* keep polling */ }
    await sleep(600);
  }
  hint.textContent = 'No card detected from a reader. Type the card ID manually ' +
                     '(or run enroll mode on the Pico — see INTEGRATION.md).';
}

/* ================= PAGE 6: SYSTEM / STATUS + UPDATES ================= */
async function renderSystem(){
  const cards = document.getElementById('statusCards');
  const log   = document.getElementById('changelog');
  let s;
  try { s = await apiGet('/api/system'); }
  catch (e) {
    cards.innerHTML = statusCard('Server', 'down', 'Cannot reach server.py');
    return;
  }
  const scan = (s.last_scan_age == null)
    ? statusCard('Card reader', 'unknown', 'No card seen yet — reader not confirmed / no hardware')
    : statusCard('Card reader', 'ok', 'Last card scanned ' + s.last_scan_age + 's ago');
  cards.innerHTML =
      statusCard('Server (server.py)', 'ok', 'Reachable · API v' + s.version)
    + statusCard('Database (cnc.db)', 'ok', s.users + ' users · ' + s.active_users + ' active')
    + statusCard('Live sessions', s.open_sessions ? 'ok' : 'idle',
                 s.open_sessions + ' machine session(s) open')
    + scan;

  log.innerHTML = s.changelog.map(v => `
    <div class="rel">
      <div class="rel-head"><strong>v${v.version}</strong> <span class="muted">${v.date}</span></div>
      <ul>${v.items.map(it => '<li>' + escapeHtml(it) + '</li>').join('')}</ul>
    </div>`).join('');
}
/* Testing helper: feed the enrollment channel without a real reader.
   Sends a UID to /api/scan so the Add-user "Scan" button can pull it. */
async function simulateTap(){
  const uid = document.getElementById('simUid').value.trim().toUpperCase();
  const msg = document.getElementById('simMsg');
  try {
    await fetch(API + '/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Device-Key': 'pico-770' },
      body: JSON.stringify({ uid }),
    });
    msg.textContent = 'Sent ' + uid + ' — now open Add user and press Scan within ~12 s.';
    renderSystem();
  } catch (e) {
    msg.textContent = 'Failed: ' + e.message;
  }
}
function statusCard(title, state, detail){
  return `<div class="scard ${state}">
    <div class="scard-dot"></div>
    <div><div class="scard-title">${escapeHtml(title)}</div>
    <div class="scard-detail">${escapeHtml(detail)}</div></div></div>`;
}

/* ================= PAGE 4: LOGS ================= */
async function renderLogs(){
  let data;
  try { data = await apiGet('/api/logs'); }
  catch (e) { return; }

  document.querySelector('#accessTable tbody').innerHTML = data.access.map(l => `
    <tr>
      <td>${escapeHtml(l.user)}</td>
      <td>${l.login || ''}</td>
      <td>${l.logout || '<span class="badge active">in use</span>'}</td>
      <td>${duration(l.login, l.logout)}</td>
    </tr>`).join('');

  document.querySelector('#eventTable tbody').innerHTML = data.events.map(e => `
    <tr>
      <td>${escapeHtml(e.user)}</td>
      <td><span class="tag ${e.type}">${e.type.replace('_',' ')}</span></td>
      <td>${escapeHtml(e.note || '')}</td>
      <td>${e.time || ''}</td>
    </tr>`).join('');
}
function duration(a, b){
  if (!a || !b) return '—';
  const ms = new Date(b.replace(' ','T')) - new Date(a.replace(' ','T'));
  return Math.round(ms / 60000) + ' min';
}

/* ================= PAGE 5: SAFETY CHECKLIST ================= */
function renderChecklist(){
  document.getElementById('checklist').innerHTML = checklistItems.map((it, i) => `
    <li data-required="${it.required}" class="${it.required ? '' : 'optional'}">
      <input type="checkbox" id="chk${i}" onchange="toggleCheck(${i})">
      <span class="label">${escapeHtml(it.text)}</span>
      <span class="flag">${it.required ? 'required' : 'optional'}</span>
    </li>`).join('');
  updateGate();
}
function toggleCheck(i){
  const box = document.getElementById('chk' + i);
  box.closest('li').classList.toggle('checked', box.checked);
  updateGate();
}
function updateGate(){
  const allRequired = checklistItems.every((it, i) =>
    !it.required || document.getElementById('chk' + i).checked);
  const gate = document.getElementById('gate');
  gate.classList.toggle('unlocked', allRequired);
  gate.classList.toggle('locked', !allRequired);
  document.getElementById('gateText').textContent = allRequired
    ? 'Machine unlocks — green light, cleared to run'
    : 'Start locked — complete all required items';
}
function resetChecklist(){ renderChecklist(); }

/* ================= util ================= */
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
