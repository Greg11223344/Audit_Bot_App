import { Api, getToken, getUser, setSession, clearSession } from "./api.js";
import { t, getLang, setLang, toggleLang } from "./i18n.js";
import { renderBarChart } from "./chart.js";

const root = document.getElementById("app");
setLang(getLang());

const state = {
  user: getUser(),
  machinesCache: [],
};

// Audit types carry both a Hebrew and an English label (label_he/label_en) so the UI only ever
// shows one language, never "Machine Audit (בדיקה מלאה)" regardless of the active language.
function auditTypeLabel(auditType) {
  return getLang() === "he" ? auditType.label_he : auditType.label_en;
}

function el(html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}

function fmtShortDate(isoDate) {
  const d = new Date(isoDate);
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

// Relative severity tier from a findings count, used for color-coding (not an absolute clinical
// threshold -- just enough buckets to make the worst machines visually pop in a short list).
function severityTier(findings) {
  if (findings >= 15) return "severity-high";
  if (findings >= 5) return "severity-medium";
  return "severity-low";
}

function failRateSeverityClass(percent) {
  if (percent >= 30) return "severity-high";
  if (percent >= 10) return "severity-medium";
  return "severity-low";
}

function skeletonRows(count, cols) {
  return Array.from({ length: count })
    .map(() => `<tr class="skeleton-row">${'<td><div class="skeleton-bar"></div></td>'.repeat(cols)}</tr>`)
    .join("");
}

// ---------- Shell ----------

function renderShell(activeRoute) {
  const isAdmin = state.user && state.user.role === "admin";
  const nav = [
    ["#/dashboard", t("dashboard")],
    ["#/audits", t("audits")],
    ["#/tasks", t("tasks")],
  ];
  if (isAdmin) {
    nav.push(["#/machines", t("machines")]);
    nav.push(["#/users", t("users")]);
  }

  const shell = el(`
    <div class="shell">
      <div class="topbar">
        <div class="topbar-title">${t("appName")}</div>
        <nav class="topnav"></nav>
        <button class="lang-toggle">${t("langToggle")}</button>
        <button class="logout-btn">${t("logout")}</button>
      </div>
      <div class="content"></div>
    </div>
  `);

  const navEl = shell.querySelector(".topnav");
  for (const [href, label] of nav) {
    const a = el(`<a href="${href}" class="${activeRoute === href ? "active" : ""}">${label}</a>`);
    navEl.appendChild(a);
  }

  shell.querySelector(".lang-toggle").onclick = () => {
    toggleLang();
    router();
  };
  shell.querySelector(".logout-btn").onclick = () => {
    clearSession();
    location.hash = "#/login";
  };

  return shell;
}

function setContent(shell, node) {
  const content = shell.querySelector(".content");
  content.innerHTML = "";
  content.appendChild(node);
}

// ---------- Login ----------

function renderLogin() {
  const view = el(`
    <div class="login-screen">
      <h1>${t("appName")}</h1>
      <form class="login-form">
        <label>${t("email")}<input type="email" name="email" required></label>
        <label>${t("password")}<input type="password" name="password" required></label>
        <div class="error-message" hidden></div>
        <button type="submit" class="primary">${t("loginButton")}</button>
      </form>
    </div>
  `);

  const form = view.querySelector("form");
  const errorBox = view.querySelector(".error-message");

  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await Api.login(form.email.value.trim(), form.password.value);
      setSession(response.access_token, response.user);
      state.user = response.user;
      location.hash = "#/dashboard";
    } catch (err) {
      errorBox.textContent = t("loginError");
      errorBox.hidden = false;
    }
  };

  root.innerHTML = "";
  root.appendChild(el(`<div class="topbar solo"><div class="topbar-title">${t("appName")}</div></div>`));
  root.appendChild(view);
}

// ---------- Dashboard ----------

