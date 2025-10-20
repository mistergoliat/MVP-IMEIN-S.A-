function initDynamicLines() {
  const addLineButtonSelector = "[data-add-line]";
  const lineItemsSelector = "[data-line-items]";
  const template = document.getElementById("line-row-template");

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (!target.matches(addLineButtonSelector)) return;
    const container = target.closest("form")?.querySelector(lineItemsSelector);
    if (!container || !template) return;
    const clone = template.content.firstElementChild.cloneNode(true);
    container.appendChild(clone);
  });
}

function parseJSON(value, fallback = {}) {
  try {
    return value ? JSON.parse(value) : fallback;
  } catch (error) {
    return fallback;
  }
}

function formatToday() {
  const now = new Date();
  const day = String(now.getDate()).padStart(2, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const year = String(now.getFullYear());
  return `${day}-${month}-${year}`;
}


function debounce(fn, delay = 250) {
  let timerId;
  return (...args) => {
    if (timerId) clearTimeout(timerId);
    timerId = setTimeout(() => {
      fn(...args);
    }, delay);
  };
}

function buildPayload(formRow) {
  const dateInput = formRow.querySelector("input[name='fecha']");
  const today = formatToday();
  if (dateInput instanceof HTMLInputElement) {
    dateInput.value = today;
  }
  const get = (selector) => {
    const input = formRow.querySelector(selector);
    if (input instanceof HTMLInputElement) {
      return input.value.trim();
    }
    return "";
  };
  const itemCode = get("input[name='item_code']").toUpperCase();
  const itemName = get("input[name='item_name']");
  const copiesRaw = get("input[name='copies']") || "1";
  const copies = Math.min(10, Math.max(1, Number.parseInt(copiesRaw, 10) || 1));

  if (!itemCode) {
    throw new Error("Completa un código válido antes de continuar.");
  }
  if (!itemName) {
    throw new Error("Completa la descripción antes de continuar.");
  }

  return { item_code: itemCode, item_name: itemName, fecha: today, copies };
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" ? data.detail : null;
    throw new Error(detail || Error );
  }
  return data || {};
}

function setStatus(element, type, message) {
  if (!element) return;
  element.hidden = false;
  element.textContent = message;
  element.className = "alert";
  if (type === "success") {
    element.classList.add("alert-success");
  } else if (type === "error") {
    element.classList.add("alert-error");
  } else {
    element.classList.add("alert-info");
  }
}

function clearStatus(element) {
  if (!element) return;
  element.hidden = true;
  element.textContent = "";
  element.className = "alert";
}

const TEMPLATE_LABELS = {
  etiqueta_50x30: "1 columna",
  etiqueta_50x30_2across: "2 columnas",
  etiqueta_50x30_2across_duplicada: "2 columnas duplicada",
};

function applyPreview(preview, elements) {
  const {
    previewPanel,
    templateBadge,
    copiesValue,
    effectiveValue,
    modeValue,
    zplPreview,
  } = elements;

  if (!previewPanel) return;
  previewPanel.hidden = false;
  if (templateBadge) {
    templateBadge.textContent = TEMPLATE_LABELS[preview.template] || preview.template;
  }
  if (copiesValue) {
    copiesValue.textContent = String(preview.copies ?? "--");
  }
  if (effectiveValue) {
    effectiveValue.textContent = String(preview.effective_labels ?? "--");
  }
  if (modeValue) {
    modeValue.textContent = preview.mode || "--";
  }
  if (zplPreview) {
    zplPreview.textContent = preview.zpl || "";
  }
}

function showPrinterSection(wrapper, shouldShow) {
  if (!wrapper) return;
  wrapper.hidden = !shouldShow;
}

async function ensureQzConnected() {
  const { qz } = window;
  if (!qz) {
    throw new Error("QZ Tray no esta disponible en este navegador.");
  }
  if (!qz.websocket.isActive()) {
    await qz.websocket.connect();
  }
  return qz;
}

async function listPrinters(printerSelect, hintElement) {
  try {
    const qz = await ensureQzConnected();
    if (qz.security) {
      qz.security.setCertificatePromise((resolve) => {
        resolve();
      });
      qz.security.setSignaturePromise(() => {
        return (resolve) => resolve();
      });
    }
    const printers = await qz.printers.find();
    const filtered = printers.filter((name) => /zd/i.test(name) || /zdesigner/i.test(name));
    printerSelect.innerHTML = "";
    if (!filtered.length) {
      const option = document.createElement("option");
      option.textContent = "Sin coincidencias";
      option.value = "";
      printerSelect.appendChild(option);
      if (hintElement) {
        hintElement.textContent = "No se detectaron impresoras Zebra. Asegura la conexion.";
      }
      return;
    }
    filtered.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      printerSelect.appendChild(option);
    });
    if (hintElement) {
      hintElement.textContent = "Selecciona la impresora destino.";
    }
  } catch (error) {
    if (hintElement) {
      hintElement.textContent = error instanceof Error ? error.message : String(error);
    }
    printerSelect.innerHTML = "";
    const option = document.createElement("option");
    option.textContent = "No disponible";
    option.value = "";
    printerSelect.appendChild(option);
  }
}

