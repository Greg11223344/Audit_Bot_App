"""Verifies the AuditType -> System -> SubModule -> ChecklistItem hierarchy: selecting a specific
System (e.g. PreFeeder) only ever surfaces that system's own sub-modules/items -- never another
system's, even when two systems happen to reuse the same sub-module name -- across the whole
path: the catalog API, the offline sync upsert, and the admin audits-list system filter.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app

client = TestClient(app)

ADMIN_EMAIL = "admin@auditbot.local"
ADMIN_PASSWORD = "ChangeMe123!"


@pytest.fixture(scope="module")
def auth_headers():
    resp = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def two_systems(auth_headers):
    """One audit type with two systems (PreFeeder, Dryer). Both systems deliberately reuse the
    same sub-module name ("General") to guard against the exact bug found during the real
    checklist_data_v2.json migration: grouping items only by sub-module name (dropping which
    system they belonged to) silently merged two unrelated systems' checks together."""
    db = SessionLocal()
    try:
        audit_type = models.AuditType(
            key=f"test_type_{uuid.uuid4().hex[:8]}", label_en="Test Audit Type", label_he="Test Audit Type", order_index=0
        )
        db.add(audit_type)
        db.flush()

        def make_system(name, descriptions):
            system_def = models.SystemDef(audit_type_id=audit_type.id, name=name, order_index=0)
            db.add(system_def)
            db.flush()

            sub_module = models.SubModuleDef(system_def_id=system_def.id, name="General", order_index=0)
            db.add(sub_module)
            db.flush()

            item_ids = []
            for i, description in enumerate(descriptions):
                item = models.ChecklistItem(sub_module_id=sub_module.id, description=description, order_index=i)
                db.add(item)
                db.flush()
                item_ids.append(item.id)

            return system_def.id, sub_module.id, item_ids

        prefeeder_id, prefeeder_sub_module_id, prefeeder_item_ids = make_system(
            "PreFeeder", ["Check paper tray alignment", "Check roller tension", "Check sensor calibration"]
        )
        dryer_id, dryer_sub_module_id, dryer_item_ids = make_system(
            "Dryer", ["Check heater temperature", "Check airflow"]
        )

        machine_model = models.MachineModel(name=f"Test Model {uuid.uuid4().hex[:8]}")
        db.add(machine_model)
        db.flush()

        machine = models.Machine(
            machine_model_id=machine_model.id,
            serial_number=f"SN-{uuid.uuid4().hex[:8]}",
            customer="Test Customer",
        )
        db.add(machine)
        db.commit()

        return {
            "audit_type_id": audit_type.id,
            "machine_id": machine.id,
            "prefeeder_id": prefeeder_id,
            "prefeeder_sub_module_id": prefeeder_sub_module_id,
            "prefeeder_item_ids": prefeeder_item_ids,
            "dryer_id": dryer_id,
            "dryer_sub_module_id": dryer_sub_module_id,
            "dryer_item_ids": dryer_item_ids,
        }
    finally:
        db.close()


def test_system_defs_have_disjoint_sub_modules_and_items(two_systems, auth_headers):
    resp = client.get(
        "/api/catalog/system-defs", params={"audit_type_id": two_systems["audit_type_id"]}, headers=auth_headers
    )
    assert resp.status_code == 200
    systems = {s["id"]: s for s in resp.json()}

    prefeeder = systems[two_systems["prefeeder_id"]]
    dryer = systems[two_systems["dryer_id"]]

    # Both systems have a sub-module named "General" -- these must be *different* SubModuleDef
    # rows (different ids), not merged into one shared grouping.
    prefeeder_sub_module_ids = {sm["id"] for sm in prefeeder["sub_modules"]}
    dryer_sub_module_ids = {sm["id"] for sm in dryer["sub_modules"]}
    assert prefeeder_sub_module_ids.isdisjoint(dryer_sub_module_ids), (
        "Two systems' same-named sub-modules must not collapse into a single SubModuleDef"
    )

    prefeeder_item_ids = {i["id"] for sm in prefeeder["sub_modules"] for i in sm["items"]}
    dryer_item_ids = {i["id"] for sm in dryer["sub_modules"] for i in sm["items"]}

    assert len(prefeeder_item_ids) == 3
    assert len(dryer_item_ids) == 2
    assert prefeeder_item_ids.isdisjoint(dryer_item_ids), "PreFeeder and Dryer must not share checklist items"

    dryer_descriptions = {i["description"] for sm in dryer["sub_modules"] for i in sm["items"]}
    for sm in prefeeder["sub_modules"]:
        for item in sm["items"]:
            assert item["description"] not in dryer_descriptions


