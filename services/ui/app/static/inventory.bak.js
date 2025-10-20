// C4/C5 logic: movements form with scan mode + balances/movements views

// Utilities
function setMvStatus(msg){ const el=document.getElementById("mv-status"); if (el) el.textContent = msg; }

async function fetchJSON(url){ const r=await fetch(url,{credentials:"include"}); if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }

// Movements form
(function(){
  const frmMove = document.getElementById("frm-move");
  if(!frmMove) return;
  const rowsContainer = frmMove.querySelector('[data-multi-rows]');
  const addRowBtn = frmMove.querySelector('[data-add-row]');
  const codeDatalist = frmMove.querySelector('#item_code_options');
  const nameDatalist = frmMove.querySelector('#item_name_options');
  const scanInput = document.getElementById("scan-input");
  const scanLog = document.getElementById("scan-log");
  const modeRadios = frmMove.querySelectorAll('input[name="mode"]');
  modeRadios.forEach(r => r.addEventListener("change", () => {
    const scanMode = frmMove.mode.value === "scan";
    document.getElementById("scan-panel").hidden = !scanMode;
    document.getElementById("manual-panel").hidden = scanMode;
    if (scanMode && scanInput) scanInput.focus();
  }));

  const createRow = () => {
    if (!rowsContainer) return null;
    const tpl = rowsContainer.querySelector('[data-row]');
    if (!(tpl instanceof HTMLElement)) return null;
    const clone = tpl.cloneNode(true);
    clone.querySelectorAll('input').forEach((inp) => {
      if (inp instanceof HTMLInputElement) {
        if (inp.name==='uom') inp.value='EA';
        else if (inp.name==='qty') inp.value='1';
        else inp.value='';
      }
    });
    const codeInp = clone.querySelector("input[name='item_code']");
    const nameInp = clone.querySelector("input[name='item_name']");
    if (codeInp instanceof HTMLInputElement) { codeInp.setAttribute('list','item_code_options'); codeInp.autocomplete='off'; }
    if (nameInp instanceof HTMLInputElement) { nameInp.setAttribute('list','item_name_options'); nameInp.autocomplete='off'; }
    rowsContainer.appendChild(clone);
    ensureRemoveButtons();
    return clone;
  };
  const ensureRemoveButtons = () => {
    if (!rowsContainer) return;
    const rows = rowsContainer.querySelectorAll('[data-row]');
    rows.forEach((row, idx) => {
      const btn = row.querySelector('[data-remove-row]');
      if (btn instanceof HTMLButtonElement) btn.hidden = rows.length <= 1;
    });
  };
  rowsContainer?.addEventListener('click', (e)=>{
    const t=e.target; if(!(t instanceof HTMLElement)) return;
    if(!t.matches('[data-remove-row]')) return;
    const row = t.closest('[data-row]'); if (row && rowsContainer.children.length>1) row.remove();
    ensureRemoveButtons();
  });
  addRowBtn?.addEventListener('click', ()=>{ createRow(); });
  ensureRemoveButtons();

  // Suggestions (autocomplete) for item_code / item_name like receipts
  function debounce(fn, delay){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), delay||250); }; }
  function renderDatalist(datalistEl, items, getValue, getLabel){
    if (!(datalistEl instanceof Element)) return;
    datalistEl.innerHTML = (items||[]).map(it=>`<option value="${(getValue(it)||'').toString().replaceAll('"','&quot;')}">${getLabel(it)||''}</option>`).join('');
  }
  let codeSuggestionMap = new Map();
  let nameSuggestionMap = new Map();
  const fetchCodeSuggestions = debounce(async (value) => {
    const trimmed = String(value||'').trim(); if (trimmed.length<2) { renderDatalist(codeDatalist, [], x=>'', x=>''); return; }
    const params = new URLSearchParams({ q: trimmed, field: 'code', limit: '10' });
    try{
      const r = await fetch(`/labels/products?${params.toString()}`, { credentials: 'include' });
      const items = r.ok ? await r.json().catch(()=>[]) : [];
      codeSuggestionMap = new Map(); nameSuggestionMap = new Map(nameSuggestionMap);
      (items||[]).forEach((it)=>{ if(it?.item_code) codeSuggestionMap.set(String(it.item_code).toUpperCase(), it); if(it?.item_name) nameSuggestionMap.set(String(it.item_name).toLowerCase(), it); });
      renderDatalist(codeDatalist, items, (it)=>it.item_code, (it)=>`${it.item_code} — ${it.item_name||''}`.trim());
    }catch{}
  }, 250);
  const fetchNameSuggestions = debounce(async (value) => {
    const trimmed = String(value||'').trim(); if (trimmed.length<2) { renderDatalist(nameDatalist, [], x=>'', x=>''); return; }
    const params = new URLSearchParams({ q: trimmed, field: 'name', limit: '10' });
    try{
      const r = await fetch(`/labels/products?${params.toString()}`, { credentials: 'include' });
      const items = r.ok ? await r.json().catch(()=>[]) : [];
      nameSuggestionMap = new Map(); codeSuggestionMap = new Map(codeSuggestionMap);
      (items||[]).forEach((it)=>{ if(it?.item_name) nameSuggestionMap.set(String(it.item_name).toLowerCase(), it); if(it?.item_code) codeSuggestionMap.set(String(it.item_code).toUpperCase(), it); });
      renderDatalist(nameDatalist, items, (it)=>it.item_name, (it)=>`${it.item_name} — ${it.item_code||''}`.trim());
    }catch{}
  }, 250);

  rowsContainer?.addEventListener('input', (event)=>{
    const target = event.target; if (!(target instanceof HTMLInputElement)) return;
    const row = target.closest('[data-row]'); if (!row) return;
    if (target.name === 'item_code') { const v=target.value.trim(); if (v.length>=2) fetchCodeSuggestions(v); }
    else if (target.name === 'item_name') { const v=target.value.trim(); if (v.length>=2) fetchNameSuggestions(v); }
  });

  rowsContainer?.addEventListener('change', (event)=>{
    const target = event.target; if (!(target instanceof HTMLInputElement)) return;
    const row = target.closest('[data-row]'); if (!row) return;
    if (target.name === 'item_code') {
      const code = target.value.trim().toUpperCase(); const match = codeSuggestionMap.get(code);
      if (match) { const nameInput = row.querySelector("input[name='item_name']"); if (nameInput) nameInput.value = match.item_name; }
    } else if (target.name === 'item_name') {
      const nameKey = target.value.trim().toLowerCase(); const match = nameSuggestionMap.get(nameKey);
      if (match) { const codeInput = row.querySelector("input[name='item_code']"); if (codeInput) codeInput.value = match.item_code; }
    }
  });

  // Escaneo HID
  let mult=1; if (scanInput){
    scanInput.addEventListener("keydown", (e)=>{
      if(e.key!=="Enter") return; e.preventDefault();
      const raw=scanInput.value.trim(); scanInput.value=""; if(!raw) return;
      const m=raw.match(/^x(\d{1,4})$/i); if(m){ mult=Math.max(1,parseInt(m[1],10)); log(`Multiplicador: x${mult}`); return; }
      addMvLine({ item_code: raw, item_name: "", uom:"EA", qty: mult });
      log(`Código ${raw} agregado x${mult}`); mult=1;
    });
  }
  function log(msg){ const p=document.createElement("div"); p.textContent=msg; if (scanLog) scanLog.prepend(p); }

  // Lookup helper to autofill item_name from item_code
  async function lookupNameByCode(code){
    try{
      const params = new URLSearchParams({ q: code, field: 'code', limit: '1' });
      const r = await fetch(`/labels/products?${params.toString()}`, { credentials: 'include' });
      if(!r.ok) return null;
      const arr = await r.json().catch(()=>null);
      if(!Array.isArray(arr) || !arr.length) return null;
      return arr[0]?.item_name || null;
    }catch{ return null; }
  }

  // After scan (keyup Enter), create a new row and fill it
  if (scanInput){
    scanInput.addEventListener('keyup', async (e)=>{
      if (e.key !== 'Enter') return;
      const raw=scanInput.value.trim(); scanInput.value=''; if(!raw) return;
      const m = raw.match(/^x(\d{1,4})$/i); if(m){ mult=Math.max(1,parseInt(m[1],10)); log(`Multiplicador: x${mult}`); return; }
      const row = createRow() || rowsContainer?.querySelector('[data-row]');
      if (!row) return;
      const codeInput = row.querySelector("input[name='item_code']");
      const nameInput = row.querySelector("input[name='item_name']");
      const qtyInput = row.querySelector("input[name='qty']");
      if (codeInput) codeInput.value = raw;
      if (qtyInput) qtyInput.value = String(mult);
      const name = await lookupNameByCode(raw);
      if (name && nameInput) nameInput.value = name;
      log(`Código ${raw} agregado x${mult}`); mult=1;
    });
  }

  document.getElementById("btn-add-mv-line")?.addEventListener("click", ()=>{ createRow(); });

  // Autofill name when item_code changes manually
  rowsContainer?.addEventListener('change', (e)=>{
    const t=e.target; if(!(t instanceof HTMLInputElement)) return; if (t.name!== 'item_code') return;
    const tr=t.closest('tr'); if(!tr) return; const code=(t.value||'').trim(); if(!code) return;
    const container = t.closest('[data-row]') || tr;
    lookupNameByCode(code).then(name=>{ if(!name) return; const nameInp=container.querySelector('input[name="item_name"]'); if(nameInp) nameInp.value=name; });
  });

  frmMove.addEventListener("submit", async (e)=>{
    e.preventDefault();
    const type = frmMove.type.value;
    const wf = frmMove.warehouse_from.value || null;
    const wt = frmMove.warehouse_to.value || null;
    const reference = frmMove.reference.value || null;
    const note = frmMove.note.value || null;
    const rows=[...(rowsContainer?.querySelectorAll('[data-row]')||[])];
    const lines=[];
    for(const row of rows){
      const g=(n)=>row.querySelector(`[name="${n}"]`)?.value?.trim()||"";
      const qty=parseFloat(g("qty")); if(!g("item_code")||!(qty>0)) continue;
      lines.push({ item_code:g("item_code"), item_name:g("item_name")||g("item_code"), uom:g("uom")||"EA", qty, batch:g("batch")||null, serial:g("serial")||null });
    }
    if(!lines.length){ return setMvStatus("Agrega al menos una línea"); }
    try{
      for(const ln of lines){
        const payload = { ...ln, type, warehouse_from: wf, warehouse_to: wt, reference, note };
        const resp = await fetch("/inventory/movements", { method:"POST", headers:{"Content-Type":"application/json"}, credentials:"include", body: JSON.stringify(payload)});
        const ct = resp.headers.get("content-type")||""; const data = ct.includes("json")? await resp.json().catch(()=>null): null;
        if(!resp.ok) throw new Error((data && data.detail) || `HTTP ${resp.status}`);
      }
      setMvStatus("Movimiento creado");
      if (rowsContainer) rowsContainer.innerHTML = '';
    }catch(err){ setMvStatus(`Error: ${err.message}`); }
  });

  document.getElementById("btn-clear-mv")?.addEventListener("click", ()=>{ if (rowsContainer) rowsContainer.innerHTML=''; setMvStatus(""); });

  // cargar bodegas en selects
  (async ()=>{
    try{ const list = await fetchJSON("/inventory/warehouses");
      const fill=(sel)=> sel.innerHTML = ['<option value=""></option>'].concat(list.map(w=>`<option value="${w.code}">${w.code} — ${w.name}</option>`)).join("");
      fill(frmMove.warehouse_from); fill(frmMove.warehouse_to);
      // Preselect type from query param if present
      const params = new URLSearchParams(location.search);
      const t = (params.get('type')||'').toUpperCase();
      const selType = frmMove.querySelector('select[name="type"]');
      if (selType && ['OUTBOUND','TRANSFER','RETURN','ADJUST'].includes(t)) selType.value = t;
    }catch{ const opt='<option value="BP">BP — Bodega Principal</option>'; frmMove.warehouse_from.innerHTML=opt; frmMove.warehouse_to.innerHTML=opt; }
  })();
})();

