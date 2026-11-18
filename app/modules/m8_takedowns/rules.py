import hashlib,json
from datetime import timedelta
from app.errors import DomainError
from app.values import number,instant
REDACTED="REDACTED";EXPOSED="EXPOSED";NEVER_PROBED="NEVER_PROBED"
BLOCKED="BLOCKED";ESCALATE="ESCALATE"
SEALED="已下架";BREACHED="已超时";OPEN="处置中"
def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()
def ticket_id(ticket_no,docs,entrances,deadline_seconds):
    basis={"ticket_no":ticket_no,"docs":docs,"entrances":sorted(entrances),"deadline_seconds":deadline_seconds}
    return "tk_"+hashlib.sha256(_canonical(basis)).hexdigest()[:20]
def _payload(payload):
    if not isinstance(payload,dict): raise DomainError("BAD_TICKET","下架工单需要对象")
    no=payload.get("ticket_no")
    if not isinstance(no,str) or not no.strip(): raise DomainError("BAD_TICKET_NO","工单号不能为空")
    docs=payload.get("documents")
    if not isinstance(docs,list) or not docs or any(not isinstance(d,dict) or not str(d.get("doc_id","")).strip() for d in docs):
        raise DomainError("BAD_SCOPE","下架范围需要至少一条文档记录")
    entrances=payload.get("entrances")
    if not isinstance(entrances,list) or not entrances or any(not isinstance(e,str) or not e.strip() for e in entrances):
        raise DomainError("BAD_ENTRANCES","检索入口不能为空")
    deadline=number(payload.get("deadline_seconds","900"))
    if deadline<=0: raise DomainError("BAD_DEADLINE","下架时限必须为正")
    issued=instant(payload.get("issued_at"))
    return no.strip(),docs,list(dict.fromkeys(e.strip() for e in entrances)),deadline,issued
def _late_writes(payload):
    writes=payload.get("late_writes") or []
    if not isinstance(writes,list): raise DomainError("BAD_LATE_WRITES","迟到写入需要列表")
    return writes
def _receipts(payload):
    receipts=payload.get("receipts") or []
    if not isinstance(receipts,list): raise DomainError("BAD_RECEIPTS","副本回执需要列表")
    return receipts
def _probe_index(probes):
    index={}
    if probes is None: probes=[]
    if not isinstance(probes,list): raise DomainError("BAD_PROBES","探针需要列表")
    for probe in probes:
        if not isinstance(probe,dict) or not str(probe.get("doc_id","")).strip() or not str(probe.get("entrance","")).strip():
            raise DomainError("BAD_PROBE","探针必须包含文档号与入口")
        body=probe.get("returns_body")
        if not isinstance(body,bool): raise DomainError("BAD_PROBE","探针结论需要布尔值 returns_body")
        observed=instant(probe.get("observed_at"))
        index.setdefault((str(probe["doc_id"]).strip(),str(probe["entrance"]).strip()),[]).append(
            {"observed_at":observed.isoformat(),"returns_body":body,"body_sha256":probe.get("body_sha256")})
    return index
def _blocked_late_writes(scope,entrances,writes,tombstone):
    blocked=[];escalations=[]
    for write in writes:
        if not isinstance(write,dict) or not str(write.get("doc_id","")).strip(): raise DomainError("BAD_LATE_WRITE","迟到写入缺少文档号")
        doc=str(write["doc_id"]).strip()
        if doc not in scope: continue
        try: version=number(write.get("version"))
        except DomainError: raise DomainError("BAD_LATE_WRITE","迟到写入版本无效")
        arrived=instant(write.get("arrived_at"))
        targets=[write["entrance"]] if write.get("entrance") else entrances
        hit=sorted({str(e).strip() for e in targets if str(e).strip() in entrances})
        item={"doc_id":doc,"version":str(version),"arrived_at":arrived.isoformat(),"entrances":hit}
        if version<=tombstone[doc]: blocked.append({**item,"reason":BLOCKED,"detail":"版本不高于墓碑，旧写被拦截，不能复活正文"})
        else: escalations.append({**item,"reason":ESCALATE,"detail":"版本高于墓碑，需人工升级，不自动复活正文"})
    return blocked,escalations