async function renderDashboard() {
  const shell = renderShell("#/dashboard");
  root.innerHTML = "";
  root.appendChild(shell);

  const skeleton = el(`
    <div class="dashboard fade-in">
      <div class="kpi-grid">
        <div class="kpi-card skeleton"><div class="skeleton-bar"></div><div class="skeleton-bar wide"></div></div>
        <div class="kpi-card skeleton"><div class="skeleton-bar"></div><div class="skeleton-bar wide"></div></div>
        <div class="kpi-card skeleton"><div class="skeleton-bar"></div><div class="skeleton-bar wide"></div></div>
      </div>
      <h2>${t("trend")}</h2>
      <div class="chart-card skeleton"><div class="skeleton-bar" style="height:180px"></div></div>
      <h2>${t("topMachines")}</h2>
      <table class="data-table"><thead><tr><th>${t("customer")}</th><th>${t("serial")}</th><th>${t("severity")}</th><th>#</th></tr></thead>
        <tbody>${skeletonRows(3, 4)}</tbody>
      </table>
    </div>
  `);
  setContent(shell, skeleton);

  const kpis = await Api.kpis();

  const monthStart = new Date();
  monthStart.setDate(1);
  monthStart.setHours(0, 0, 0, 0);

  const view = el(`
    <div class="dashboard fade-in">
      <div class="kpi-grid">
        <a class="kpi-card" href="#/audits?started_after=${encodeURIComponent(monthStart.toISOString())}">
          <span>${t("auditsThisMonth")}</span><b>${kpis.audits_this_month}</b>
        </a>
        <a class="kpi-card" href="#/tasks?status=open">
          <span>${t("openTasks")}</span><b>${kpis.open_tasks}</b>
        </a>
        <a class="kpi-card ${failRateSeverityClass(kpis.fail_rate_percent)}" href="#/audits">
          <span>${t("failRate")}</span><b>${kpis.fail_rate_percent}%</b>
        </a>
      </div>

      <h2>${t("trend")}</h2>
      <div class="chart-card">
        <div class="trend-chart"></div>
      </div>

      <h2>${t("topMachines")}</h2>
      <table class="data-table">
        <thead><tr><th>${t("customer")}</th><th>${t("serial")}</th><th>${t("severity")}</th><th>#</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  `);

  if (kpis.audits_trend && kpis.audits_trend.length) {
    renderBarChart(
      view.querySelector(".trend-chart"),
      kpis.audits_trend.map((t) => ({ label: fmtShortDate(t.period), value: t.count })),
      { color: "#52796f" }
    );
  }

  const tbody = view.querySelector("tbody");
  if (kpis.top_machines_by_findings.length === 0) {
    tbody.appendChild(el(`<tr><td colspan="4">${t("noFindings")}</td></tr>`));
  }
  const maxFindings = Math.max(1, ...kpis.top_machines_by_findings.map((r) => r.findings));
  for (const row of kpis.top_machines_by_findings) {
    const tier = severityTier(row.findings);
    const barPercent = Math.round((row.findings / maxFindings) * 100);
    const tr = el(`
      <tr class="clickable-row">
        <td>${row.customer}</td>
        <td>${row.serial_number}</td>
        <td>
          <div class="severity-bar-track"><div class="severity-bar-fill ${tier}" style="width:${barPercent}%"></div></div>
        </td>
        <td>${row.findings}</td>
      </tr>
    `);
    tr.onclick = () => {
      location.hash = `#/machine/${row.machine_id}`;
    };
    tbody.appendChild(tr);
  }

  setContent(shell, view);
}

// ---------- Audits ----------

