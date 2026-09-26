from orchestrator.db import Database


def test_session_lifecycle(db: Database):
    db.log_session("s1", "hello")
    db.update_session("s1", route="direct", is_destructive=True)
    db.update_session_status("s1", "completed", response_text="done")
    db.log_step("s1", "direct", 1, "execute", "vol down", True)
    db.log_error("s1", "oops")
    s = db.get_session("s1")
    assert s["route"] == "direct" and s["is_destructive"] == 1 and s["status"] == "completed"
    assert s["completed_at"] and s["steps"][0]["success"] == 1
    assert db.next_step_number("s1") == 2
    assert db.get_errors("s1")[0]["message"] == "oops"
    assert db.list_sessions()[0]["id"] == "s1"


def test_rejects_unknown_columns(db: Database):
    db.log_session("s1", "x")
    try:
        db.update_session("s1", bogus=1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_file_db_persists(tmp_path):
    path = str(tmp_path / "a" / "alfred.db")
    Database(path).log_session("s1", "x")
    assert Database(path).get_session("s1")["transcript"] == "x"
