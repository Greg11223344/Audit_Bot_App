"""Verifies admin-only soft delete of audits: a non-admin gets 403 even calling the API
directly, a deleted audit disappears from every read path immediately, and a field-app client
with a stale local copy is told "deleted" (not silently allowed to resurrect it) on next sync.
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
def admin_headers():
    resp = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(scope="module")
def field_engineer_headers():
    email = f"field_{uuid.uuid4().hex[:8]}@test.local"
    db = SessionLocal()
    try:
        from app.auth import hash_password

        db.add(
            models.User(
                name="Test Field Engineer",
                email=email,
                role=models.UserRole.field_engineer,
                password_hash=hash_password("testpass123"),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def sample_audit(admin_headers):
    db = SessionLocal()
    try:
        audit_type = models.AuditType(key=f"del_test_{uuid.uuid4().hex[:8]}", label="Delete Test Type", order_index=0)
        db.add(audit_type)
        db.flush()
        system_def = models.SystemDef(audit_type_id=audit_type.id, name="Test System", order_index=0)
        db.add(system_def)
        db.flush()
        machine_model = models.MachineModel(name=f"Del Test Model {uuid.uuid4().hex[:8]}")
        db.add(machine_model)
        db.flush()
        machine = models.Machine(
            machine_model_id=machine_model.id, serial_number=f"SN-{uuid.uuid4().hex[:8]}", customer="Delete Test Customer"
        )
        db.add(machine)
        db.flush()

        admin_user = db.query(models.User).filter(models.User.email == ADMIN_EMAIL).first()
        audit = models.Audit(
            client_uuid=str(uuid.uuid4()),
            machine_id=machine.id,
            engineer_id=admin_user.id,
            audit_type="Delete Test Type",
            status=models.AuditStatus.draft,
        )
        db.add(audit)
        db.commit()
        return audit.id
    finally:
        db.close()


def test_non_admin_cannot_delete_audit(sample_audit, field_engineer_headers):
    resp = client.delete(f"/api/audits/{sample_audit}", headers=field_engineer_headers)
    assert resp.status_code == 403, resp.text

    # Confirm it's genuinely still there.
    get_resp = client.get(f"/api/audits/{sample_audit}", headers=field_engineer_headers)
    assert get_resp.status_code == 200


def test_admin_delete_hides_audit_from_all_read_paths(sample_audit, admin_headers):
    delete_resp = client.delete(f"/api/audits/{sample_audit}", headers=admin_headers)
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/audits/{sample_audit}", headers=admin_headers)
    assert get_resp.status_code == 404

    list_resp = client.get("/api/audits", headers=admin_headers)
    assert list_resp.status_code == 200
    assert sample_audit not in {a["id"] for a in list_resp.json()}

    drafts_resp = client.get("/api/audits/drafts", headers=admin_headers)
    assert sample_audit not in {a["id"] for a in drafts_resp.json()}


def test_deleting_twice_returns_404(sample_audit, admin_headers):
    first = client.delete(f"/api/audits/{sample_audit}", headers=admin_headers)
    assert first.status_code == 204
    second = client.delete(f"/api/audits/{sample_audit}", headers=admin_headers)
    assert second.status_code == 404


def test_sync_reports_deleted_status_instead_of_resurrecting(sample_audit, admin_headers):
    """Mirrors a field-app device that still has a local copy of an audit an admin just deleted:
    the next sync must say 'deleted', not silently create a brand-new audit under that uuid."""
    db = SessionLocal()
    try:
        audit = db.get(models.Audit, sample_audit)
        client_uuid = audit.client_uuid
    finally:
        db.close()

    delete_resp = client.delete(f"/api/audits/{sample_audit}", headers=admin_headers)
    assert delete_resp.status_code == 204

    sync_resp = client.post(
        "/api/audits/sync",
        json={
            "audits": [
                {
                    "client_uuid": client_uuid,
                    "base_version": 1,
                    "machine_id": 1,
                    "audit_type": "Delete Test Type",
                    "system_def_ids": [],
                    "status": "draft",
                    "results": [],
                }
            ]
        },
        headers=admin_headers,
    )
    assert sync_resp.status_code == 200, sync_resp.text
    result_item = sync_resp.json()["results"][0]
    assert result_item["status"] == "deleted"

    # And it must still be gone, not resurrected as a new row.
    get_resp = client.get(f"/api/audits/{sample_audit}", headers=admin_headers)
    assert get_resp.status_code == 404