async function printLocally(printer, zpl) {
  const qz = await ensureQzConnected();
  const cfg = qz.configs.create(printer, { encoding: "utf-8" });
  const data = [{ type: "raw", format: "plain", data: zpl }];
  await qz.print(cfg, data);
}

function renderDatalist(datalist, items, getValue, getLabel) {
  if (!(datalist instanceof HTMLDataListElement)) return;
  datalist.innerHTML = "";
  items.forEach((item) => {
    const value = getValue(item);
    if (!value) return;
    const option = document.createElement("option");
    option.value = value;
    const label = getLabel ? getLabel(item) : null;
    if (label) option.label = label;
    datalist.appendChild(option);
  });
}

function renderJobs(jobs, elements) {
  const { table, body, empty } = elements;
  if (!(body instanceof HTMLElement)) return;
  const list = Array.isArray(jobs) ? jobs : [];
  body.innerHTML = "";
  list.forEach((job) => {
    const row = document.createElement("tr");
    const cells = [
      { value: job?.id ?? "--", className: "mono" },
      { value: job?.status ? String(job.status).toUpperCase() : "--" },
      { value: job?.copies ?? "--" },
      { value: job?.created_at ?? "--" },
    ];
    cells.forEach(({ value, className }) => {
      const cell = document.createElement("td");
      if (className) cell.classList.add(className);
      cell.textContent = value == null ? "--" : String(value);
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  if (table instanceof HTMLElement) {
    table.hidden = list.length === 0;
  }
  if (empty instanceof HTMLElement) {
    empty.hidden = list.length > 0;
  }
}

function setJobsError(box, message) {
  if (!(box instanceof HTMLElement)) return;
  const text = String(message || "").trim();
  if (!text) {
    box.hidden = true;
    box.textContent = "";
  } else {
    box.hidden = false;
    box.textContent = text;
  }
}

async function fetchJobsData() {
  const response = await fetch("/labels/jobs", { credentials: "include" });
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" ? data.detail : null;
    throw new Error(detail || Error );
  }
  if (!Array.isArray(data)) {
    throw new Error("Respuesta de cola invalida.");
  }
  return data;
}

const suggestionControllers = {
  code: null,
  name: null,
};

async function fetchProductSuggestions(query, field) {
  const trimmed = String(query || "").trim();
  if (trimmed.length < 2) {
    return [];
  }
  const key = field === "code" ? "code" : "name";
  if (suggestionControllers[key]) {
    suggestionControllers[key].abort();
  }
  const controller = new AbortController();
  suggestionControllers[key] = controller;
try {
  const params = new URLSearchParams({ q: trimmed, field: key });
  const response = await fetch(`/labels/products?${params.toString()}`, {
    credentials: "include",
    signal: controller.signal,
  });
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      return [];
    }
    if (!Array.isArray(data)) {
      return [];
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return [];
    }
    return [];
  } finally {
    if (suggestionControllers[key] === controller) {
      suggestionControllers[key] = null;
    }
  }
}

function initMultiRow(form) {
  const rowsContainer = form.querySelector("[data-multi-rows]");
  const addRowBtn = form.querySelector("[data-add-row]");
  const codeDatalist = form.querySelector("#item_code_options");
  const nameDatalist = form.querySelector("#item_name_options");

  if (!(rowsContainer instanceof HTMLElement)) return;

  const createRow = () => {
    const templateRow = rowsContainer.querySelector("[data-row]");
    if (!(templateRow instanceof HTMLElement)) return null;
    const clone = templateRow.cloneNode(true);
    const inputs = clone.querySelectorAll("input");
    inputs.forEach((input) => {
      if (input instanceof HTMLInputElement) {
        if (input.type === "number") {
          input.value = "1";
        } else {
          input.value = "";
        }
      }
    });
    const removeBtn = clone.querySelector("[data-remove-row]");
    if (removeBtn instanceof HTMLElement) {
      removeBtn.hidden = false;
    }
    rowsContainer.appendChild(clone);
    return clone;
  };

  const ensureRemoveButtons = () => {
    const rows = rowsContainer.querySelectorAll("[data-row]");
    rows.forEach((row, index) => {
      const removeBtn = row.querySelector("[data-remove-row]");
      if (removeBtn instanceof HTMLElement) {
        removeBtn.hidden = rows.length <= 1 || index === 0;
      }
    });
  };

  rowsContainer.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (!target.matches("[data-remove-row]")) return;
    const row = target.closest("[data-row]");
    if (row && rowsContainer.children.length > 1) {
      row.remove();
      ensureRemoveButtons();
    }
  });

  addRowBtn?.addEventListener("click", () => {
    createRow();
    ensureRemoveButtons();
  });

  ensureRemoveButtons();

  return { rowsContainer, codeDatalist, nameDatalist };
}