def test_selecting_one_system_only_syncs_that_systems_results(two_systems, auth_headers):
    """Mirrors what the field-app does: pick one system, fill in its items, sync -- and confirm
    the persisted audit's results never reference another system's checklist items."""
    prefeeder_item_ids = two_systems["prefeeder_item_ids"]
    dryer_item_ids = set(two_systems["dryer_item_ids"])

    client_uuid = str(uuid.uuid4())
    sync_resp = client.post(
        "/api/audits/sync",
        json={
            "audits": [
                {
                    "client_uuid": client_uuid,
                    "base_version": 0,
                    "machine_id": two_systems["machine_id"],
                    "audit_type": "Test Audit Type",
                    "system_def_ids": [two_systems["prefeeder_id"]],
                    "status": "draft",
                    "results": [
                        {"checklist_item_id": prefeeder_item_ids[0], "result": "Pass", "comment": "ok"},
                        {"checklist_item_id": prefeeder_item_ids[1], "result": "Fail", "flagged_critical": True},
                    ],
                }
            ]
        },
        headers=auth_headers,
    )
    assert sync_resp.status_code == 200, sync_resp.text
    result_item = sync_resp.json()["results"][0]
    assert result_item["status"] == "ok"

    audit = result_item["audit"]
    assert audit["system_def_ids"] == [two_systems["prefeeder_id"]]

    result_checklist_item_ids = {r["checklist_item_id"] for r in audit["results"]}
    assert result_checklist_item_ids.isdisjoint(dryer_item_ids), (
        "An audit scoped to PreFeeder must never contain Dryer's checklist items"
    )
    assert result_checklist_item_ids == {prefeeder_item_ids[0], prefeeder_item_ids[1]}

    # Enriched result fields (added so the admin UI can actually show what was checked).
    result_by_item = {r["checklist_item_id"]: r for r in audit["results"]}
    assert result_by_item[prefeeder_item_ids[0]]["description"] == "Check paper tray alignment"
    assert result_by_item[prefeeder_item_ids[0]]["system_name"] == "PreFeeder"
    assert result_by_item[prefeeder_item_ids[0]]["sub_module_name"] == "General"

    # A critical flag on a PreFeeder item must auto-create a task tied to that item, not to Dryer.
    assert len(audit["tasks"]) == 1
    assert audit["tasks"][0]["audit_result_id"] is not None


def test_audits_list_system_filter_excludes_other_systems(two_systems, auth_headers):
    # Create one audit against PreFeeder and one against Dryer, then confirm the system_def_id
    # filter on GET /api/audits returns only the matching one.
    prefeeder_client_uuid = str(uuid.uuid4())
    dryer_client_uuid = str(uuid.uuid4())

    for client_uuid, system_id in [
        (prefeeder_client_uuid, two_systems["prefeeder_id"]),
        (dryer_client_uuid, two_systems["dryer_id"]),
    ]:
        resp = client.post(
            "/api/audits/sync",
            json={
                "audits": [
                    {
                        "client_uuid": client_uuid,
                        "base_version": 0,
                        "machine_id": two_systems["machine_id"],
                        "audit_type": "Test",
                        "system_def_ids": [system_id],
                        "status": "draft",
                        "results": [],
                    }
                ]
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

    filtered_resp = client.get(
        "/api/audits", params={"system_def_id": two_systems["prefeeder_id"]}, headers=auth_headers
    )
    assert filtered_resp.status_code == 200
    filtered_audits = filtered_resp.json()

    assert len(filtered_audits) >= 1
    for audit in filtered_audits:
        assert two_systems["prefeeder_id"] in audit["system_def_ids"]
        assert two_systems["dryer_id"] not in audit["system_def_ids"]


def test_audit_types_endpoint_excludes_inactive_types(auth_headers):
    inactive_key = f"hidden_type_{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(
            models.AuditType(
                key=inactive_key, label_en="Hidden Legacy Type", label_he="Hidden Legacy Type",
                order_index=999, is_active=False,
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/catalog/audit-types", headers=auth_headers)
    assert resp.status_code == 200
    keys = {at["key"] for at in resp.json()}
    assert inactive_key not in keys, "an is_active=False audit type must never be offered for new audits"