async function renderAuditsList(initialParams = new URLSearchParams()) {
  const shell = renderShell("#/audits");
  root.innerHTML = "";
  root.appendChild(shell);

  const isAdmin = state.user && state.user.role === "admin";
  const startedAfter = initialParams.get("started_after") || "";
  const machineIdFilter = initialParams.get("machine_id") || "";

  const view = el(`
    <div class="fade-in">
      <h2>${t("audits")}</h2>
      <div class="filter-chip-row"></div>
      <div class="filters">
        <select class="status-filter">
          <option value="">${t("all")}</option>
          <option value="draft" ${initialParams.get("status") === "draft" ? "selected" : ""}>${t("draft")}</option>
          <option value="completed" ${initialParams.get("status") === "completed" ? "selected" : ""}>${t("completed")}</option>
        </select>
        <select class="system-filter">
          <option value="">${t("filterSystem")}: ${t("all")}</option>
        </select>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>${t("customer")}</th><th>${t("serial")}</th><th>${t("system")}</th><th>${t("engineer")}</th>
            <th>${t("status")}</th><th>${t("date")}</th><th></th>${isAdmin ? "<th></th>" : ""}
          </tr>
        </thead>
        <tbody>${skeletonRows(4, isAdmin ? 8 : 7)}</tbody>
      </table>
    </div>
  `);

  if (startedAfter) {
    view.querySelector(".filter-chip-row").appendChild(
      el(`<div class="filter-chip">${t("showingThisMonth")} <a href="#/audits">${t("clearFilter")}</a></div>`)
    );
  }

  const tbody = view.querySelector("tbody");
  const statusFilter = view.querySelector(".status-filter");
  const systemFilter = view.querySelector(".system-filter");

  // Two fetches: the filter dropdown should only offer currently-selectable systems, but
  // resolving each row's system name (below) must also cover inactive/legacy systems --
  // otherwise a historical audit tied to a retired system shows "#26" instead of its name.
  const [activeSystemDefs, allSystemDefs] = await Promise.all([
    Api.systemDefs(),
    Api.systemDefs(undefined, { includeInactive: true }),
  ]);
  const systemById = {};
  for (const s of allSystemDefs) {
    systemById[s.id] = s;
  }
  for (const s of activeSystemDefs) {
    systemFilter.appendChild(el(`<option value="${s.id}">${s.name}</option>`));
  }

  async function load() {
    tbody.innerHTML = skeletonRows(4, isAdmin ? 8 : 7);
    const params = {};
    if (statusFilter.value) params.status = statusFilter.value;
    if (systemFilter.value) params.system_def_id = systemFilter.value;
    if (startedAfter) params.started_after = startedAfter;
    if (machineIdFilter) params.machine_id = machineIdFilter;
    const audits = await Api.audits(params);

    tbody.innerHTML = "";
    if (audits.length === 0) {
      tbody.appendChild(el(`<tr><td colspan="${isAdmin ? 8 : 7}">${t("noData")}</td></tr>`));
      return;
    }

    for (const audit of audits) {
      const systemNames = audit.system_def_ids.map((id) => systemById[id]?.name || `#${id}`).join(", ");
      const row = el(`
        <tr>
          <td>${audit.machine.customer}</td>
          <td>${audit.machine.serial_number}</td>
          <td>${systemNames}</td>
          <td>${audit.engineer.name}</td>
          <td><span class="badge badge-${audit.status}">${t(audit.status)}</span></td>
          <td>${fmtDate(audit.started_at)}</td>
          <td><a href="#/audits/${audit.id}">${t("viewAudit")}</a></td>
          ${isAdmin ? '<td><button type="button" class="danger delete-audit-btn">' + t("deleteAudit") + "</button></td>" : ""}
        </tr>
      `);
      if (isAdmin) {
        row.querySelector(".delete-audit-btn").onclick = async () => {
          if (!confirm(t("confirmDeleteAudit"))) return;
          await Api.deleteAudit(audit.id);
          row.remove();
          if (!tbody.hasChildNodes()) {
            tbody.appendChild(el(`<tr><td colspan="${isAdmin ? 8 : 7}">${t("noData")}</td></tr>`));
          }
        };
      }
      tbody.appendChild(row);
    }
  }

  statusFilter.onchange = load;
  systemFilter.onchange = load;
  await load();

  setContent(shell, view);
}

