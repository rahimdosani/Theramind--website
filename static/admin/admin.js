async function fetchJson(url, opts={}) {
  const res = await fetch(url, Object.assign({credentials: 'same-origin', headers: {'Content-Type':'application/json'}}, opts));
  return res.json();
}
function el(tag, text, cls){ const e = document.createElement(tag); if(text) e.textContent = text; if(cls) e.className = cls; return e; }

async function loadUsers(){
  const box = document.getElementById('users-list'); box.innerHTML = 'Loading users...';
  try {
    const users = await fetchJson('/admin/users');
    box.innerHTML = '';
    if(!users || users.length === 0){ box.textContent = 'No users'; return; }
    users.forEach(u=>{
      const row = el('div', null, 'list-item');
      const left = el('div', `${u.username} ${u.is_admin? '(admin)':''}`);
      const right = el('div', null);
      const del = el('button', 'Delete', 'btn');
      del.onclick = async ()=> { alert('Delete user not implemented yet'); };
      right.appendChild(del);
      row.appendChild(left); row.appendChild(right); box.appendChild(row);
    });
  } catch(e){ box.textContent = 'Failed to load users'; console.error(e); }
}

async function loadConvos(){
  const box = document.getElementById('convos-list'); box.innerHTML = 'Loading convos...';
  try {
    const convs = await fetchJson('/get_conversations');
    box.innerHTML = '';
    if(!convs || convs.length === 0){ box.textContent = 'No saved conversations'; return; }
    convs.forEach(c=>{
      const row = el('div', null, 'list-item');
      const left = el('div', `${c.title}`);
      const right = el('div', null);
      const view = el('button', 'Open', 'btn');
      view.onclick = async ()=> {
        const history = await fetchJson(`/load_conversation/${c.id}`);
        const w = window.open('', '_blank');
        w.document.title = `Conversation ${c.id}`;
        w.document.body.innerHTML = `<pre style="white-space:pre-wrap;font-family:monospace;padding:20px;">${JSON.stringify(history, null, 2)}</pre>`;
      };
      const del = el('button', 'Delete', 'btn');
      del.onclick = async ()=> {
        if(!confirm('Delete conversation?')) return;
        const res = await fetch(`/delete_conversation/${c.id}`, {method:'DELETE', credentials:'same-origin'});
        const data = await res.json();
        if(data.status === 'deleted') loadConvos(); else alert('Delete failed');
      };
      right.appendChild(view); right.appendChild(del); row.appendChild(left); row.appendChild(right); box.appendChild(row);
    });
  } catch(e){ box.textContent = 'Failed to load convos'; console.error(e); }
}

document.addEventListener('DOMContentLoaded', ()=>{
  loadUsers(); loadConvos();
  document.getElementById('create-user').addEventListener('click', async ()=>{
    const username = document.getElementById('new-username').value.trim();
    const password = document.getElementById('new-password').value;
    const isAdmin = document.getElementById('new-is-admin').checked;
    if(!username || !password){ alert('username & password required'); return; }
    const res = await fetch('/admin/create_user', { method: 'POST', credentials: 'same-origin', body: JSON.stringify({username, password, is_admin: isAdmin})});
    const data = await res.json();
    if(data.status === 'ok'){ alert('User created'); loadUsers(); } else { alert('Create failed: ' + (data.message||'unknown')); }
  });
});
