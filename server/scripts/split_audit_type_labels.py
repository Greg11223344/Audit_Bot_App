"""One-time migration: splits audit_types.label ("English (Hebrew)") into two separate columns,
label_en and label_he, on whatever database DATABASE_URL/AUDIT_BOT_DATABASE_URL points at.

Two phases, deliberately not run together, to avoid a window where the OLD deployed code (which
still reads the `label` column) breaks before the NEW code (reading label_en/label_he) is live:

  1. (default) Add label_en/label_he and backfill them -- leaves the old `label` column in place
     and untouched, so whichever code is currently deployed (old or new) keeps working.
  2. --drop-old-column -- only run this AFTER confirming the redeployed app (using label_en/
     label_he) is live and working; drops the now-unused `label` column.

Safe to re-run either phase.
"""
import re
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

LABEL_PATTERN = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*\Z")


def main():
    drop_old_column = "--drop-old-column" in sys.argv

    with engine.connect() as conn:
        if drop_old_column:
            columns = [row[0] for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_types'")
            )]
            if "label" not in columns:
                print("`label` column already gone -- nothing to do.")
                return
            null_check = conn.execute(
                text("SELECT count(*) FROM audit_types WHERE label_en IS NULL OR label_he IS NULL")
            ).scalar()
            if null_check:
                print(f"ERROR: {null_check} row(s) still have NULL label_en/label_he -- run without --drop-old-column first.")
                sys.exit(1)
            conn.execute(text("ALTER TABLE audit_types DROP COLUMN label"))
            conn.commit()
            print("Dropped the old `label` column.")
            return

        columns = [row[0] for row in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_types'"))]

        if "label_en" not in columns:
            conn.execute(text("ALTER TABLE audit_types ADD COLUMN label_en VARCHAR(200)"))
            print("Added label_en column.")
        if "label_he" not in columns:
            conn.execute(text("ALTER TABLE audit_types ADD COLUMN label_he VARCHAR(200)"))
            print("Added label_he column.")
        conn.commit()

        rows = conn.execute(text("SELECT id, key, label, label_en, label_he FROM audit_types")).fetchall()
        updated = 0
        for row in rows:
            audit_type_id, key, label, label_en, label_he = row
            if label_en and label_he:
                print(f"  #{audit_type_id} {key}: already split, skipping.")
                continue

            match = LABEL_PATTERN.match(label or "")
            if match:
                new_en, new_he = match.group(1).strip(), match.group(2).strip()
            else:
                # No "(...)" suffix -- use the same text for both rather than leaving a NULL.
                new_en = new_he = (label or "").strip()

            conn.execute(
                text("UPDATE audit_types SET label_en = :en, label_he = :he WHERE id = :id"),
                {"en": new_en, "he": new_he, "id": audit_type_id},
            )
            updated += 1
            safe_label = (label or "").encode("ascii", "backslashreplace").decode()
            safe_he = new_he.encode("ascii", "backslashreplace").decode()
            print(f"  #{audit_type_id} {key}: {safe_label!r} -> en={new_en!r} he={safe_he!r}")
        conn.commit()
        print(f"Backfilled {updated} row(s).")

        remaining_nulls = conn.execute(
            text("SELECT count(*) FROM audit_types WHERE label_en IS NULL OR label_he IS NULL")
        ).scalar()
        if remaining_nulls:
            print(f"WARNING: {remaining_nulls} row(s) still have a NULL label_en/label_he -- not making the columns NOT NULL yet.")
            return

        # The old `label` column is still NOT NULL from before -- the new code never populates
        # it, so any INSERT from here on would violate that constraint even though `label`
        # itself is being kept around only for the old deployed code's benefit. Relax it (data
        # already there is untouched; only the constraint changes).
        conn.execute(text("ALTER TABLE audit_types ALTER COLUMN label DROP NOT NULL"))
        conn.commit()
        print("Relaxed the old `label` column to nullable (kept for old-code backward compat only).")

        conn.execute(text("ALTER TABLE audit_types ALTER COLUMN label_en SET NOT NULL"))
        conn.execute(text("ALTER TABLE audit_types ALTER COLUMN label_he SET NOT NULL"))
        conn.commit()
        print("label_en/label_he set NOT NULL. Old `label` column left in place on purpose --")
        print("re-run with --drop-old-column once the app has redeployed with the new code.")


if __name__ == "__main__":
    main()