function registerSuggestions(store, items) {
  store.clear();
  items.forEach((item) => {
    if (item?.item_code) {
      store.set(String(item.item_code).toUpperCase(), item);
    }
    if (item?.item_name) {
      store.set(String(item.item_name).toLowerCase(), item);
    }
  });
}

function initPrintModule() {
  const app = document.querySelector("[data-print-app]");
  if (!app) return;

  const form = app.querySelector("[data-print-form]");
  const previewBtn = app.querySelector("[data-preview-btn]");
  const printBtn = app.querySelector("[data-print-btn]");
  const statusMessage = app.querySelector("[data-status-message]");
  const previewPanel = app.querySelector("[data-preview-panel]");
  const templateBadge = app.querySelector("[data-template-badge]");
  const copiesValue = app.querySelector("[data-copies-value]");
  const effectiveValue = app.querySelector("[data-effective-value]");
  const modeValue = app.querySelector("[data-mode-value]");
  const zplPreview = app.querySelector("[data-zpl-preview]");
  const printerWrapper = app.querySelector("[data-printer-select-wrapper]");
  const printerSelect = app.querySelector("[data-printer-select]");
  const refreshPrintersBtn = app.querySelector("[data-refresh-printers]");
  const printerHint = app.querySelector("[data-printer-hint]");

  if (!(form instanceof HTMLFormElement)) return;

  const multi = initMultiRow(form);
  if (!multi) return;
  const { rowsContainer, codeDatalist, nameDatalist } = multi;

  let codeSuggestionMap = new Map();
  let nameSuggestionMap = new Map();

const fetchCodeSuggestions = debounce(async (value) => {
  const items = await fetchProductSuggestions(value, "code");
  codeSuggestionMap = new Map();
  items.forEach((item) => {
    if (item?.item_code) {
      codeSuggestionMap.set(String(item.item_code).toUpperCase(), item);
    }
    if (item?.item_name) {
      nameSuggestionMap.set(String(item.item_name).toLowerCase(), item);
    }
  });
  renderDatalist(
    codeDatalist,
    items,
    (item) => item.item_code,
    (item) => `${item.item_code} Â·`.trim()
  );
});

const fetchNameSuggestions = debounce(async (value) => {
  const items = await fetchProductSuggestions(value, "name");
  nameSuggestionMap = new Map();
  items.forEach((item) => {
    if (item?.item_name) {
      nameSuggestionMap.set(String(item.item_name).toLowerCase(), item);
    }
    if (item?.item_code) {
      codeSuggestionMap.set(String(item.item_code).toUpperCase(), item);
    }
  });
  renderDatalist(
    nameDatalist,
    items,
    (item) => item.item_name,
    (item) => `${item.item_name} Â·`.trim()
  );
});


  rowsContainer.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const row = target.closest("[data-row]");
    if (!row) return;
    if (target.name === "item_code") {
      const value = target.value.trim();
      if (value.length >= 2) {
        fetchCodeSuggestions(value);
      }
    } else if (target.name === "item_name") {
      const value = target.value.trim();
      if (value.length >= 2) {
        fetchNameSuggestions(value);
      }
    }
  });

  rowsContainer.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const row = target.closest("[data-row]");
    if (!row) return;
    if (target.name === "item_code") {
      const code = target.value.trim().toUpperCase();
      const match = codeSuggestionMap.get(code);
      if (match) {
        const nameInput = row.querySelector("input[name='item_name']");
        if (nameInput instanceof HTMLInputElement) {
          nameInput.value = match.item_name;
        }
      }
    } else if (target.name === "item_name") {
      const nameKey = target.value.trim().toLowerCase();
      const match = nameSuggestionMap.get(nameKey);
      if (match) {
        const codeInput = row.querySelector("input[name='item_code']");
        if (codeInput instanceof HTMLInputElement) {
          codeInput.value = match.item_code;
        }
      }
    }
  });

  const previewElements = {
    previewPanel,
    templateBadge,
    copiesValue,
    effectiveValue,
    modeValue,
    zplPreview,
  };

  const printerSection = () => {}

  let jobsLoading = false;
  const jobsTable = app.querySelector("[data-jobs-table]");
  const jobsTableBody = app.querySelector("[data-jobs-body]");
  const jobsEmpty = app.querySelector("[data-jobs-empty]");
  const jobsErrorBox = app.querySelector("[data-jobs-error]");
  const jobsSection = app.querySelector("[data-jobs-section]");
  const refreshJobsBtn = app.querySelector("[data-refresh-jobs]");

  const jobsElements = {
    table: jobsTable instanceof HTMLElement ? jobsTable : null,
    body: jobsTableBody instanceof HTMLElement ? jobsTableBody : null,
    empty: jobsEmpty instanceof HTMLElement ? jobsEmpty : null,
  };

  const refreshJobs = async () => {
    if (!(jobsSection instanceof HTMLElement)) return;
    if (jobsLoading) return;
    jobsLoading = true;
    if (refreshJobsBtn instanceof HTMLButtonElement) {
      refreshJobsBtn.disabled = true;
    }
    try {
      const data = await fetchJobsData();
      renderJobs(data, jobsElements);
    } catch (error) {
      setJobsError(jobsErrorBox, error instanceof Error ? error.message : String(error));
    } finally {
      jobsLoading = false;
      if (refreshJobsBtn instanceof HTMLButtonElement) {
        refreshJobsBtn.disabled = false;
      }
    }
  };

  refreshJobsBtn?.addEventListener("click", () => {
    refreshJobs();
  });

  const printerWrapperEl = printerWrapper;
  const togglePrinterUi = (mode) => {
    showPrinterSection(printerWrapperEl, mode === "local");
    if (mode === "local" && printerSelect instanceof HTMLSelectElement) {
      listPrinters(printerSelect, printerHint instanceof HTMLElement ? printerHint : null);
    }
  };

  const config = parseJSON(app.dataset.printerConfig || "{}");
  const initialMode = typeof config.mode === "string" ? config.mode : "network";
  togglePrinterUi(initialMode);

  refreshPrintersBtn?.addEventListener("click", () => {
    if (printerSelect instanceof HTMLSelectElement) {
      listPrinters(printerSelect, printerHint instanceof HTMLElement ? printerHint : null);
    }
  });

  const handlePreview = async () => {
    clearStatus(statusMessage);
    try {
      const rows = rowsContainer.querySelectorAll("[data-row]");
      if (!rows.length) {
        throw new Error("Agrega al menos un SKU antes de previsualizar.");
      }
      const previews = [];
      let lastResult = null;
      for (const row of rows) {
        const payload = buildPayload(row);
        const preview = await postJSON("/labels/preview", payload);
        previews.push(preview);
        lastResult = preview;
      }
      if (lastResult) {
        applyPreview(lastResult, previewElements);
        togglePrinterUi(lastResult.mode || initialMode);
        if (rows.length > 1) {
          setStatus(
            statusMessage,
            "success",
            `Previsualización generada para ${rows.length} SKUs.`
          );
        } else {
          setStatus(
            statusMessage,
            "success",
            "Previsualización generada correctamente."
          );
        }

        if (lastResult.zpl) {
          const joiner = previews
            .map((p) => p.zpl || "")
            .filter(Boolean)
            .join("\n");
          if (joiner) {
            previewElements.zplPreview.textContent = joiner;
          }
        }
      }
    } catch (error) {
      setStatus(
        statusMessage,
        "error",
        error instanceof Error ? error.message : String(error)
      );
    }
}; // â† cierre de handlePreview