async function renderAuditDetail(id) {
  const shell = renderShell("#/audits");
  root.innerHTML = "";
  root.appendChild(shell);

  const audit = await Api.audit(id);

  const view = el(`
    <div>
      <a href="#/audits" class="back-link">&larr; ${t("back")}</a>
      <h2>${t("auditDetails")}</h2>
      <div class="detail-grid">
        <div><span>${t("customer")}</span><b>${audit.machine.customer}</b></div>
        <div><span>${t("serial")}</span><b>${audit.machine.serial_number}</b></div>
        <div><span>${t("engineer")}</span><b>${audit.engineer.name}</b></div>
        <div><span>${t("status")}</span><b>${t(audit.status)}</b></div>
        <div><span>${t("date")}</span><b>${fmtDate(audit.started_at)}</b></div>
      </div>
      <button class="primary report-btn">${t("generateReport")}</button>
      <div class="report-result"></div>
      <h3>${t("results")}</h3>
      <div class="results-list"></div>
    </div>
  `);

  view.querySelector(".report-btn").onclick = async () => {
    const box = view.querySelector(".report-result");
    try {
      const result = await Api.generateReport(audit.id);
      box.innerHTML = "";
      const downloadBtn = el(`<button class="primary">${t("downloadReport")}</button>`);
      downloadBtn.onclick = async () => {
        try {
          const objectUrl = await Api.downloadReportFile(result.download_url);
          const link = el(`<a href="${objectUrl}" download="audit_${audit.id}_report.pdf"></a>`);
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
        } catch (e) {
          if (e.status !== 401) alert(t("downloadError"));
        }
      };
      box.appendChild(downloadBtn);
    } catch (e) {
      if (e.status !== 401) alert(t("downloadError"));
    }
  };

  const attachmentsByResult = {};
  for (const a of audit.attachments) {
    (attachmentsByResult[a.audit_result_id] ||= []).push(a);
  }

  const answeredResults = audit.results.filter((r) => r.result || r.comment);
  const sortedResults = [...answeredResults].sort(
    (a, b) => a.system_name.localeCompare(b.system_name) || a.sub_module_name.localeCompare(b.sub_module_name)
  );

  const list = view.querySelector(".results-list");
  let currentSystem = null;
  let currentSubModule = null;

  for (const r of sortedResults) {
    if (r.system_name !== currentSystem) {
      list.appendChild(el(`<div class="result-system-heading">${r.system_name}</div>`));
      currentSystem = r.system_name;
      currentSubModule = null;
    }
    if (r.sub_module_name !== currentSubModule) {
      list.appendChild(el(`<div class="result-submodule-heading">${r.sub_module_name}</div>`));
      currentSubModule = r.sub_module_name;
    }

    const row = el(`
      <div class="result-row ${r.flagged_critical ? "critical" : ""}">
        <div class="result-row-desc">${r.description}</div>
        <div class="result-row-main"><b>${r.result || "-"}</b> ${r.flagged_critical ? '<span class="critical-tag">CRITICAL</span>' : ""}</div>
        <div class="result-row-comment">${r.comment || ""}</div>
        <div class="result-row-photos"></div>
      </div>
    `);
    const photosEl = row.querySelector(".result-row-photos");
    for (const attachment of attachmentsByResult[r.id] || []) {
      photosEl.appendChild(el(`<img class="result-photo" src="/${attachment.file_path}">`));
    }
    list.appendChild(row);
  }

  if (!list.hasChildNodes()) {
    list.appendChild(el(`<p>${t("noData")}</p>`));
  }

  setContent(shell, view);
}

// ---------- Tasks ----------