// Views: balances + movements
(function(){
  const balBody=document.querySelector("#tbl-balance tbody");
  const movBody=document.querySelector("#tbl-mov tbody");
  const loadBalances = async ()=>{
    const item=document.getElementById("f-item").value.trim();
    const wh=document.getElementById("f-wh").value;
    const qs=new URLSearchParams(); if(item) qs.set("item_code", item); if(wh) qs.set("warehouse", wh);
    const rows = await fetchJSON(`/inventory/balances?${qs}`);
    balBody.innerHTML = rows.map(r=>`<tr><td class="mono">${r.item_code}</td><td>${r.warehouse_code}</td><td>${r.batch||""}</td><td>${r.serial||""}</td><td class="num">${r.qty}</td></tr>`).join("");
  };
  const loadMovements = async ()=>{
    const rows = await fetchJSON(`/inventory/movements?limit=100`);
    movBody.innerHTML = rows.map(r=>`<tr><td>${new Date(r.created_at).toLocaleString()}</td><td>${r.type}</td><td class="mono">${r.item_code} — ${r.item_name||""}</td><td class="num">${r.qty}</td><td>${r.warehouse_from||""}</td><td>${r.warehouse_to||""}</td><td>${r.reference||""}</td></tr>`).join("");
  };
  document.getElementById("btn-load-balance")?.addEventListener("click", loadBalances);
  document.getElementById("btn-load-mov")?.addEventListener("click", loadMovements);
  (async ()=>{ // populate warehouse filter
    try{ const list = await fetchJSON("/inventory/warehouses"); const sel=document.getElementById("f-wh"); sel.innerHTML = `<option value="">(todas)</option>` + list.map(w=>`<option value="${w.code}">${w.code} — ${w.name}</option>`).join(""); }catch{}
  })();
})();

