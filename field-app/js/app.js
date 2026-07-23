import { DB } from "./db.js";
import { Api, AuthExpiredError, setSession, getCurrentUser, clearSession } from "./api.js";
import { t, getLang, setLang, toggleLang } from "./i18n.js";
import { syncAll, onSyncEvent, startAutoSync } from "./sync.js";

const root = document.getElementById("app");

const state = {
  screen: "login",
  user: null,
  online: navigator.onLine,
  catalog: { machineModels: [], machines: [], auditTypes: [], systemDefs: [] },
  currentAudit: null, // local audit object being edited
  syncStatus: "idle",
};

setLang(getLang());

// Audit types carry both a Hebrew and an English label (server fields label_he/label_en) so the
// UI only ever shows one language at a time, never "Machine Audit (בדיקה מלאה)" regardless of
// the active language toggle.
function auditTypeLabel(auditType) {
  return getLang() === "he" ? auditType.label_he : auditType.label_en;
}

// ---------- Catalog caching ----------

async function refreshCatalogFromServer() {
  try {
    const [machineModels, machines, auditTypes, systemDefs] = await Promise.all([
      Api.machineModels(),
      Api.machines(),
      Api.auditTypes(),
      Api.systemDefs(),
    ]);
    await DB.put("catalog", { key: "machineModels", data: machineModels });
    await DB.put("catalog", { key: "machines", data: machines });
    await DB.put("catalog", { key: "auditTypes", data: auditTypes });
    await DB.put("catalog", { key: "systemDefs", data: systemDefs });
    state.catalog = { machineModels, machines, auditTypes, systemDefs };
  } catch (e) {
    console.warn("catalog refresh failed (probably offline)", e);
  }
}

async function loadCatalogFromCache() {
  const [mm, m, at, sd] = await Promise.all([
    DB.get("catalog", "machineModels"),
    DB.get("catalog", "machines"),
    DB.get("catalog", "auditTypes"),
    DB.get("catalog", "systemDefs"),
  ]);
  state.catalog = {
    machineModels: mm ? mm.data : [],
    machines: m ? m.data : [],
    auditTypes: at ? at.data : [],
    systemDefs: sd ? sd.data : [],
  };
}

// ---------- Local audit helpers ----------

function newLocalAudit(machine, auditType, systemDefIds) {
  const clientUuid = crypto.randomUUID();
  const items = checklistItemsForSystems(systemDefIds);
  const results = {};
  for (const item of items) {
    results[item.id] = { result: "", comment: "", flagged_critical: false };
  }

  return {
    client_uuid: clientUuid,
    server_id: null,
    base_version: 0,
    machine_id: machine.id,
    audit_type: auditTypeLabel(auditType),
    audit_type_id: auditType.id,
    system_def_ids: systemDefIds,
    status: "draft",
    notes: "",
    started_at: new Date().toISOString(),
    completed_at: null,
    results,
    dirty: true,
    conflict: false,
  };
}

// Flattens the System -> SubModule -> Item hierarchy for the chosen systems into one ordered
// list, each item tagged with its system/sub-module context so the checklist screen can render
// grouped headings and the PDF report can do the same.
function checklistItemsForSystems(systemDefIds) {
  const items = [];
  for (const sd of state.catalog.systemDefs) {
    if (!systemDefIds.includes(sd.id)) continue;
    for (const sm of sd.sub_modules) {
      for (const item of sm.items) {
        items.push({
          ...item,
          system_id: sd.id,
          system_name: sd.name,
          system_order_index: sd.order_index,
          sub_module_id: sm.id,
          sub_module_name: sm.name,
          sub_module_order_index: sm.order_index,
        });
      }
    }
  }
  return items.sort(
    (a, b) =>
      a.system_order_index - b.system_order_index ||
      a.sub_module_order_index - b.sub_module_order_index ||
      a.order_index - b.order_index
  );
}

async function saveLocalAudit(audit) {
  audit.dirty = true;
  await DB.put("audits", audit);
}

// ---------- Rendering ----------