def evaluate(payload,context=None):
    ticket_no,docs,entrances,deadline,issued=_payload(payload)
    scope={str(d["doc_id"]).strip():d for d in docs}
    if len(scope)!=len(docs): raise DomainError("BAD_SCOPE","下架范围文档号重复")
    tombstone={}
    for doc,item in scope.items():
        try: tombstone[doc]=number(item.get("tombstone_version"))
        except DomainError: raise DomainError("BAD_TOMBSTONE","墓碑版本无效")
        if not isinstance(item.get("body_sha256"),str) or not item["body_sha256"].strip(): raise DomainError("BAD_BODY_HASH","需保留原正文摘要用于审计定位，正文本身不落库")
    cutoff=issued+timedelta(seconds=int(deadline))
    probe_index=_probe_index(payload.get("probes"))
    blocked,escalations=_blocked_late_writes(scope,entrances,_late_writes(payload),tombstone)
    receipt_set={(str(r.get("doc_id","")).strip(),str(r.get("entrance","")).strip()) for r in _receipts(payload) if isinstance(r,dict)}
    receipt_set={(d,e) for d,e in receipt_set if d in scope and e in entrances}
    rows=[];redacted=exposed=missing=0;all_by_cutoff=True
    for doc in sorted(scope):
        for entrance in entrances:
            probes=sorted(probe_index.get((doc,entrance),[]),key=lambda p:p["observed_at"])
            if not probes: state=NEVER_PROBED
            else: state=EXPOSED if probes[-1]["returns_body"] else REDACTED
            redact_times=[instant(p["observed_at"]) for p in probes if not p["returns_body"]]
            first=min(redact_times).isoformat() if redact_times else None
            if first is None or instant(first)>cutoff: all_by_cutoff=False
            if state==REDACTED: redacted+=1
            elif state==EXPOSED: exposed+=1
            else: missing+=1;all_by_cutoff=False
            rows.append({"doc_id":doc,"entrance":entrance,"tombstone_version":str(tombstone[doc]),"state":state,
                "receipt_confirmed":(doc,entrance) in receipt_set,"first_redacted_at":first,
                "probe_count":len(probes),"ever_exposed":any(p["returns_body"] for p in probes),
                "body_sha256":scope[doc]["body_sha256"],"_sources":[f"{ticket_no}:{doc}:{entrance}"]})
    observed=[instant(p["observed_at"]) for probes in probe_index.values() for p in probes]
    as_of=instant(payload["as_of"]) if payload.get("as_of") else (max(observed) if observed else issued)
    if all(state==REDACTED for state in (r["state"] for r in rows)) and all_by_cutoff:
        conclusion=SEALED;concluded_at=max(instant(r["first_redacted_at"]) for r in rows).isoformat()
    elif as_of>cutoff:
        conclusion=BREACHED;concluded_at=as_of.isoformat()
    else:
        conclusion=OPEN;concluded_at=None
    tk_id=ticket_id(ticket_no,sorted(scope),entrances,int(deadline))
    scope_digest=hashlib.sha256(_canonical({"documents":sorted(scope),"entrances":entrances})).hexdigest()
    credential=None;credential_id=None
    if conclusion==SEALED:
        conclusion_basis={"ticket_id":tk_id,"scope_digest":scope_digest,"deadline_seconds":int(deadline),
            "cells":sorted(({"doc_id":r["doc_id"],"entrance":r["entrance"],"state":r["state"],"first_redacted_at":r["first_redacted_at"]} for r in rows),key=lambda x:(x["doc_id"],x["entrance"]))}
        credential_id="cred_"+hashlib.sha256(_canonical(conclusion_basis)).hexdigest()[:20]
        credential={"credential_id":credential_id,"ticket_id":tk_id,"conclusion":conclusion,
            "scope_digest":scope_digest,"issued_at":concluded_at,"cells_redacted":redacted,"body_retained":False,
            "sealed_judgement":hashlib.sha256(_canonical(conclusion_basis)).hexdigest()}
    metrics={"scope_documents":len(scope),"entrances":len(entrances),"cells_total":len(rows),
        "cells_redacted":redacted,"cells_exposed":exposed,"cells_never_probed":missing,
        "receipts_confirmed":len(receipt_set),"receipts_required":len(rows),"all_receipts_in":len(receipt_set)==len(rows),
        "late_writes_blocked":len(blocked),"late_writes_escalated":len(escalations),
        "deadline_seconds":int(deadline),"within_deadline":all_by_cutoff,"exposed_anywhere":exposed>0}
    return {"ticket_id":tk_id,"ticket_no":ticket_no,"conclusion":conclusion,"concluded_at":concluded_at,
        "issued_at":issued.isoformat(),"deadline_seconds":int(deadline),"cutoff_at":cutoff.isoformat(),
        "scope_digest":scope_digest,"credential_id":credential_id,"credential":credential,
        "rows":rows,"blocked_late_writes":blocked,"escalated_late_writes":escalations,
        "quarantine":[],"metrics":metrics}
