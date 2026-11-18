import json
from flask import Blueprint,request,jsonify
from app.config import ROOT,DATA_DIR
from app.errors import DomainError
from app.modules.m8_takedowns.rules import evaluate
from app import takedown_store
from app.takedown_archive import build_takedown_archive
bp=Blueprint("takedowns",__name__)
def load_sample_ticket():
    return json.loads((ROOT/"sample_data"/"takedown.json").read_text(encoding="utf-8"))
def _body():
    payload=request.get_json(silent=True)
    if payload is None or not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    return payload
@bp.route("/api/takedowns",methods=["GET","POST"])
def preview():
    payload=load_sample_ticket() if request.method=="GET" else _body()
    return jsonify(evaluate(payload))
@bp.route("/api/takedowns/settle",methods=["GET","POST"])
def settle():
    payload=load_sample_ticket() if request.method=="GET" or not request.data.strip() else _body()
    result,created=takedown_store.settle(DATA_DIR,payload)
    return jsonify({**result,"settled":True,"new_conclusion":created})
@bp.route("/api/takedowns/history")
def history(): return jsonify({"takedowns":takedown_store.history(DATA_DIR)})
@bp.route("/api/takedowns/<ticket_id>")
def detail(ticket_id): return jsonify(takedown_store.get(DATA_DIR,ticket_id))
@bp.route("/api/takedowns/<ticket_id>/credential")
def credential(ticket_id):
    ticket=takedown_store.get(DATA_DIR,ticket_id)
    if ticket["conclusion"]!="已下架" or not ticket.get("credential_id"):
        raise DomainError("NO_CREDENTIAL","仅已下架工单形成唯一凭据",409)
    from flask import current_app
    return current_app.response_class(build_takedown_archive(ticket),mimetype="text/csv",
        headers={"Content-Disposition":'attachment; filename="takedown-credential.csv"'})