async function renderTasks(initialParams = new URLSearchParams()) {
  const shell = renderShell("#/tasks");
  root.innerHTML = "";
  root.appendChild(shell);

  const initialStatus = initialParams.get("status") || "";

  const view = el(`
    <div class="fade-in">
      <h2>${t("tasks")}</h2>
      <div class="filters">
        <select class="status-filter">
          <option value="">${t("all")}</option>
          <option value="open" ${initialStatus === "open" ? "selected" : ""}>${t("taskStatusOpen")}</option>
          <option value="in_progress" ${initialStatus === "in_progress" ? "selected" : ""}>${t("taskStatusInProgress")}</option>
          <option value="closed" ${initialStatus === "closed" ? "selected" : ""}>${t("taskStatusClosed")}</option>
        </select>
      </div>
      <div class="tasks-list"></div>
    </div>
  `);

  const listEl = view.querySelector(".tasks-list");
  const statusFilter = view.querySelector(".status-filter");

  async function load() {
    listEl.innerHTML = `<div class="task-card skeleton"><div class="skeleton-bar wide"></div><div class="skeleton-bar"></div></div>`;
    const tasks = await Api.tasks(statusFilter.value);
    listEl.innerHTML = "";

    if (tasks.length === 0) {
      listEl.appendChild(el(`<p class="empty">${t("noData")}</p>`));
      return;
    }

    for (const task of tasks) {
      const card = el(`
        <div class="task-card">
          <div class="task-desc">${task.description}</div>
          <div class="task-meta">Audit #${task.audit_id} - ${fmtDate(task.created_at)}</div>
          <select class="task-status-select">
            <option value="open" ${task.status === "open" ? "selected" : ""}>${t("taskStatusOpen")}</option>
            <option value="in_progress" ${task.status === "in_progress" ? "selected" : ""}>${t("taskStatusInProgress")}</option>
            <option value="closed" ${task.status === "closed" ? "selected" : ""}>${t("taskStatusClosed")}</option>
          </select>
          <textarea class="task-note" placeholder="${t("resolutionNote")}">${task.resolution_note || ""}</textarea>
          <a href="#/audits/${task.audit_id}">${t("viewAudit")}</a>
        </div>
      `);

      card.querySelector(".task-status-select").onchange = async (e) => {
        await Api.updateTask(task.id, { status: e.target.value });
      };
      card.querySelector(".task-note").onblur = async (e) => {
        await Api.updateTask(task.id, { resolution_note: e.target.value });
      };

      listEl.appendChild(card);
    }
  }

  statusFilter.onchange = load;
  await load();

  setContent(shell, view);
}

// ---------- Machines / Systems (admin) ----------

async function renderMachines() {
  const shell = renderShell("#/machines");
  root.innerHTML = "";
  root.appendChild(shell);

  const view = el(`
    <div>
      <h2>${t("machines")}</h2>

      <details open>
        <summary>${t("machineModel")}</summary>
        <div class="model-list"></div>
        <form class="add-model-form inline-form">
          <input name="name" placeholder="${t("name")}" required>
          <button type="submit">${t("addMachineModel")}</button>
        </form>
      </details>

      <details>
        <summary>${t("machines")}</summary>
        <table class="data-table"><thead><tr><th>${t("customer")}</th><th>${t("serial")}</th><th>${t("machineModel")}</th><th>${t("region")}</th></tr></thead><tbody class="machines-body"></tbody></table>
        <form class="add-machine-form inline-form">
          <select name="machine_model_id"></select>
          <input name="customer" placeholder="${t("customer")}" required>
          <input name="serial_number" placeholder="${t("serial")}" required>
          <input name="site" placeholder="${t("site")}">
          <input name="region" placeholder="${t("region")}">
          <button type="submit">${t("addMachine")}</button>
        </form>
      </details>

      <details>
        <summary>${t("addSystem")}</summary>
        <div class="systems-body"></div>
        <form class="add-system-form inline-form">
          <select name="audit_type_id"></select>
          <input name="name" placeholder="${t("name")}" required>
          <button type="submit">${t("addSystem")}</button>
        </form>
      </details>
    </div>
  `);

  const machineModels = await Api.machineModels();
  const machines = await Api.machines();
  const auditTypes = await Api.auditTypes();
  const systemDefs = await Api.systemDefs();

  const modelListEl = view.querySelector(".model-list");
  modelListEl.innerHTML = machineModels.map((m) => `<div class="chip">${m.name}</div>`).join("") || t("noData");

  for (const select of view.querySelectorAll('select[name="machine_model_id"]')) {
    select.innerHTML = machineModels.map((m) => `<option value="${m.id}">${m.name}</option>`).join("");
  }
  for (const select of view.querySelectorAll('select[name="audit_type_id"]')) {
    select.innerHTML = auditTypes.map((at) => `<option value="${at.id}">${auditTypeLabel(at)}</option>`).join("");
  }

  const machinesBody = view.querySelector(".machines-body");
  for (const m of machines) {
    machinesBody.appendChild(
      el(`<tr><td>${m.customer}</td><td>${m.serial_number}</td><td>${m.machine_model.name}</td><td>${m.region || ""}</td></tr>`)
    );
  }

  const systemsBody = view.querySelector(".systems-body");
  for (const at of auditTypes) {
    const group = el(`<div class="system-group"><b>${auditTypeLabel(at)}</b></div>`);
    const systemsForType = systemDefs.filter((s) => s.audit_type_id === at.id);
    for (const s of systemsForType) {
      const count = s.sub_modules.reduce((sum, sm) => sum + sm.items.length, 0);
      group.appendChild(el(`<div class="chip">${s.name} (${count})</div>`));
    }
    systemsBody.appendChild(group);
  }

  view.querySelector(".add-model-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    await Api.createMachineModel(form.name.value.trim());
    renderMachines();
  };

  view.querySelector(".add-machine-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    await Api.createMachine({
      machine_model_id: Number(form.machine_model_id.value),
      customer: form.customer.value.trim(),
      serial_number: form.serial_number.value.trim(),
      site: form.site.value.trim(),
      region: form.region.value.trim(),
    });
    renderMachines();
  };

  view.querySelector(".add-system-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    await Api.createSystemDef({ audit_type_id: Number(form.audit_type_id.value), name: form.name.value.trim() });
    renderMachines();
  };

  setContent(shell, view);
}

