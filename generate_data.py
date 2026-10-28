#!/usr/bin/env python3
"""Deterministic synthetic supplier acknowledgement workflow data generator."""
import argparse, csv, json, hashlib, random, sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta

SEED_DEFAULT = 20261022
TABLES = ['Supplier','PurchaseOrder','POLine','Acknowledgement','PromiseDate','ChangeRequest','Approval','InventoryPlan','ProductionOrder','Notification']

def iso(d): return d.isoformat() if d else ''
def write_csv(path, rows):
    rows = list(rows)
    fields = list(rows[0].keys()) if rows else []
    with path.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--scale', choices=['starter','full'], default='starter')
    ap.add_argument('--seed', type=int, default=SEED_DEFAULT)
    ap.add_argument('--out', default='output')
    args=ap.parse_args(); rng=random.Random(args.seed); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    n_po=100 if args.scale=='starter' else 10000
    n_events=150 if args.scale=='starter' else 15000
    today=date(2026,10,22)
    suppliers=[]
    for i in range(1,101):
        suppliers.append({'supplier_id':f'SUP-{i:05d}','supplier_name':f'Synthetic Supplier {i:03d}','country':rng.choice(['IN','US','DE','JP','CN']),'lead_time_days':rng.randint(3,35),'risk_tier':rng.choices(['LOW','MEDIUM','HIGH'],[.55,.32,.13])[0],'active':True})
    pos=[]; lines=[]; ack=[]; promises=[]; changes=[]; approvals=[]; plans=[]; production=[]; notifications=[]; truth=[]
    line_by_po={}; event_count=0; change_counter={}; ack_counter={}; notification_counter=0
    for i in range(1,n_po+1):
        po_id=f'PO-2026-{i:06d}'; supplier=rng.choice(suppliers); order_date=today-timedelta(days=rng.randint(0,90)); currency='INR'
        pos.append({'po_id':po_id,'supplier_id':supplier['supplier_id'],'order_date':iso(order_date),'currency':currency,'status':'OPEN','buyer_id':f'BUY-{rng.randint(1,30):03d}'})
        count=rng.randint(1,3); po_lines=[]
        for j in range(1,count+1):
            qty=rng.randint(10,500); price=round(rng.uniform(50,5000),2); req=order_date+timedelta(days=supplier['lead_time_days']+rng.randint(0,10)); line_id=f'{po_id}-L{j:02d}'
            row={'po_line_id':line_id,'po_id':po_id,'line_no':j,'item_id':f'ITEM-{rng.randint(1,500):04d}','requested_qty':qty,'unit_price':price,'requested_delivery_date':iso(req),'uom':'EA'}
            lines.append(row); po_lines.append(row)
            plans.append({'inventory_plan_id':f'IP-{i:06d}-{j:02d}','po_line_id':line_id,'baseline_projected_qty':qty,'projected_qty':qty,'projected_date':iso(req),'last_approved_change_id':'','plan_version':1})
            production.append({'production_order_id':f'PROD-{i:06d}-{j:02d}','po_line_id':line_id,'required_qty':max(1,int(qty*rng.uniform(.3,.9))),'need_by_date':iso(req-timedelta(days=rng.randint(0,7))),'status':'PLANNED'})
        line_by_po[po_id]=po_lines
    # Allocate event types; every event has a documented rule-derived outcome.
    event_types=['ACK','CHANGE']; weights=[.53,.47]
    for e in range(1,n_events+1):
        po=rng.choice(pos); po_id=po['po_id']; line=rng.choice(line_by_po[po_id]); order_date=date.fromisoformat(po['order_date']); req_date=date.fromisoformat(line['requested_delivery_date'])
        et=rng.choices(event_types,weights)[0]
        if et=='ACK':
            ack_counter[po_id]=ack_counter.get(po_id,0)+1; aid=f'ACK-{po_id}-{ack_counter[po_id]:02d}'
            accepted=rng.randint(1,line['requested_qty']); rejected=line['requested_qty']-accepted; promised=req_date+timedelta(days=rng.choices([-5,0,1,3,7,14],[.03,.40,.18,.20,.14,.05])[0])
            issue=''; gt='VALID'; status='RECEIVED'
            # Deliberate labelled wrong-line and pre-order date anomalies, without corrupting other rows.
            anomaly=rng.random()
            ack_line=line['po_line_id']
            if anomaly<.006:
                other=rng.choice([x for x in lines if x['po_id']!=po_id]); ack_line=other['po_line_id']; issue='WRONG_PO_LINE'; gt='INVALID_FOREIGN_RELATION'
            elif anomaly<.012:
                promised=order_date-timedelta(days=1); issue='PROMISE_BEFORE_ORDER'; gt='INVALID_DATE_ORDER'
            ack.append({'acknowledgement_id':aid,'po_id':po_id,'po_line_id':ack_line,'revision_no':ack_counter[po_id],'received_date':iso(max(order_date,today-timedelta(days=rng.randint(0,30)))),'accepted_qty':accepted,'rejected_qty':rejected,'promised_date':iso(promised),'status':status,'issue_type':issue})
            promises.append({'promise_date_id':f'PRM-{e:06d}','acknowledgement_id':aid,'po_line_id':ack_line,'promised_date':iso(promised),'effective_from':iso(today),'effective_to':'','revision_no':ack_counter[po_id]})
            truth.append({'record_id':aid,'issue_type':issue or 'NONE','ground_truth':gt,'expected_decision':'QUARANTINE' if issue else ('PARTIAL_ACCEPTANCE' if rejected else 'ACCEPT'),'rule':'Wrong PO line or promise date before order date is invalid; otherwise compare accepted and rejected quantities with requested quantity.'})
        else:
            change_counter[po_id]=change_counter.get(po_id,0)+1; cid=f'CHG-{po_id}-{change_counter[po_id]:06d}'
            change_kind=rng.choice(['QUANTITY','DATE','PRICE']); old_qty=line['requested_qty']; new_qty=old_qty; old_date=req_date; new_date=req_date; old_price=line['unit_price']; new_price=old_price
            if change_kind=='QUANTITY': new_qty=max(1,int(old_qty*rng.uniform(.5,1.4)))
            elif change_kind=='DATE': new_date=req_date+timedelta(days=rng.choice([-2,0,2,5,10,20]))
            else: new_price=round(old_price*rng.uniform(.92,1.15),2)
            pct=abs(new_qty-old_qty)/old_qty*100 if change_kind=='QUANTITY' else (abs((new_date-old_date).days) if change_kind=='DATE' else abs(new_price-old_price)/old_price*100)
            threshold={'QUANTITY':10,'DATE':3,'PRICE':5}[change_kind]
            required_approval=pct>threshold
            approved=not required_approval or rng.random()<.72
            decision='APPROVED' if approved and required_approval else ('NOT_REQUIRED' if not required_approval else 'REJECTED')
            changes.append({'change_request_id':cid,'po_id':po_id,'po_line_id':line['po_line_id'],'change_type':change_kind,'old_qty':old_qty,'new_qty':new_qty,'old_date':iso(old_date),'new_date':iso(new_date),'old_price':old_price,'new_price':new_price,'change_pct_or_days':round(pct,2),'approval_required':required_approval,'status':decision,'requested_at':iso(today-timedelta(days=rng.randint(0,20)))})
            if required_approval:
                approvals.append({'approval_id':f'APR-{cid}-01','change_request_id':cid,'decision':'APPROVED' if approved else 'REJECTED','approver_id':f'APRVR-{rng.randint(1,20):03d}','decision_date':iso(today-timedelta(days=rng.randint(0,5))),'reason':'Threshold exceeded; approval decision recorded'})
            if approved:
                plan=next(x for x in plans if x['po_line_id']==line['po_line_id'])
                if change_kind=='QUANTITY': plan['projected_qty']=new_qty
                elif change_kind=='DATE': plan['projected_date']=iso(new_date)
                elif change_kind=='PRICE': pass
                plan['last_approved_change_id']=cid; plan['plan_version']+=1
                notification_counter+=1; notifications.append({'notification_id':f'NOT-2026-{notification_counter:06d}','po_id':po_id,'po_line_id':line['po_line_id'],'recipient_role':'PLANNER','notification_type':'APPROVED_CHANGE','message':f'{change_kind} change approved; review downstream schedule','created_at':iso(today),'status':'SENT'})
            truth.append({'record_id':cid,'issue_type':'NONE','ground_truth':decision,'expected_decision':decision,'rule':f'Approval required when {change_kind.lower()} change exceeds threshold {threshold}; projected supply changes only when approved or approval is not required.'})
    # Supplier silence is tracked separately so the requested 15,000 ACK/change event volume stays exact.
    acked_po_ids={x['po_id'] for x in ack}
    silence_candidates=[p for p in pos if p['po_id'] not in acked_po_ids and (today-date.fromisoformat(p['order_date'])).days >= 7]
    for p in silence_candidates[:max(1, int(n_po*0.05))]:
        po_id=p['po_id']; line=line_by_po[po_id][0]
        truth.append({'record_id':f"SIL-{po_id}",'issue_type':'SUPPLIER_SILENCE','ground_truth':'EXCEPTION','expected_decision':'FOLLOW_UP_REQUIRED','rule':'No acknowledgement received within 7 days of order date.'})
        notification_counter+=1; notifications.append({'notification_id':f'NOT-2026-{notification_counter:06d}','po_id':po_id,'po_line_id':line['po_line_id'],'recipient_role':'PLANNER','notification_type':'SUPPLIER_SILENCE','message':'Supplier acknowledgement overdue','created_at':iso(today),'status':'SENT'})
    # Explicit negative scenario: a bad change attempts to update the plan without approval.
    if lines:
        line=lines[0]; po_id=line['po_id']; cid=f'CHG-{po_id}-999999'; change_counter[po_id]=change_counter.get(po_id,0)+1
        changes.append({'change_request_id':cid,'po_id':po_id,'po_line_id':line['po_line_id'],'change_type':'QUANTITY','old_qty':line['requested_qty'],'new_qty':line['requested_qty']+100,'old_date':line['requested_delivery_date'],'new_date':line['requested_delivery_date'],'old_price':line['unit_price'],'new_price':line['unit_price'],'change_pct_or_days':round(100/line['requested_qty']*100,2),'approval_required':True,'status':'PENDING','requested_at':iso(today)})
        truth.append({'record_id':cid,'issue_type':'UNAPPROVED_PLAN_UPDATE_ATTEMPT','ground_truth':'BLOCK_UPDATE','expected_decision':'DO_NOT_UPDATE_PLAN','rule':'Pending changes requiring approval must not update InventoryPlan.'})
    tables={'Supplier':suppliers,'PurchaseOrder':pos,'POLine':lines,'Acknowledgement':ack,'PromiseDate':promises,'ChangeRequest':changes,'Approval':approvals,'InventoryPlan':plans,'ProductionOrder':production,'Notification':notifications}
    # Ensure outputs include a header even for empty tables (not expected here).
    for name,rows in tables.items(): write_csv(out/f'{name}.csv',rows)
    (out/'ground_truth.json').write_text(json.dumps(truth,indent=2),encoding='utf-8'); write_csv(out/'ground_truth.csv',truth)
    (out/'data_dictionary.json').write_text(json.dumps({
      'Supplier':{'pk':'supplier_id','fields':{'supplier_id':'string, required, unique, SUP-#####','supplier_name':'string, required','country':'ISO-like 2-letter synthetic code','lead_time_days':'integer days, 1..90','risk_tier':'LOW|MEDIUM|HIGH','active':'boolean'}},
      'PurchaseOrder':{'pk':'po_id','fk':['supplier_id -> Supplier.supplier_id'],'fields':{'order_date':'ISO date','currency':'3-letter code','status':'OPEN|CLOSED|CANCELLED','buyer_id':'synthetic buyer identifier'}},
      'POLine':{'pk':'po_line_id','fk':['po_id -> PurchaseOrder.po_id'],'fields':{'line_no':'positive integer unique within PO','requested_qty':'positive EA','unit_price':'positive INR per EA','requested_delivery_date':'ISO date >= order date','uom':'EA'}},
      'Acknowledgement':{'pk':'acknowledgement_id','fk':['po_id -> PurchaseOrder.po_id','po_line_id -> POLine.po_line_id'],'fields':{'revision_no':'positive integer','accepted_qty':'non-negative EA','rejected_qty':'non-negative EA','promised_date':'ISO date >= order date','status':'RECEIVED','issue_type':'optional anomaly label'}},
      'PromiseDate':{'pk':'promise_date_id','fk':['acknowledgement_id -> Acknowledgement.acknowledgement_id','po_line_id -> POLine.po_line_id'],'fields':{'promised_date':'ISO date','effective_from':'ISO date','effective_to':'optional ISO date','revision_no':'positive integer'}},
      'ChangeRequest':{'pk':'change_request_id','fk':['po_id -> PurchaseOrder.po_id','po_line_id -> POLine.po_line_id'],'fields':{'change_type':'QUANTITY|DATE|PRICE','status':'PENDING|APPROVED|REJECTED|NOT_REQUIRED','approval_required':'boolean','change_pct_or_days':'derived numeric'}},
      'Approval':{'pk':'approval_id','fk':['change_request_id -> ChangeRequest.change_request_id'],'fields':{'decision':'APPROVED|REJECTED','approver_id':'synthetic ID','decision_date':'ISO date','reason':'string'}},
      'InventoryPlan':{'pk':'inventory_plan_id','fk':['po_line_id -> POLine.po_line_id'],'fields':{'projected_qty':'non-negative EA','projected_date':'ISO date','last_approved_change_id':'optional ChangeRequest ID','plan_version':'positive integer'}},
      'ProductionOrder':{'pk':'production_order_id','fk':['po_line_id -> POLine.po_line_id'],'fields':{'required_qty':'positive EA','need_by_date':'ISO date','status':'PLANNED|RELEASED|COMPLETED'}},
      'Notification':{'pk':'notification_id','fk':['po_id -> PurchaseOrder.po_id','po_line_id -> POLine.po_line_id'],'fields':{'recipient_role':'PLANNER|LOGISTICS_ANALYST|OPERATIONS_MANAGER','notification_type':'SUPPLIER_SILENCE|APPROVED_CHANGE','status':'SENT|FAILED'}}
    },indent=2),encoding='utf-8')
    # SQLite schema and seed data
    db=sqlite3.connect(out/'supplier_workflow.sqlite'); db.execute('PRAGMA foreign_keys=OFF')
    for name,rows in tables.items():
        if not rows: continue
        cols=list(rows[0].keys()); db.execute(f'DROP TABLE IF EXISTS "{name}"')
        types=[]
        for c in cols:
            vals=[r.get(c) for r in rows[:20]]; typ='INTEGER' if all(isinstance(v,(int,bool)) or v is None for v in vals) else ('REAL' if all(isinstance(v,(float,int)) or v is None for v in vals) else 'TEXT')
            types.append(f'"{c}" {typ}')
        db.execute(f'CREATE TABLE "{name}" ({", ".join(types)})')
        db.executemany(f'INSERT INTO "{name}" ({", ".join(chr(34)+c+chr(34) for c in cols)}) VALUES ({", ".join("?" for _ in cols)})',[[r.get(c) for c in cols] for r in rows])
    db.commit(); db.close()
    # Validation report
    errors=[]
    for name,rows in tables.items():
        if rows:
            pk={'Supplier':'supplier_id','PurchaseOrder':'po_id','POLine':'po_line_id','Acknowledgement':'acknowledgement_id','PromiseDate':'promise_date_id','ChangeRequest':'change_request_id','Approval':'approval_id','InventoryPlan':'inventory_plan_id','ProductionOrder':'production_order_id','Notification':'notification_id'}[name]
            ids=[r[pk] for r in rows]
            if len(ids)!=len(set(ids)): errors.append(f'{name}: duplicate primary keys')
    po_ids={x['po_id'] for x in pos}; line_ids={x['po_line_id'] for x in lines}; sup_ids={x['supplier_id'] for x in suppliers}; ack_ids={x['acknowledgement_id'] for x in ack}; change_ids={x['change_request_id'] for x in changes}
    for x in pos:
        if x['supplier_id'] not in sup_ids: errors.append('PO supplier FK failure')
    for x in lines:
        if x['po_id'] not in po_ids: errors.append('POLine PO FK failure')
    for x in ack:
        if x['po_id'] not in po_ids: errors.append('Acknowledgement PO FK failure')
        if x['po_line_id'] not in line_ids and x['issue_type']!='WRONG_PO_LINE': errors.append('Acknowledgement line FK failure')
    for x in approvals:
        if x['change_request_id'] not in change_ids: errors.append('Approval change FK failure')
    # Intentional anomaly rows are counted, not treated as accidental validation errors.
    checksums={}
    for p in sorted(out.glob('*.csv')): checksums[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    report={'seed':args.seed,'scale':args.scale,'counts':{k:len(v) for k,v in tables.items()},'acknowledgement_and_change_events':len(ack)+len(changes),'ground_truth_rows':len(truth),'validation_errors':errors,'labelled_anomalies':sum(1 for x in truth if x['issue_type'] not in ('NONE','SUPPLIER_SILENCE')),'csv_sha256':checksums,'reproducibility_note':'Run twice with same seed and scale; compare CSV SHA-256 values.'}
    (out/'validation_summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'source_manifest.json').write_text(json.dumps({'data_origin':'fully synthetic; no external datasets or personal data used','seed':args.seed,'generator':'generate_data.py','generated_at':'intentionally omitted for deterministic output','external_sources':[]},indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if errors: raise SystemExit(1)
if __name__=='__main__': main()