const handlePrint = async () => {
  clearStatus(statusMessage);
  try {
    const rows = rowsContainer.querySelectorAll("[data-row]");
    if (!rows.length) {
      throw new Error("Agrega al menos un SKU antes de imprimir.");
    }
    let lastResult = null;
    for (const row of rows) {
      const payload = buildPayload(row);
      const result = await postJSON("/labels/print", payload);
      lastResult = result;
      togglePrinterUi(result.mode || initialMode);
      if ((result.mode || initialMode) === "local") {
        if (!(printerSelect instanceof HTMLSelectElement)) {
          throw new Error("Selección de impresora no disponible.");
        }
        const printerName = printerSelect.value;
        if (!printerName) {
          throw new Error("Selecciona una impresora antes de imprimir.");
        }
        if (!result.zpl) {
          throw new Error("La API no devolvía datos ZPL para impresión local.");
        }
        await printLocally(printerName, result.zpl);
      }
    }
    if (lastResult) {
      applyPreview(lastResult, previewElements);
      setStatus(
        statusMessage,
        "success",
        rows.length > 1
          ? `Se enviaron ${rows.length} SKUs a imprimir.`
          : "Trabajo enviado correctamente."
      );
      const data = await fetchJobsData();
      renderJobs(data, jobsElements);
    }
  } catch (error) {
    setStatus(
      statusMessage,
      "error",
      error instanceof Error ? error.message : String(error)
    );
  }
}; // â† cierre de handlePrint

previewBtn?.addEventListener("click", handlePreview);
printBtn?.addEventListener("click", handlePrint);
}; // â† cierre de initPrintModule

document.addEventListener("DOMContentLoaded", () => {
  initDynamicLines();
  initPrintModule();
  initAnalyticsModule();
  initReceiptsModule();
});

