import { DB } from "./db.js";
import { Api } from "./api.js";

const listeners = [];

export function onSyncEvent(fn) {
  listeners.push(fn);
}

function notify(event) {
  listeners.forEach((fn) => fn(event));
}

function resultsMapToList(resultsMap) {
  return Object.entries(resultsMap).map(([checklist_item_id, r]) => ({
    checklist_item_id: Number(checklist_item_id),
    result: r.result || "",
    comment: r.comment || "",
    flagged_critical: !!r.flagged_critical,
  }));
}

async function pushOne(localAudit) {
  const payload = {
    client_uuid: localAudit.client_uuid,
    base_version: localAudit.base_version || 0,
    machine_id: localAudit.machine_id,
    audit_type: localAudit.audit_type,
    system_def_ids: localAudit.system_def_ids,
    status: localAudit.status,
    notes: localAudit.notes || "",
    started_at: localAudit.started_at,
    completed_at: localAudit.completed_at,
    results: resultsMapToList(localAudit.results || {}),
  };

  const response = await Api.sync([payload]);
  const item = response.results[0];

  if (item.status === "deleted") {
    // An admin deleted this audit server-side -- drop the local copy instead of resurrecting
    // it (the naive alternative, treating "not found" as "create new", would silently undo
    // the admin's deletion the next time this device comes online).
    await DB.delete("audits", localAudit.client_uuid);
    return { status: "deleted", localAudit };
  }

  if (item.status === "conflict") {
    localAudit.conflict = true;
    localAudit.conflict_server_audit = item.conflict.server_audit;
    await DB.put("audits", localAudit);
    return { status: "conflict", localAudit };
  }

  const serverAudit = item.audit;
  localAudit.server_id = serverAudit.id;
  localAudit.base_version = serverAudit.version;
  localAudit.dirty = false;
  localAudit.conflict = false;

  // Map checklist_item_id -> server audit_result id, needed to upload queued attachments.
  const resultIdByItem = {};
  for (const r of serverAudit.results) {
    resultIdByItem[r.checklist_item_id] = r.id;
  }
  localAudit.result_id_by_item = resultIdByItem;
  localAudit.server_snapshot = serverAudit;

  await DB.put("audits", localAudit);
  return { status: "ok", localAudit };
}

async function pushPendingAttachments(localAudit) {
  if (!localAudit.server_id) return;

  const all = await DB.getAll("attachments");
  const pending = all.filter((a) => a.audit_client_uuid === localAudit.client_uuid && !a.uploaded);

  for (const attachment of pending) {
    const auditResultId = localAudit.result_id_by_item
      ? localAudit.result_id_by_item[attachment.checklist_item_id]
      : null;

    const formData = new FormData();
    formData.append("client_uuid", attachment.client_uuid);
    formData.append("taken_at", attachment.taken_at);
    if (auditResultId) formData.append("audit_result_id", auditResultId);
    formData.append("file", attachment.blob, attachment.file_name || "photo.jpg");

    try {
      const uploaded = await Api.uploadAttachment(localAudit.server_id, formData);
      attachment.uploaded = true;
      attachment.server_file_path = uploaded.file_path;
      attachment.blob = null; // free memory, keep metadata
      await DB.put("attachments", attachment);
    } catch (e) {
      // leave pending, will retry on next sync pass
      console.warn("attachment upload failed, will retry", e);
    }
  }
}

let inFlightSync = null;

// Concurrent callers (the 30s timer, an 'online' event, and an explicit "save & exit"/"submit"
// click can all fire close together) must all resolve only once the sync they asked for has
// actually finished -- previously a second caller mid-sync just returned immediately, so e.g.
// clicking "submit" right as the periodic timer was mid-sync silently skipped that audit and
// left it looking stuck on "pending sync".
export function syncAll() {
  if (inFlightSync) return inFlightSync;
  inFlightSync = runSync().finally(() => {
    inFlightSync = null;
  });
  return inFlightSync;
}

async function runSync() {
  notify({ type: "start" });

  const online = await Api.isOnline();
  if (!online) {
    notify({ type: "offline" });
    return;
  }

  const audits = await DB.getAll("audits");
  const dirty = audits.filter((a) => a.dirty && !a.conflict);

  for (const localAudit of dirty) {
    try {
      const result = await pushOne(localAudit);
      if (result.status === "ok") {
        await pushPendingAttachments(result.localAudit);
      }
    } catch (e) {
      console.warn("sync failed for", localAudit.client_uuid, e);
    }
  }

  notify({ type: "done" });
}

export function startAutoSync() {
  window.addEventListener("online", () => syncAll());
  setInterval(() => syncAll(), 30000);
  syncAll();
}
