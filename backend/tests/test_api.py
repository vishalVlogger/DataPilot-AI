def test_health(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200


def test_upload_profile_and_ask(client) -> None:
    content = b"Product,Revenue\nAlpha,100\nBeta,50\nAlpha,25\n"
    uploaded = client.post("/api/datasets/upload", files={"file": ("sales.csv", content, "text/csv")})
    assert uploaded.status_code == 201
    dataset_id = uploaded.json()["id"]
    profile = client.get(f"/api/datasets/{dataset_id}/profile")
    assert profile.json()["row_count"] == 3
    answer = client.post(f"/api/datasets/{dataset_id}/ask", json={"question": "Show top 1 Product by Revenue"})
    assert answer.status_code == 200
    assert answer.json()["result"][0] == {"Product": "Alpha", "Revenue": 125.0}


def test_unsupported_question_is_standardized(client) -> None:
    uploaded = client.post("/api/datasets/upload", files={"file": ("sales.csv", b"Revenue\n10\n", "text/csv")})
    response = client.post(f"/api/datasets/{uploaded.json()['id']}/ask", json={"question": "Forecast next year"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_QUESTION"
