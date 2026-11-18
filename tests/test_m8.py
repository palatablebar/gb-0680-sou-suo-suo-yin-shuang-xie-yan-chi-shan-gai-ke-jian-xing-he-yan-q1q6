import csv,io,json
import pytest
from app.modules.m8_takedowns.rules import evaluate,ticket_id
from app.modules.m8_takedowns.handler import load_sample_ticket
from app import takedown_store
from app.takedown_archive import build_takedown_archive
ISSUED="2026-11-18T09:00:00+00:00"
ENTRANCES=["search-main","search-replica-a","search-replica-b","search-partner"]
def ticket(probes,receipts=None,late=None,as_of="2026-11-18T09:08:00+00:00",deadline=900,docs=None):
    docs=docs or [{"doc_id":"0007","tombstone_version":"5","body_sha256":"sha256:abc"},
                  {"doc_id":"0008","tombstone_version":"3","body_sha256":"sha256:def"}]
    return {"ticket_no":"CT-2026-1118-001","issued_at":ISSUED,"deadline_seconds":deadline,"as_of":as_of,
            "entrances":ENTRANCES,"documents":docs,"probes":probes,"receipts":receipts or [],"late_writes":late or []}
def redact(doc,entrance,minute,second=0):
    return {"doc_id":doc,"entrance":entrance,"observed_at":f"2026-11-18T09:{minute:02d}:{second:02d}+00:00","returns_body":False}
def expose(doc,entrance,minute,second=0):
    return {"doc_id":doc,"entrance":entrance,"observed_at":f"2026-11-18T09:{minute:02d}:{second:02d}+00:00","returns_body":True}
def all_redacted(minute=7):
    return [redact(d,e,minute) for d in ("0007","0008") for e in ENTRANCES]
def test_unique_conclusion_when_all_entrances_redacted_within_deadline():
    r=evaluate(ticket(all_redacted()))
    assert r["conclusion"]=="已下架" and r["concluded_at"] is not None
    assert r["metrics"]["cells_redacted"]==8 and r["metrics"]["exposed_anywhere"] is False
    assert r["credential_id"].startswith("cred_") and r["credential"]["body_retained"] is False
def test_conclusion_does_not_wait_for_all_receipts():
    partial=[{"doc_id":"0007","entrance":"search-main"}]
    r=evaluate(ticket(all_redacted(),receipts=partial))
    assert r["conclusion"]=="已下架" and r["metrics"]["all_receipts_in"] is False
    assert r["metrics"]["receipts_confirmed"]==1
def test_exposed_cell_blocks_completion():
    probes=all_redacted();probes.append(expose("0007","search-replica-a",12))
    r=evaluate(ticket(probes,as_of="2026-11-18T09:16:00+00:00"))
    assert r["conclusion"]=="已超时" and r["credential_id"] is None and r["credential"] is None
    assert r["metrics"]["cells_exposed"]==1
def test_open_before_deadline_when_cell_missing():
    probes=[p for p in all_redacted() if not (p["doc_id"]=="0008" and p["entrance"]=="search-partner")]
    r=evaluate(ticket(probes,as_of="2026-11-18T09:05:00+00:00"))
    assert r["conclusion"]=="处置中" and r["concluded_at"] is None
def test_missing_cell_after_cutoff_is_breach():
    probes=[p for p in all_redacted() if not (p["doc_id"]=="0008" and p["entrance"]=="search-partner")]
    r=evaluate(ticket(probes,as_of="2026-11-18T09:16:00+00:00"))
    assert r["conclusion"]=="已超时" and r["metrics"]["cells_never_probed"]==1
def test_redaction_after_cutoff_is_breach():
    probes=[redact(d,e,16) for d in ("0007","0008") for e in ENTRANCES]
    r=evaluate(ticket(probes,as_of="2026-11-18T09:17:00+00:00"))
    assert r["conclusion"]=="已超时" and r["metrics"]["within_deadline"] is False
def test_redaction_exactly_at_cutoff_still_seals():
    probes=[{"doc_id":d,"entrance":e,"observed_at":"2026-11-18T09:15:00+00:00","returns_body":False}
            for d in ("0007","0008") for e in ENTRANCES]
    r=evaluate(ticket(probes,as_of="2026-11-18T09:15:00+00:00"))
    assert r["conclusion"]=="已下架" and r["metrics"]["within_deadline"] is True
def test_late_old_write_blocked_by_tombstone_and_never_revives():
    late=[{"doc_id":"0007","version":"4","arrived_at":"2026-11-18T09:03:00+00:00","entrance":"search-replica-a"},
          {"doc_id":"0007","version":"5","arrived_at":"2026-11-18T09:03:30+00:00"}]
    r=evaluate(ticket(all_redacted(),late=late))
    assert len(r["blocked_late_writes"])==2 and {x["reason"] for x in r["blocked_late_writes"]}=={"BLOCKED"}
    assert r["conclusion"]=="已下架"
def test_newer_version_write_is_escalated_not_auto_revived():
    late=[{"doc_id":"0008","version":"9","arrived_at":"2026-11-18T09:05:30+00:00","entrance":"search-partner"}]
    r=evaluate(ticket(all_redacted(),late=late))
    assert len(r["escalated_late_writes"])==1 and r["escalated_late_writes"][0]["reason"]=="ESCALATE"
def test_credential_stable_under_retry_and_extra_late_writes():
    base=ticket(all_redacted(),receipts=[{"doc_id":"0007","entrance":"search-main"}])
    first=evaluate(base)
    again=evaluate(json.loads(json.dumps(base)))
    assert again["credential_id"]==first["credential_id"] and again["conclusion"]==first["conclusion"]
    noisy=json.loads(json.dumps(base))
    noisy["late_writes"]=[{"doc_id":"0007","version":"2","arrived_at":"2026-11-18T09:10:00+00:00"}]
    noisy["as_of"]="2026-11-18T09:20:00+00:00"
    assert evaluate(noisy)["credential_id"]==first["credential_id"]