// D7 — Count scanning panel
(function(){
  const countWh = document.getElementById('count-wh');
  const btnStart = document.getElementById('btn-count-start');
  const area = document.getElementById('count-area');
  const scan = document.getElementById('count-scan');
  const statusEl = document.getElementById('count-status');
  const log = (m)=>{ const p=document.createElement('div'); p.textContent=m; document.getElementById('count-log').prepend(p); };
  const setCS=(m)=>{ if(statusEl) statusEl.textContent=m; };
  let sid=null, mult=1;
  if (!countWh) return;
  // load warehouses
  (async()=>{
    try{ const list = await fetchJSON('/inventory/warehouses'); countWh.innerHTML = list.map(w=>`<option value="${w.code}">${w.code} — ${w.name}</option>`).join(''); }catch{ countWh.innerHTML='<option value="BP">BP — Bodega Principal</option>'; }
  })();
  btnStart?.addEventListener('click', async ()=>{
    const wh = countWh.value; if(!wh) return setCS('Selecciona bodega');
    const r = await fetch('/count/sessions',{method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({warehouse_code: wh})});
    const d = await r.json().catch(()=>null); if(!r.ok) return setCS((d&&d.detail)||'Error');
    sid = d.id; area.hidden=false; scan.focus(); setCS(`Sesión ${sid} abierta`);
  });
  scan?.addEventListener('keydown', async (e)=>{
    if(e.key!=="Enter") return; e.preventDefault(); const raw=scan.value.trim(); scan.value=''; if(!raw) return;
    const m=raw.match(/^x(\d{1,4})$/i); if(m){ mult=Math.max(1,parseInt(m[1],10)); log(`x${mult}`); return; }
    const r = await fetch(`/count/sessions/${sid}/scan`, { method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({barcode: raw, qty: mult})});
    if(!r.ok){ const t=await r.text(); log(`ERR ${t}`); return; }
    log(`+ ${raw} x${mult}`); mult=1;
  });
  document.getElementById('btn-count-close')?.addEventListener('click', async ()=>{
    const r = await fetch(`/count/sessions/${sid}/finalize`, { method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({adjustments: true})});
    const d = await r.json().catch(()=>null); if(!r.ok) return setCS((d&&d.detail)||'Error');
    setCS(`Cerrada. Propuestas: ${Array.isArray(d.proposed_adjustments)? d.proposed_adjustments.length : 0}`);
  });
})();