// ------------------------
// ABC–XYZ helpers (UI)
// ------------------------
function createAbcXyzBadge(abc, xyz) {
  const cls = `${String(abc || "").toUpperCase()}${String(xyz || "").toUpperCase()}`;
  const el = document.createElement("span");
  el.className = "badge";
  el.textContent = cls || "—";
  let bg = "#059669"; // emerald-600
  if (cls === "AX") bg = "#dc2626"; // red-600
  else if (String(abc || "").toUpperCase() === "A") bg = "#d97706"; // amber-600
  el.style.cssText = `margin-left:6px;padding:2px 6px;border-radius:6px;color:white;background:${bg}`;
  return el;
}

// Add badge + policy when selecting item_code in print view
document.addEventListener("change", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (target.name !== "item_code") return;
  const row = target.closest("[data-row]");
  if (!row || !row.closest("[data-print-app]")) return;
  const code = target.value.trim().toUpperCase();
  if (!code) return;
  try {
    const r = await fetch(`/analytics/abcxyz/item/${encodeURIComponent(code)}`, { credentials: "include" });
    const data = r.ok ? await r.json() : null;
    let meta = row.querySelector("[data-abcxyz-meta]");
    if (!meta) {
      meta = document.createElement("div");
      meta.setAttribute("data-abcxyz-meta", "");
      meta.style.cssText = "font-size:12px;color:#444;margin-top:4px;display:flex;align-items:center;gap:6px;";
      const codeField = row.querySelector(".form-field");
      if (codeField) codeField.appendChild(meta);
      else row.appendChild(meta);
    }
    meta.innerHTML = "";
    if (data && data.abc && data.xyz) {
      const badge = createAbcXyzBadge(data.abc, data.xyz);
      meta.appendChild(badge);
      const pol = document.createElement("small");
      pol.textContent = data.policy ? ` ${data.policy}` : "";
      meta.appendChild(pol);
    } else {
      const pol = document.createElement("small");
      pol.textContent = "Sin clasificación ABC–XYZ";
      meta.appendChild(pol);
    }
  } catch (e) {
    // ignore errors quietly
  }
});