def test_ticket_id_deterministic_for_same_scope():
    a=ticket_id("CT-1",[{"doc_id":"1"}],"e1",900)
    b=ticket_id("CT-1",[{"doc_id":"1"}],"e1",900)
    assert a==b
def test_body_never_stored_only_hash_and_redaction():
    r=evaluate(ticket(all_redacted()))
    blob=json.dumps(r,ensure_ascii=False)
    assert "正文" not in blob
    assert all(row["state"]=="REDACTED" for row in r["rows"])
    assert all(row["body_sha256"].startswith("sha256:") for row in r["rows"])
def test_archive_locates_scope_without_body():
    r=evaluate(ticket(all_redacted()))
    rows=list(csv.reader(io.StringIO(build_takedown_archive(r).lstrip("﻿"))))
    assert rows[0][:4]==["ticket_id","ticket_no","conclusion","credential_id"]
    kinds={row[5] for row in rows[1:]}
    assert "cell" in kinds and "credential" in kinds
    assert all("sha256:" in row[11] for row in rows[1:] if row[5]=="cell")
def test_settle_idempotent_no_new_conclusion_or_credential(tmp_path):
    payload=load_sample_ticket()
    first,created=takedown_store.settle(tmp_path,payload)
    assert created is True and first["conclusion"]=="已下架"
    second,created2=takedown_store.settle(tmp_path,payload)
    assert created2 is False
    assert second["ticket_id"]==first["ticket_id"] and second["credential_id"]==first["credential_id"]
    assert len(takedown_store.history(tmp_path))==1
def test_final_conclusion_immutable_against_late_evidence(tmp_path):
    payload=load_sample_ticket()
    first,_=takedown_store.settle(tmp_path,payload)
    tampered=json.loads(json.dumps(payload))
    tampered["probes"].append(expose("0007","search-main",13))
    tampered["as_of"]="2026-11-18T09:30:00+00:00"
    stored,created=takedown_store.settle(tmp_path,tampered)
    assert created is False and stored["conclusion"]=="已下架" and stored["credential_id"]==first["credential_id"]
def test_retry_with_terminal_breach_stays_breached(tmp_path):
    probes=all_redacted();probes.append(expose("0007","search-main",12))
    payload=ticket(probes,as_of="2026-11-18T09:16:00+00:00")
    first,created=takedown_store.settle(tmp_path,payload)
    assert first["conclusion"]=="已超时" and created is True
    healed=ticket(all_redacted(),as_of="2026-11-18T09:30:00+00:00")
    healed["ticket_no"]=payload["ticket_no"]
    stored,created2=takedown_store.settle(tmp_path,healed)
    assert created2 is False and stored["conclusion"]=="已超时" and stored["credential_id"] is None
def test_open_ticket_progresses_then_seals_once(tmp_path):
    probes=[p for p in all_redacted() if not (p["doc_id"]=="0008" and p["entrance"]=="search-partner")]
    payload=ticket(probes,as_of="2026-11-18T09:05:00+00:00")
    first,created=takedown_store.settle(tmp_path,payload)
    assert first["conclusion"]=="处置中" and created is True
    again,_=takedown_store.settle(tmp_path,payload)
    assert again["conclusion"]=="处置中" and len(takedown_store.history(tmp_path))==1
    sealed,created2=takedown_store.settle(tmp_path,ticket(all_redacted()))
    assert created2 is True and sealed["conclusion"]=="已下架"
    assert takedown_store.get(tmp_path,sealed["ticket_id"])["credential_id"]==sealed["credential_id"]
def test_missing_ticket_404(tmp_path):
    with pytest.raises(Exception) as exc: takedown_store.get(tmp_path,"tk_nope")
    assert exc.value.status==404
def test_invalid_shape_rejected():
    with pytest.raises(Exception): evaluate({"ticket_no":""})
    with pytest.raises(Exception): evaluate({**ticket([]),"documents":[]})
def test_sample_ticket_meets_contract():
    r=evaluate(load_sample_ticket())
    assert r["conclusion"]=="已下架"
    assert r["metrics"]["all_receipts_in"] is False
    assert r["metrics"]["late_writes_blocked"]==1 and r["metrics"]["late_writes_escalated"]==1
    assert r["credential"]["scope_digest"]==r["scope_digest"]
def test_api_endpoints(client):
    assert client.get("/api/takedowns").status_code==200
    assert client.get("/takedowns").status_code==200
    r=client.post("/api/takedowns/settle");assert r.status_code==200
    ticket_id=r.get_json()["ticket_id"]
    again=client.post("/api/takedowns/settle");assert again.get_json()["new_conclusion"] is False
    cred=client.get(f"/api/takedowns/{ticket_id}/credential");assert cred.status_code==200
    assert cred.mimetype=="text/csv"
    assert client.get("/api/takedowns/history").get_json()["takedowns"][0]["ticket_id"]==ticket_id
def test_breach_has_no_credential_endpoint(client,tmp_path,monkeypatch):
    monkeypatch.setattr("app.modules.m8_takedowns.handler.DATA_DIR",tmp_path)
    probes=all_redacted();probes.append(expose("0007","search-main",12))
    r=client.post("/api/takedowns/settle",json=ticket(probes,as_of="2026-11-18T09:16:00+00:00"))
    tid=r.get_json()["ticket_id"]
    assert client.get(f"/api/takedowns/{tid}/credential").status_code==409