function el(html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

async function handleSessionExpired() {
  await clearSession();
  state.user = null;
  state.screen = "login";
  render();
  alert(t("sessionExpired"));
}

// Downloads a PDF report via an authenticated fetch (a plain <a href> to the API never sends
// the Authorization header, which is what caused the "Could not validate credentials" error).
async function downloadReport(downloadUrl, filename) {
  try {
    const objectUrl = await Api.downloadReportFile(downloadUrl);
    const link = el(`<a href="${objectUrl}" download="${filename}"></a>`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
  } catch (e) {
    if (e instanceof AuthExpiredError) {
      await handleSessionExpired();
    } else {
      alert(t("downloadError"));
    }
  }
}

// Generates a PDF report for the audit's current state (works mid-audit, before it's closed,
// as well as after submit) and renders a download button into `containerEl`. The audit must
// have synced to the server at least once -- if it hasn't yet, triggers a sync first.
async function generateAndShowReport(audit, containerEl) {
  containerEl.innerHTML = `<p>${t("loading")}</p>`;

  await syncAll();
  const synced = await DB.get("audits", audit.client_uuid);

  // syncAll() re-reads/mutates its own fresh copies from IndexedDB, not this `audit` object
  // (typically the same in-memory object as state.currentAudit) -- copy the fresher sync state
  // back onto it so screens rendered afterward from the same reference don't act on stale data
  // (e.g. re-saving a stale base_version:0 and confusing the next sync).
  if (synced) {
    audit.server_id = synced.server_id;
    audit.base_version = synced.base_version;
    audit.dirty = synced.dirty;
    audit.conflict = synced.conflict;
  }

  if (!synced || !synced.server_id || synced.dirty) {
    containerEl.innerHTML = `<p>${t("syncPending")} - ${t("generateReport")} will be available once synced online.</p>`;
    return;
  }

  try {
    const result = await Api.generateReport(synced.server_id);
    containerEl.innerHTML = `<p>${t("reportReady")}</p>`;
    const downloadBtn = el(`<button class="primary">${t("downloadReport")}</button>`);
    downloadBtn.onclick = () => downloadReport(result.download_url, `audit_${synced.server_id}_report.pdf`);
    containerEl.appendChild(downloadBtn);
  } catch (e) {
    if (e instanceof AuthExpiredError) {
      await handleSessionExpired();
      return;
    }
    containerEl.innerHTML = `<p>${t("downloadError")}</p>`;
  }
}

function render() {
  root.innerHTML = "";
  root.appendChild(topBar());

  let screenEl;
  switch (state.screen) {
    case "login":
      screenEl = renderLogin();
      break;
    case "home":
      screenEl = renderHome();
      break;
    case "select-machine":
      screenEl = renderSelectMachine();
      break;
    case "select-audit-type":
      screenEl = renderSelectAuditType();
      break;
    case "select-systems":
      screenEl = renderSelectSystems();
      break;
    case "checklist":
      screenEl = renderChecklist();
      break;
    case "review":
      screenEl = renderReview();
      break;
    default:
      screenEl = el(`<div>404</div>`);
  }
  root.appendChild(screenEl);
}

function topBar() {
  const bar = el(`
    <div class="topbar">
      <div class="topbar-title">${t("appName")}</div>
      <div class="topbar-status ${state.online ? "online" : "offline"}">${state.online ? t("online") : t("offline")}</div>
      <button class="lang-toggle" type="button">${t("langToggle")}</button>
    </div>
  `);
  bar.querySelector(".lang-toggle").onclick = () => {
    toggleLang();
    render();
  };
  return bar;
}

// ---------- Login ----------

function renderLogin() {
  const view = el(`
    <div class="screen login-screen">
      <h1>${t("appName")}</h1>
      <form class="login-form">
        <label>${t("email")}<input type="email" name="email" required autocomplete="username"></label>
        <label>${t("password")}<input type="password" name="password" required autocomplete="current-password"></label>
        <div class="error-message" hidden></div>
        <button type="submit" class="primary">${t("loginButton")}</button>
      </form>
    </div>
  `);

  const form = view.querySelector("form");
  const errorBox = view.querySelector(".error-message");

  form.onsubmit = async (event) => {
    event.preventDefault();
    const email = form.email.value.trim();
    const password = form.password.value;

    try {
      const response = await Api.login(email, password);
      await setSession(response.access_token, response.user);
      state.user = response.user;
      await refreshCatalogFromServer();
      startAutoSync();
      state.screen = "home";
      render();
    } catch (e) {
      errorBox.textContent = t("loginError");
      errorBox.hidden = false;
    }
  };

  return view;
}

// ---------- Home ----------

async function renderHomeAsync(container) {
  const localAudits = (await DB.getAll("audits")).filter((a) => a.status === "draft");
  const list = container.querySelector(".open-audits-list");
  list.innerHTML = "";

  if (localAudits.length === 0) {
    list.appendChild(el(`<p class="empty">${t("noOpenAudits")}</p>`));
    return;
  }

  for (const audit of localAudits) {
    const machine = state.catalog.machines.find((m) => m.id === audit.machine_id);
    const label = machine ? `${machine.customer} - ${machine.serial_number}` : `#${audit.machine_id}`;
    const syncLabel = audit.conflict ? t("syncError") : audit.dirty ? t("syncPending") : t("synced");
    const card = el(`
      <div class="audit-card">
        <div class="audit-card-title">${label}</div>
        <div class="audit-card-sub">${audit.audit_type} - ${new Date(audit.started_at).toLocaleDateString()}</div>
        <div class="audit-card-sync ${audit.conflict ? "conflict" : ""}">${syncLabel}</div>
      </div>
    `);
    card.onclick = () => {
      state.currentAudit = audit;
      state.screen = "checklist";
      render();
    };
    list.appendChild(card);
  }
}

function renderHome() {
  const view = el(`
    <div class="screen home-screen">
      <div class="home-actions">
        <button class="primary big" data-action="new-audit">${t("newAudit")}</button>
      </div>
      <h2>${t("openAudits")}</h2>
      <div class="open-audits-list"><p class="empty">${t("loading")}</p></div>
      <button class="link logout-btn">${t("logout")}</button>
    </div>
  `);

  view.querySelector('[data-action="new-audit"]').onclick = () => {
    state.screen = "select-machine";
    render();
  };
  view.querySelector(".logout-btn").onclick = async () => {
    await clearSession();
    state.user = null;
    state.screen = "login";
    render();
  };

  renderHomeAsync(view);
  return view;
}

// ---------- Select Machine ----------

function renderSelectMachine() {
  const view = el(`
    <div class="screen">
      <button class="link back-btn">&larr; ${t("back")}</button>
      <h2>${t("selectMachine")}</h2>
      <input type="search" class="machine-search" placeholder="${t("searchMachine")}">
      <div class="machine-list"></div>
    </div>
  `);

  view.querySelector(".back-btn").onclick = () => {
    state.screen = "home";
    render();
  };

  const listEl = view.querySelector(".machine-list");
  const searchEl = view.querySelector(".machine-search");

  function renderList(filter) {
    const term = (filter || "").toLowerCase();
    const filtered = state.catalog.machines.filter((m) =>
      !term ||
      m.customer.toLowerCase().includes(term) ||
      m.serial_number.toLowerCase().includes(term) ||
      (m.site || "").toLowerCase().includes(term)
    );

    listEl.innerHTML = "";
    for (const machine of filtered) {
      const card = el(`
        <div class="machine-card">
          <div class="machine-card-title">${machine.customer}</div>
          <div class="machine-card-sub">${machine.machine_model.name} - ${t("serial")}: ${machine.serial_number}</div>
          <div class="machine-card-sub">${machine.site || ""} ${machine.region ? "(" + machine.region + ")" : ""}</div>
        </div>
      `);
      card.onclick = () => {
        state.selectedMachine = machine;
        state.screen = "select-audit-type";
        render();
      };
      listEl.appendChild(card);
    }
  }

  searchEl.oninput = () => renderList(searchEl.value);
  renderList("");

  return view;
}

// ---------- Select Audit Type ----------

function renderSelectAuditType() {
  const machine = state.selectedMachine;

  const view = el(`
    <div class="screen">
      <button class="link back-btn">&larr; ${t("back")}</button>
      <h2>${t("selectAuditType")}</h2>
      <div class="machine-summary">${machine.customer} - ${machine.serial_number}</div>
      <div class="audit-type-list"></div>
    </div>
  `);

  view.querySelector(".back-btn").onclick = () => {
    state.screen = "select-machine";
    render();
  };

  const listEl = view.querySelector(".audit-type-list");

  if (state.catalog.auditTypes.length === 0) {
    listEl.appendChild(el(`<p class="empty">${t("noAuditTypes")}</p>`));
  }

  for (const auditType of state.catalog.auditTypes) {
    const systemCount = state.catalog.systemDefs.filter((s) => s.audit_type_id === auditType.id).length;
    const card = el(`
      <div class="machine-card">
        <div class="machine-card-title">${auditTypeLabel(auditType)}</div>
        <div class="machine-card-sub">${systemCount} ${t("system")}</div>
      </div>
    `);
    card.onclick = () => {
      state.selectedAuditType = auditType;
      state.screen = "select-systems";
      render();
    };
    listEl.appendChild(card);
  }

  return view;
}

// ---------- Select Systems ----------

function renderSelectSystems() {
  const machine = state.selectedMachine;
  const auditType = state.selectedAuditType;
  const systems = state.catalog.systemDefs.filter((s) => s.audit_type_id === auditType.id);

  const view = el(`
    <div class="screen">
      <button class="link back-btn">&larr; ${t("back")}</button>
      <h2>${t("selectSystems")}</h2>
      <div class="machine-summary">${machine.customer} - ${machine.serial_number} - ${auditTypeLabel(auditType)}</div>
      <div class="systems-list"></div>
      <button class="primary continue-btn" disabled>${t("continue")}</button>
    </div>
  `);

  view.querySelector(".back-btn").onclick = () => {
    state.screen = "select-audit-type";
    render();
  };

  const listEl = view.querySelector(".systems-list");
  const continueBtn = view.querySelector(".continue-btn");

  if (systems.length === 0) {
    listEl.appendChild(el(`<p class="empty">${t("noSystems")}</p>`));
  }

  const selected = new Set();

  for (const system of systems) {
    const itemCount = system.sub_modules.reduce((sum, sm) => sum + sm.items.length, 0);
    const row = el(`
      <label class="system-row">
        <input type="checkbox" value="${system.id}">
        <span>${system.name} (${itemCount})</span>
      </label>
    `);
    row.querySelector("input").onchange = (e) => {
      if (e.target.checked) selected.add(system.id);
      else selected.delete(system.id);
      continueBtn.disabled = selected.size === 0;
    };
    listEl.appendChild(row);
  }

  continueBtn.onclick = async () => {
    const audit = newLocalAudit(machine, auditType, Array.from(selected));
    await saveLocalAudit(audit);
    state.currentAudit = audit;
    state.screen = "checklist";
    render();
  };

  return view;
}

// ---------- Checklist ----------

const RESULT_OPTIONS = [
  { value: "", labelKey: "notChecked" },
  { value: "Pass", labelKey: "pass" },
  { value: "Near Fail", labelKey: "nearFail" },
  { value: "Fail", labelKey: "fail" },
  { value: "N/A", labelKey: "na" },
];

async function renderChecklistAttachments(container, audit, checklistItemId) {
  const all = await DB.getAll("attachments");
  const forItem = all.filter(
    (a) => a.audit_client_uuid === audit.client_uuid && a.checklist_item_id === checklistItemId
  );
  container.innerHTML = "";
  for (const attachment of forItem) {
    const src = attachment.blob ? URL.createObjectURL(attachment.blob) : "/" + attachment.server_file_path;
    const thumb = el(`<img class="photo-thumb" src="${src}">`);
    container.appendChild(thumb);
  }
}

function renderChecklist() {
  const audit = state.currentAudit;
  const items = checklistItemsForSystems(audit.system_def_ids);
  const doneCount = items.filter((i) => {
    const r = audit.results[i.id];
    return r && (r.result || r.comment);
  }).length;

  const view = el(`
    <div class="screen checklist-screen">
      <button class="link back-btn">&larr; ${t("backToHome")}</button>
      <div class="progress-bar"><div class="progress-fill" style="width:${items.length ? (doneCount / items.length) * 100 : 0}%"></div></div>
      <div class="progress-label">${t("progress", doneCount, items.length)}</div>
      <div class="checklist-items"></div>
      <div class="checklist-actions">
        <button class="secondary save-exit-btn">${t("saveDraft")}</button>
        <button class="secondary report-btn">${t("generateReport")}</button>
        <button class="primary review-btn">${t("reviewAndSubmit")}</button>
      </div>
      <div class="report-area"></div>
    </div>
  `);

  view.querySelector(".back-btn").onclick = async () => {
    await saveLocalAudit(audit);
    syncAll();
    state.screen = "home";
    render();
  };
  view.querySelector(".save-exit-btn").onclick = async () => {
    await saveLocalAudit(audit);
    syncAll();
    state.screen = "home";
    render();
  };
  view.querySelector(".review-btn").onclick = async () => {
    await saveLocalAudit(audit);
    state.screen = "review";
    render();
  };
  view.querySelector(".report-btn").onclick = async () => {
    await saveLocalAudit(audit);
    await generateAndShowReport(audit, view.querySelector(".report-area"));
  };

  const container = view.querySelector(".checklist-items");
  let currentSystem = null;
  let currentSubModule = null;
  let itemNumber = 0;

  for (const item of items) {
    if (item.system_name !== currentSystem) {
      container.appendChild(el(`<h2 class="system-heading">${item.system_name}</h2>`));
      currentSystem = item.system_name;
      currentSubModule = null;
    }
    if (item.sub_module_name !== currentSubModule) {
      container.appendChild(el(`<h3 class="module-heading">${item.sub_module_name}</h3>`));
      currentSubModule = item.sub_module_name;
      itemNumber = 0;
    }
    itemNumber += 1;

    const resultState = audit.results[item.id] || { result: "", comment: "", flagged_critical: false };

    const row = el(`
      <div class="checklist-item">
        <div class="checklist-item-desc">${itemNumber}. ${item.description}</div>
        <div class="result-buttons"></div>
        <textarea class="comment-input" placeholder="${t("comment")}">${resultState.comment}</textarea>
        <label class="critical-flag">
          <input type="checkbox" ${resultState.flagged_critical ? "checked" : ""}>
          ${t("criticalFlag")}
        </label>
        <div class="photo-section">
          <div class="photo-thumbs"></div>
          <label class="photo-add-btn">
            ${t("addPhoto")}
            <input type="file" accept="image/*" capture="environment" hidden>
          </label>
        </div>
      </div>
    `);

    const resultButtonsEl = row.querySelector(".result-buttons");
    for (const option of RESULT_OPTIONS) {
      if (option.value === "") continue;
      const btn = el(
        `<button type="button" class="result-btn result-${option.value.replace(/\s+/g, "-")} ${resultState.result === option.value ? "selected" : ""}">${t(option.labelKey)}</button>`
      );
      btn.onclick = async () => {
        resultState.result = resultState.result === option.value ? "" : option.value;
        audit.results[item.id] = resultState;
        row.querySelectorAll(".result-btn").forEach((b) => b.classList.remove("selected"));
        if (resultState.result === option.value) btn.classList.add("selected");
        await saveLocalAudit(audit);
        updateProgress();
      };
      resultButtonsEl.appendChild(btn);
    }

    row.querySelector(".comment-input").oninput = async (e) => {
      resultState.comment = e.target.value;
      audit.results[item.id] = resultState;
      await saveLocalAudit(audit);
      updateProgress();
    };

    row.querySelector(".critical-flag input").onchange = async (e) => {
      resultState.flagged_critical = e.target.checked;
      audit.results[item.id] = resultState;
      await saveLocalAudit(audit);
    };

    const fileInput = row.querySelector('input[type="file"]');
    fileInput.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const attachment = {
        client_uuid: crypto.randomUUID(),
        audit_client_uuid: audit.client_uuid,
        checklist_item_id: item.id,
        blob: file,
        file_name: file.name,
        taken_at: new Date().toISOString(),
        uploaded: false,
      };
      await DB.put("attachments", attachment);
      await renderChecklistAttachments(row.querySelector(".photo-thumbs"), audit, item.id);
      await saveLocalAudit(audit);
      syncAll();
    };

    renderChecklistAttachments(row.querySelector(".photo-thumbs"), audit, item.id);

    container.appendChild(row);
  }

  function updateProgress() {
    const done = items.filter((i) => {
      const r = audit.results[i.id];
      return r && (r.result || r.comment);
    }).length;
    view.querySelector(".progress-fill").style.width = `${items.length ? (done / items.length) * 100 : 0}%`;
    view.querySelector(".progress-label").textContent = t("progress", done, items.length);
  }

  return view;
}

// ---------- Review ----------

function renderReview() {
  const audit = state.currentAudit;
  const items = checklistItemsForSystems(audit.system_def_ids);

  let pass = 0, nearFail = 0, fail = 0, na = 0, critical = 0;
  for (const item of items) {
    const r = audit.results[item.id];
    if (!r) continue;
    if (r.result === "Pass") pass++;
    else if (r.result === "Near Fail") nearFail++;
    else if (r.result === "Fail") fail++;
    else if (r.result === "N/A") na++;
    if (r.flagged_critical) critical++;
  }

  const view = el(`
    <div class="screen review-screen">
      <button class="link back-btn">&larr; ${t("back")}</button>
      <h2>${t("review")}</h2>
      <div class="review-stats">
        <div class="stat"><span>${t("pass")}</span><b>${pass}</b></div>
        <div class="stat"><span>${t("nearFail")}</span><b>${nearFail}</b></div>
        <div class="stat"><span>${t("fail")}</span><b>${fail}</b></div>
        <div class="stat"><span>${t("na")}</span><b>${na}</b></div>
        <div class="stat critical"><span>${t("criticalFlag")}</span><b>${critical}</b></div>
      </div>
      <button class="primary submit-btn">${t("submitAudit")}</button>
      <div class="report-area"></div>
    </div>
  `);

  view.querySelector(".back-btn").onclick = () => {
    state.screen = "checklist";
    render();
  };

  view.querySelector(".submit-btn").onclick = async () => {
    if (!confirm(t("confirmSubmit"))) return;

    audit.status = "completed";
    audit.completed_at = new Date().toISOString();
    await saveLocalAudit(audit);

    const reportArea = view.querySelector(".report-area");
    await generateAndShowReport(audit, reportArea);

    const backBtn = el(`<button class="secondary" style="margin-top:16px">${t("backToHome")}</button>`);
    backBtn.onclick = () => {
      state.screen = "home";
      render();
    };
    reportArea.appendChild(backBtn);
  };

  return view;
}

// ---------- Boot ----------

async function boot() {
  onSyncEvent((event) => {
    if (event.type === "done") {
      if (state.screen === "home") render();
    }
  });

  window.addEventListener("online", () => {
    state.online = true;
    render();
  });
  window.addEventListener("offline", () => {
    state.online = false;
    render();
  });

  const user = await getCurrentUser();
  if (user) {
    state.user = user;
    await loadCatalogFromCache();
    refreshCatalogFromServer().then(() => {
      if (state.screen === "select-machine" || state.screen === "home") render();
    });
    startAutoSync();
    state.screen = "home";
  } else {
    state.screen = "login";
  }

  render();
}

boot();