// D8 — Outbound/Transfer scanning panel
(function(){
  const typeSel = document.getElementById('out-type');
  const wfSel = document.getElementById('out-wf');
  const wtSel = document.getElementById('out-wt');
  const btnStart = document.getElementById('btn-out-start');
  const area = document.getElementById('out-area');
  const scan = document.getElementById('out-scan');
  const btnConfirm = document.getElementById('btn-out-confirm');
  const statusEl = document.getElementById('out-status');
  const log = (m)=>{ const p=document.createElement('div'); p.textContent=m; document.getElementById('out-log').prepend(p); };
  const setOS=(m)=>{ if(statusEl) statusEl.textContent=m; };
  let sid=null, mult=1;
  if (!typeSel) return;
  // load warehouses
  (async()=>{
    try{ const list = await fetchJSON('/inventory/warehouses'); const opt=list.map(w=>`<option value="${w.code}">${w.code} — ${w.name}</option>`).join(''); wfSel.innerHTML=opt; wtSel.innerHTML=opt; }catch{ const opt='<option value="BP">BP — Bodega Principal</option>'; wfSel.innerHTML=opt; wtSel.innerHTML=opt; }
  })();
  btnStart?.addEventListener('click', async ()=>{
    const type = typeSel.value; const wf=wfSel.value; const wt = wtSel.value || null; if(!wf) return setOS('Selecciona bodega origen'); if(type==='TRANSFER' && !wt) return setOS('Selecciona bodega destino');
    const r = await fetch('/outbound/sessions', { method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({type, warehouse_from: wf, warehouse_to: wt})});
    const d = await r.json().catch(()=>null); if(!r.ok) return setOS((d&&d.detail)||'Error'); sid=d.id; area.hidden=false; scan.focus(); setOS(`Sesión ${sid} abierta`);
  });
  scan?.addEventListener('keydown', async (e)=>{
    if(e.key!=="Enter") return; e.preventDefault(); const raw=scan.value.trim(); scan.value=''; if(!raw) return;
    const m=raw.match(/^x(\d{1,4})$/i); if(m){ mult=Math.max(1,parseInt(m[1],10)); log(`x${mult}`); return; }
    const r = await fetch(`/outbound/sessions/${sid}/scan`, { method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({barcode: raw, qty: mult})});
    if(!r.ok){ const t=await r.text(); log(`ERR ${t}`); return; }
    log(`- ${raw} x${mult}`); mult=1;
  });
  btnConfirm?.addEventListener('click', async ()=>{
    const r = await fetch(`/outbound/sessions/${sid}/confirm`, { method:'POST', credentials:'include' });
    const d = await r.json().catch(()=>null); if(!r.ok) return setOS((d&&d.detail)||'Error'); setOS(`Confirmado. Líneas: ${d.lines}`); sid=null; area.hidden=true;
  });
})();