// ------------------------
// Analytics page module
// ------------------------
function initAnalyticsModule() {
  const root = document.querySelector("[data-analytics-abcxyz]");
  if (!root) return;

  const periodEl = root.querySelector("[data-period]");
  const updatedEl = root.querySelector("[data-updated]");
  const kTotal = root.querySelector("[data-kpi-total]");
  const kA = root.querySelector("[data-kpi-a]");
  const kB = root.querySelector("[data-kpi-b]");
  const kC = root.querySelector("[data-kpi-c]");
  const heatmap = root.querySelector("[data-heatmap]");
  const tbody = root.querySelector("[data-table-body]");
  const empty = root.querySelector("[data-empty]");
  const fAbc = root.querySelector("[data-filter-abc]");
  const fXyz = root.querySelector("[data-filter-xyz]");
  const fSearch = root.querySelector("[data-search-code]");
  const uploader = root.querySelector("[data-uploader]");
  const uploadStatus = root.querySelector("[data-upload-status]");

  let state = { rows: [], summary: { matrix: [], kpi: { total: 0, percentA: 0, percentB: 0, percentC: 0 } } };

  const renderKpis = () => {
    const kpi = state.summary.kpi || { total: 0, percentA: 0, percentB: 0, percentC: 0 };
    if (kTotal) kTotal.textContent = String(kpi.total || 0);
    if (kA) kA.textContent = `${kpi.percentA || 0}%`;
    if (kB) kB.textContent = `${kpi.percentB || 0}%`;
    if (kC) kC.textContent = `${kpi.percentC || 0}%`;
  };

  const renderHeatmap = () => {
    if (!(heatmap instanceof HTMLElement)) return;
    const catsX = ["A", "B", "C"]; // X axis ABC
    const catsY = ["X", "Y", "Z"]; // Y axis XYZ
    const matrix = state.summary.matrix || [];
    const key = (a, x) => `${a}-${x}`;
    const map = new Map(matrix.map((m) => [key(m.abc, m.xyz), Number(m.count) || 0]));
    const max = Math.max(1, ...Array.from(map.values()));
    const cell = (label, isHdr = false) => {
      const div = document.createElement("div");
      div.className = isHdr ? "hdr" : "cell";
      div.textContent = label;
      return div;
    };
    heatmap.innerHTML = "";
    heatmap.appendChild(cell(" ", true));
    catsX.forEach((c) => heatmap.appendChild(cell(c, true)));
    catsY.forEach((y) => {
      heatmap.appendChild(cell(y, true));
      catsX.forEach((a) => {
        const val = map.get(key(a, y)) || 0;
        const intensity = Math.round((val / max) * 180) + 40; // 40..220
        const box = cell(String(val));
        box.style.background = `hsl(160, 60%, ${Math.max(25, 80 - intensity/3)}%)`;
        box.style.color = "#fff";
        heatmap.appendChild(box);
      });
    });
  };

  const applyFilters = () => {
    const fa = fAbc instanceof HTMLSelectElement ? (fAbc.value || "").toUpperCase() : "";
    const fx = fXyz instanceof HTMLSelectElement ? (fXyz.value || "").toUpperCase() : "";
    const q = fSearch instanceof HTMLInputElement ? (fSearch.value || "").trim().toUpperCase() : "";
    return state.rows.filter((r) => {
      const okA = !fa || String(r.abc || "").toUpperCase() === fa;
      const okX = !fx || String(r.xyz || "").toUpperCase() === fx;
      const okQ = !q || String(r.item_code || "").toUpperCase().includes(q);
      return okA && okX && okQ;
    });
  };

  const renderTable = () => {
    const rows = applyFilters();
    if (!(tbody instanceof HTMLElement) || !(empty instanceof HTMLElement)) return;
    tbody.innerHTML = "";
    if (!rows.length) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    const fmt = (v) => {
      if (v === null || v === undefined || v === "") return "";
      const n = Number(v);
      if (!Number.isFinite(n)) return String(v);
      return Number.isInteger(n) ? String(n) : n.toFixed(1);
    };
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${r.item_code ?? ""}</td>
        <td>${r.item_name ?? ""}</td>
        <td>${r.abc ?? ""}</td>
        <td>${r.xyz ?? ""}</td>
        <td>${r.class ?? ""}</td>
        <td>${r.policy ?? ""}</td>
        <td>${fmt(r.min_qty)}</td>
        <td>${fmt(r.max_qty)}</td>
        <td>${fmt(r.stock)}</td>
      `;
      tbody.appendChild(tr);
    });
  };

  const reload = async () => {
    const r = await fetch("/analytics/abcxyz/latest", { credentials: "include" });
    const data = r.ok ? await r.json() : { period: null, updated_at: null, rows: [], summary: { matrix: [], kpi: {} } };
    state = data;
    if (periodEl) periodEl.textContent = data.period || "—";
    if (updatedEl) updatedEl.textContent = data.updated_at || "—";
    renderKpis();
    renderHeatmap();
    renderTable();
  };

  if (uploader instanceof HTMLFormElement) {
    // Autofill period with current YYYY-MM if empty
    const periodInput = uploader.querySelector('input[name="period"]');
    if (periodInput instanceof HTMLInputElement && !periodInput.value) {
      const now = new Date();
      const dd = String(now.getDate()).padStart(2, '0');
      const mm = String(now.getMonth() + 1).padStart(2, '0');
      const yyyy = now.getFullYear();
      periodInput.value = `${dd}-${mm}-${yyyy}`;
    }
    uploader.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!(uploader instanceof HTMLFormElement)) return;
      const fd = new FormData(uploader);
      try {
        const resp = await fetch("/analytics/abcxyz/ingest", { method: "POST", body: fd, credentials: "include" });
        if (!resp.ok) {
          let detail = "Error al subir archivo";
          try { const data = await resp.json(); if (data && data.detail) detail = data.detail; } catch (_) {}
          throw new Error(detail);
        }
        setStatus(uploadStatus, "success", "Archivo procesado correctamente.");
        await reload();
      } catch (err) {
        setStatus(uploadStatus, "error", err instanceof Error ? err.message : String(err));
      }
    });
  }

  [fAbc, fXyz, fSearch].forEach((el) => {
    if (!el) return;
    const evt = el instanceof HTMLInputElement ? "input" : "change";
    el.addEventListener(evt, renderTable);
  });

  reload();
}

// ------------------------
// Receipts (Goods Receipt)
// ------------------------
function initReceiptsModule() {
  const root = document.querySelector('[data-receipt-app]');
  if (!root) return;
  const form = root.querySelector('[data-receipt-form]');
  const statusBox = root.querySelector('[data-receipt-status]');
  const printBtn = root.querySelector('[data-print-receipt]');
  const printNowChk = form?.querySelector('[data-print-now]');
  const printerWrapper = form?.querySelector('[data-printer-select-wrapper]');
  const printerSelect = form?.querySelector('[data-printer-select]');
  const refreshPrintersBtn = form?.querySelector('[data-refresh-printers]');
  const printerHint = form?.querySelector('[data-printer-hint]');
  if (!(form instanceof HTMLFormElement)) return;

  const rowsContainer = form.querySelector('[data-multi-rows]');
  const addRowBtn = form.querySelector('[data-add-row]');
  const codeDatalist = form.querySelector('#item_code_options');
  const nameDatalist = form.querySelector('#item_name_options');
  const ensureRemoveButtons = () => {
    if (!rowsContainer) return;
    const rows = rowsContainer.querySelectorAll('[data-row]');
    rows.forEach((row, idx) => {
      const btn = row.querySelector('[data-remove-row]');
      if (!(btn instanceof HTMLButtonElement)) return;
      btn.hidden = rows.length <= 1;
      btn.onclick = () => {
        if (rowsContainer.children.length > 1) row.remove();
        ensureRemoveButtons();
      };
    });
  };
  addRowBtn?.addEventListener('click', () => {
    const tpl = rowsContainer?.querySelector('[data-row]');
    if (!tpl || !rowsContainer) return;
    const clone = tpl.cloneNode(true);
    // clear fields
    clone.querySelectorAll('input').forEach((inp) => { if (inp instanceof HTMLInputElement) { if (inp.name==='uom') inp.value='EA'; else if (inp.name==='qty') inp.value='1'; else inp.value=''; }});
    // ensure datalist attributes exist on new inputs
    const codeInp = clone.querySelector("input[name='item_code']");
    const nameInp = clone.querySelector("input[name='item_name']");
    if (codeInp instanceof HTMLInputElement) { codeInp.setAttribute('list', 'item_code_options'); codeInp.autocomplete = 'off'; }
    if (nameInp instanceof HTMLInputElement) { nameInp.setAttribute('list', 'item_name_options'); nameInp.autocomplete = 'off'; }
    rowsContainer.appendChild(clone);
    ensureRemoveButtons();
  });
  ensureRemoveButtons();

  // Autofocus first SKU for scanner-friendly flow
  const firstCode = form.querySelector("[data-row] input[name='item_code']");
  if (firstCode instanceof HTMLInputElement) {
    firstCode.focus();
  }

  // Toggle printer UI when using local print-now
  const togglePrinterNow = () => {
    const enabled = (printNowChk instanceof HTMLInputElement) && printNowChk.checked;
    showPrinterSection(printerWrapper, enabled);
    if (enabled && (printerSelect instanceof HTMLSelectElement)) {
      listPrinters(printerSelect, printerHint instanceof HTMLElement ? printerHint : null);
    }
  };
  if (printNowChk instanceof HTMLInputElement) {
    printNowChk.addEventListener('change', togglePrinterNow);
  }
  refreshPrintersBtn?.addEventListener('click', () => {
    if (printerSelect instanceof HTMLSelectElement) {
      listPrinters(printerSelect, printerHint instanceof HTMLElement ? printerHint : null);
    }
  });
  togglePrinterNow();

  // Suggestions (autocomplete) for item_code / item_name
  let codeSuggestionMap = new Map();
  let nameSuggestionMap = new Map();
  const fetchCodeSuggestions = debounce(async (value) => {
    const items = await fetchProductSuggestions(value, 'code');
    codeSuggestionMap = new Map();
    nameSuggestionMap = new Map(nameSuggestionMap); // keep name map for cross-fill
    items.forEach((item) => {
      if (item?.item_code) codeSuggestionMap.set(String(item.item_code).toUpperCase(), item);
      if (item?.item_name) nameSuggestionMap.set(String(item.item_name).toLowerCase(), item);
    });
    renderDatalist(
      codeDatalist,
      items,
      (item) => item.item_code,
      (item) => `${item.item_code} — ${item.item_name || ''}`.trim()
    );
  });
  const fetchNameSuggestions = debounce(async (value) => {
    const items = await fetchProductSuggestions(value, 'name');
    nameSuggestionMap = new Map();
    codeSuggestionMap = new Map(codeSuggestionMap); // keep code map for cross-fill
    items.forEach((item) => {
      if (item?.item_name) nameSuggestionMap.set(String(item.item_name).toLowerCase(), item);
      if (item?.item_code) codeSuggestionMap.set(String(item.item_code).toUpperCase(), item);
    });
    renderDatalist(
      nameDatalist,
      items,
      (item) => item.item_name,
      (item) => `${item.item_name} — ${item.item_code || ''}`.trim()
    );
  });

  rowsContainer?.addEventListener('input', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const value = target.value.trim();
    if (target.name === 'item_code' && value.length >= 2) {
      fetchCodeSuggestions(value);
    } else if (target.name === 'item_name' && value.length >= 2) {
      fetchNameSuggestions(value);
    }
  });
  rowsContainer?.addEventListener('change', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const row = target.closest('[data-row]');
    if (!row) return;
    if (target.name === 'item_code') {
      const code = target.value.trim().toUpperCase();
      const match = codeSuggestionMap.get(code);
      if (match) {
        const nameInput = row.querySelector("input[name='item_name']");
        if (nameInput instanceof HTMLInputElement) nameInput.value = match.item_name || '';
      }
    } else if (target.name === 'item_name') {
      const nameKey = target.value.trim().toLowerCase();
      const match = nameSuggestionMap.get(nameKey);
      if (match) {
        const codeInput = row.querySelector("input[name='item_code']");
        if (codeInput instanceof HTMLInputElement) codeInput.value = match.item_code || '';
      }
    }
  });

  // Scanner Enter behavior: when pressing Enter on item_code, fill name (if available) and jump to qty/new row
  rowsContainer?.addEventListener('keydown', async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (event.key !== 'Enter') return;
    const row = target.closest('[data-row]');
    if (!row) return;
    if (target.name === 'item_code') {
      event.preventDefault();
      const code = target.value.trim().toUpperCase();
      if (!code) return;
      let match = null;
      // try cached
      if (typeof codeSuggestionMap !== 'undefined') {
        match = codeSuggestionMap.get(code) || null;
      }
      if (!match) {
        // fetch directly (non-debounced) to resolve name
        const items = await fetchProductSuggestions(code, 'code');
        match = items && items.length ? items[0] : null;
      }
      const nameInput = row.querySelector("input[name='item_name']");
      const qtyInput = row.querySelector("input[name='qty']");
      if (match && nameInput instanceof HTMLInputElement && !nameInput.value) {
        nameInput.value = match.item_name || '';
      }
      if (qtyInput instanceof HTMLInputElement) {
        qtyInput.focus();
        qtyInput.select();
      }
    } else if (target.name === 'qty') {
      event.preventDefault();
      // move to next row (create if needed) and focus item_code for rapid scans
      let nextRow = row.nextElementSibling;
      if (!(nextRow instanceof HTMLElement)) {
        const tpl = rowsContainer?.querySelector('[data-row]');
        if (tpl && rowsContainer) {
          const clone = tpl.cloneNode(true);
          clone.querySelectorAll('input').forEach((inp) => {
            if (inp instanceof HTMLInputElement) {
              if (inp.name==='uom') inp.value='EA'; else if (inp.name==='qty') inp.value='1'; else inp.value='';
            }
          });
          const codeInp = clone.querySelector("input[name='item_code']");
          const nameInp = clone.querySelector("input[name='item_name']");
          if (codeInp instanceof HTMLInputElement) { codeInp.setAttribute('list','item_code_options'); codeInp.autocomplete='off'; }
          if (nameInp instanceof HTMLInputElement) { nameInp.setAttribute('list','item_name_options'); nameInp.autocomplete='off'; }
          rowsContainer.appendChild(clone);
          ensureRemoveButtons();
          nextRow = clone;
        }
      }
      const nextCode = nextRow?.querySelector("input[name='item_code']");
      if (nextCode instanceof HTMLInputElement) {
        nextCode.focus();
      }
    }
  });

  let lastReceiptId = null;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearStatus(statusBox);
    try {
      const get = (name) => {
        const el = form.querySelector(`[name="${name}"]`);
        return el instanceof HTMLInputElement ? el.value.trim() : '';
      };
      const warehouse_to = get('warehouse_to') || 'MAIN';
      const reference = get('reference') || null;
      const note = get('note') || null;
      const print_all = (form.querySelector('[name="print_all"]') instanceof HTMLInputElement) ? form.querySelector('[name="print_all"]').checked : false;
      const lines = [];
      form.querySelectorAll('[data-row]').forEach((row) => {
        const val = (sel) => { const i = row.querySelector(sel); return i instanceof HTMLInputElement ? i.value.trim() : ''; };
        const qtyStr = val('input[name="qty"]') || '1';
        const qty = Math.max(1, Number.parseFloat(qtyStr) || 1);
        const payload = {
          item_code: val('input[name="item_code"]').toUpperCase(),
          item_name: val('input[name="item_name"]'),
          uom: val('input[name="uom"]') || 'EA',
          qty,
          batch: val('input[name="batch"]') || null,
          serial: val('input[name="serial"]') || null,
        };
        if (payload.item_code && payload.item_name && qty > 0) lines.push(payload);
      });
      if (!lines.length) throw new Error('Agrega al menos una línea válida.');
      const body = { warehouse_to, reference, note, lines, print_all };
      const resp = await fetch('/receipts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify(body) });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error((data && data.detail) || 'No se pudo crear la entrada');
      lastReceiptId = data.gr_id;
      const doPrintNow = (printNowChk instanceof HTMLInputElement) && printNowChk.checked;
      if (doPrintNow) {
        if (!(printerSelect instanceof HTMLSelectElement)) throw new Error('Selección de impresora no disponible.');
        const printerName = printerSelect.value;
        if (!printerName) throw new Error('Selecciona una impresora antes de imprimir.');
        for (const ln of lines) {
          const copies = Math.max(1, Math.min(50, Math.round(Number(ln.qty) || 1)));
          const preview = await postJSON('/labels/preview', { item_code: ln.item_code, item_name: ln.item_name, fecha: formatToday(), copies });
          if (!preview || !preview.zpl) throw new Error('No se pudo generar ZPL para una de las líneas.');
          await printLocally(printerName, preview.zpl);
        }
        setStatus(statusBox, 'success', `Entrada creada (${data.lines_count} líneas). Impresión local enviada (${lines.length} SKU).`);
      } else {
        setStatus(statusBox, 'success', `Entrada creada (${data.lines_count} líneas). ${data.printed ? 'Trabajos de impresión encolados.' : ''}`);
      }
    } catch (err) {
      setStatus(statusBox, 'error', err instanceof Error ? err.message : String(err));
    }
  });

  // Se elimina el uso de botones secundarios de impresión para simplificar el flujo
}
