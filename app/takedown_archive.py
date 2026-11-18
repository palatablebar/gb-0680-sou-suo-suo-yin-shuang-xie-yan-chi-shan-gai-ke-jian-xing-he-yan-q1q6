import csv,io,json
def build_takedown_archive(ticket):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["ticket_id","ticket_no","conclusion","credential_id","scope_digest","kind","doc_id","entrance","state","receipt_confirmed","first_redacted_at","body_sha256","evidence"])
    credential=ticket.get("credential") or {}
    for row in ticket["rows"]:
        writer.writerow([ticket["ticket_id"],ticket["ticket_no"],ticket["conclusion"],ticket.get("credential_id") or "",
            ticket["scope_digest"],"cell",row["doc_id"],row["entrance"],row["state"],
            "1" if row["receipt_confirmed"] else "0",row["first_redacted_at"] or "",row["body_sha256"],
            json.dumps({"tombstone_version":row["tombstone_version"],"probe_count":row["probe_count"]},ensure_ascii=False)])
    for item in ticket.get("blocked_late_writes",[]):
        writer.writerow([ticket["ticket_id"],ticket["ticket_no"],ticket["conclusion"],ticket.get("credential_id") or "",
            ticket["scope_digest"],"blocked_late_write",item["doc_id"],"|".join(item["entrances"]),item["reason"],
            "0",item["arrived_at"],"",json.dumps(item,ensure_ascii=False)])
    for item in ticket.get("escalated_late_writes",[]):
        writer.writerow([ticket["ticket_id"],ticket["ticket_no"],ticket["conclusion"],ticket.get("credential_id") or "",
            ticket["scope_digest"],"escalated_late_write",item["doc_id"],"|".join(item["entrances"]),item["reason"],
            "0",item["arrived_at"],"",json.dumps(item,ensure_ascii=False)])
    writer.writerow([ticket["ticket_id"],ticket["ticket_no"],ticket["conclusion"],ticket.get("credential_id") or "",
        ticket["scope_digest"],"credential","","",credential.get("conclusion",""),"",credential.get("issued_at",""),
        "",json.dumps(credential,ensure_ascii=False)])
    return "﻿"+stream.getvalue()
