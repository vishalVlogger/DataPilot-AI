from io import BytesIO

import pandas as pd

from app.schemas.dataset import CleaningOperation
from app.services.cleaning.service import clean_frame


def test_cleaning_preview_does_not_modify_input() -> None:
    frame = pd.DataFrame({"Customer": [" Alice ", "Bob", "Bob"], "Sales": [10.0, None, None]})
    original = frame.copy(deep=True)
    cleaned, preview = clean_frame(frame, [CleaningOperation(type="trim_whitespace", column="Customer"), CleaningOperation(type="remove_duplicates")])
    pd.testing.assert_frame_equal(frame, original)
    assert cleaned.iloc[0]["Customer"] == "Alice"
    assert preview.affected_rows >= 1


def test_fill_mean_and_case_cleaning() -> None:
    frame = pd.DataFrame({"Customer": ["alice", "BOB"], "Sales": [10.0, None]})
    cleaned, _ = clean_frame(frame, [CleaningOperation(type="standardize_titlecase", column="Customer"), CleaningOperation(type="fill_missing_mean", column="Sales")])
    assert cleaned["Customer"].tolist() == ["Alice", "Bob"]
    assert cleaned["Sales"].tolist() == [10.0, 10.0]


def test_apply_reset_and_exports(client) -> None:
    content = b"Customer,Sales\n Alice ,10\nBob,20\nBob,20\n"
    uploaded = client.post("/api/datasets/upload", files={"file": ("sales.csv", content, "text/csv")}).json()
    dataset_id = uploaded["id"]
    operation = {"operations": [{"type": "trim_whitespace", "column": "Customer"}, {"type": "remove_duplicates"}]}
    preview = client.post(f"/api/datasets/{dataset_id}/clean/preview", json=operation)
    assert preview.status_code == 200
    assert client.get(f"/api/datasets/{dataset_id}/profile").json()["row_count"] == 3
    rejected = client.post(f"/api/datasets/{dataset_id}/clean/apply", json=operation)
    assert rejected.status_code == 400 and rejected.json()["error_code"] == "CLEANING_APPLY_FAILED"
    applied = client.post(f"/api/datasets/{dataset_id}/clean/apply", json={**operation, "confirmed": True})
    assert applied.status_code == 200 and applied.json()["profile"]["row_count"] == 2
    csv_export = client.get(f"/api/datasets/{dataset_id}/export?format=csv&version=current")
    assert csv_export.status_code == 200 and "Alice" in csv_export.text
    xlsx_export = client.get(f"/api/datasets/{dataset_id}/export?format=xlsx&version=original")
    assert xlsx_export.status_code == 200
    exported = pd.read_excel(BytesIO(xlsx_export.content))
    assert len(exported) == 3
    reset = client.post(f"/api/datasets/{dataset_id}/reset")
    assert reset.status_code == 200 and reset.json()["row_count"] == 3