// ---------- Machine Detail ----------

async function renderMachineDetail(machineId) {
  const shell = renderShell("#/audits");
  root.innerHTML = "";
  root.appendChild(shell);

  const skeleton = el(`
    <div class="fade-in">
      <a href="#/dashboard" class="back-link">&larr; ${t("back")}</a>
      <h2>${t("machineDetails")}</h2>
      <div class="kpi-grid">
        <div class="kpi-card skeleton"><div class="skeleton-bar wide"></div></div>
        <div class="kpi-card skeleton"><div class="skeleton-bar wide"></div></div>
        <div class="kpi-card skeleton"><div class="skeleton-bar wide"></div></div>
      </div>
      <table class="data-table"><tbody>${skeletonRows(3, 6)}</tbody></table>
    </div>
  `);
  setContent(shell, skeleton);

  const [machines, audits] = await Promise.all([
    Api.machines(),
    Api.audits({ machine_id: machineId }),
  ]);
  const machine = machines.find((m) => String(m.id) === String(machineId));

  let totalFindings = 0;
  for (const audit of audits) {
    totalFindings += audit.results.filter((r) => r.result === "Fail" || r.result === "Near Fail").length;
  }

  const view = el(`
    <div class="fade-in">
      <a href="#/dashboard" class="back-link">&larr; ${t("back")}</a>
      <h2>${t("machineDetails")}</h2>
      <div class="detail-grid">
        <div><span>${t("customer")}</span><b>${machine ? machine.customer : "-"}</b></div>
        <div><span>${t("serial")}</span><b>${machine ? machine.serial_number : machineId}</b></div>
        <div><span>${t("machineModel")}</span><b>${machine ? machine.machine_model.name : "-"}</b></div>
        <div><span>${t("site")}</span><b>${machine ? machine.site : "-"}</b></div>
        <div><span>${t("region")}</span><b>${machine ? machine.region : "-"}</b></div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card"><span>${t("totalAudits")}</span><b>${audits.length}</b></div>
        <div class="kpi-card"><span>${t("totalFindings")}</span><b>${totalFindings}</b></div>
        <div class="kpi-card ${severityTier(totalFindings)}"><span>${t("severity")}</span><b>${t(severityTier(totalFindings).replace("severity-", ""))}</b></div>
      </div>
      <h3>${t("audits")}</h3>
      <table class="data-table">
        <thead><tr><th>${t("system")}</th><th>${t("engineer")}</th><th>${t("status")}</th><th>${t("date")}</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  `);

  // include_inactive: this page shows historical audits too, which may reference retired/legacy
  // systems -- without it those rows would show "#26" instead of the system's name.
  const systemDefs = await Api.systemDefs(undefined, { includeInactive: true });
  const systemById = Object.fromEntries(systemDefs.map((s) => [s.id, s]));

  const tbody = view.querySelector("tbody");
  if (audits.length === 0) {
    tbody.appendChild(el(`<tr><td colspan="5">${t("noData")}</td></tr>`));
  }
  for (const audit of audits) {
    const systemNames = audit.system_def_ids.map((id) => systemById[id]?.name || `#${id}`).join(", ");
    tbody.appendChild(
      el(`
        <tr>
          <td>${systemNames}</td>
          <td>${audit.engineer.name}</td>
          <td><span class="badge badge-${audit.status}">${t(audit.status)}</span></td>
          <td>${fmtDate(audit.started_at)}</td>
          <td><a href="#/audits/${audit.id}">${t("viewAudit")}</a></td>
        </tr>
      `)
    );
  }

  setContent(shell, view);
}

// ---------- Users (admin) ----------

async function renderUsers() {
  const shell = renderShell("#/users");
  root.innerHTML = "";
  root.appendChild(shell);

  const view = el(`
    <div>
      <h2>${t("users")}</h2>
      <table class="data-table">
        <thead><tr><th>${t("name")}</th><th>${t("email")}</th><th>${t("role")}</th><th>${t("active")}</th></tr></thead>
        <tbody class="users-body"></tbody>
      </table>
      <form class="add-user-form inline-form">
        <input name="name" placeholder="${t("name")}" required>
        <input name="email" type="email" placeholder="${t("email")}" required>
        <input name="password" type="password" placeholder="${t("password")}" required>
        <select name="role">
          <option value="field_engineer">${t("role_field_engineer")}</option>
          <option value="internal">${t("role_internal")}</option>
          <option value="admin">${t("role_admin")}</option>
        </select>
        <button type="submit">${t("addUser")}</button>
      </form>
    </div>
  `);

  const users = await Api.users();
  const body = view.querySelector(".users-body");
  for (const u of users) {
    const row = el(`
      <tr>
        <td>${u.name}</td><td>${u.email}</td>
        <td>
          <select class="role-select">
            <option value="field_engineer" ${u.role === "field_engineer" ? "selected" : ""}>${t("role_field_engineer")}</option>
            <option value="internal" ${u.role === "internal" ? "selected" : ""}>${t("role_internal")}</option>
            <option value="admin" ${u.role === "admin" ? "selected" : ""}>${t("role_admin")}</option>
          </select>
        </td>
        <td><input type="checkbox" class="active-check" ${u.is_active ? "checked" : ""}></td>
      </tr>
    `);
    row.querySelector(".role-select").onchange = async (e) => {
      await Api.updateUser(u.id, { role: e.target.value });
    };
    row.querySelector(".active-check").onchange = async (e) => {
      await Api.updateUser(u.id, { is_active: e.target.checked });
    };
    body.appendChild(row);
  }

  view.querySelector(".add-user-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    await Api.createUser({
      name: form.name.value.trim(),
      email: form.email.value.trim(),
      password: form.password.value,
      role: form.role.value,
    });
    renderUsers();
  };

  setContent(shell, view);
}

// ---------- Router ----------

async function router() {
  const fullHash = location.hash || "#/dashboard";
  const [hash, queryString] = fullHash.split("?");
  const params = new URLSearchParams(queryString || "");

  if (!getToken()) {
    renderLogin();
    return;
  }

  if (hash === "#/login") {
    location.hash = "#/dashboard";
    return;
  }

  if (hash.startsWith("#/audits/")) {
    const id = hash.split("/")[2];
    await renderAuditDetail(id);
  } else if (hash === "#/audits") {
    await renderAuditsList(params);
  } else if (hash.startsWith("#/machine/")) {
    const id = hash.split("/")[2];
    await renderMachineDetail(id);
  } else if (hash === "#/tasks") {
    await renderTasks(params);
  } else if (hash === "#/machines") {
    await renderMachines();
  } else if (hash === "#/users") {
    await renderUsers();
  } else {
    await renderDashboard();
  }
}

window.addEventListener("hashchange", router);
router();
