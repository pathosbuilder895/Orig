"""Local end-to-end check of the alpha join flow. Talks ONLY to a local server
(default http://127.0.0.1:8077). Usage: python verify_join_flow_local.py <prof_invite_path>"""
import sys, requests
from urllib.parse import urlparse, parse_qs
B = "http://127.0.0.1:8077"; PW = "alpha-local-Passw0rd!"
assert "127.0.0.1" in B or "localhost" in B
tok = lambda p: parse_qs(urlparse(p).query)["invite"][0]
H = lambda t: {"Authorization": f"Bearer {t}"}
def ok(label, r, code=200):
    good = r.status_code == code; print(("PASS" if good else "FAIL"), label, r.status_code, "" if good else r.text[:300]); 
    if not good: sys.exit(1)
    return r.json() if r.content and "json" in r.headers.get("content-type","") else None
ok("invite page /bluebook/?invite= serves SPA", requests.get(B + sys.argv[1]))
ok("teacher redeem without terms refused", requests.post(B+"/auth/invite/redeem", json={"token": tok(sys.argv[1]), "password": PW}), 422)
t = ok("teacher redeem + accept terms", requests.post(B+"/auth/invite/redeem", json={"token": tok(sys.argv[1]), "password": PW, "accept_terms": True}))
tt = t["token"]; print("  products:", t.get("products"))
assert t.get("products") == ["bluebook"], "Original must be OFF"
c = ok("create course", requests.post(B+"/bluebook/courses", json={"name": "Alpha test", "code": "ALPHA1"}, headers=H(tt)), 201)
conds = {"blockCopy": True, "blockAI": True, "blockWeb": False, "aiDetect": False, "spellChk": True}
ex = ok("create exam (25 min, paste blocked, consistency off)", requests.post(B+"/bluebook/exams", json={"title": "Practice prompt 1", "status": "ACTIVE", "duration": 25, "questions": ["Describe a city that exists only at night."], "conditions": conds, "course_id": c["id"]}, headers=H(tt)), 201)
emails = [f"volunteer{i:02d}@example.test" for i in range(1, 21)]
rows = ok("add 20 students (no email)", requests.post(B+f"/bluebook/courses/{c['id']}/students", json={"students": [{"email": e, "name": f"V{i}"} for i, e in enumerate(emails, 1)], "send_email": False}, headers=H(tt)))["students"]
assert len(rows) == 20 and all(r.get("invite_path") for r in rows), rows[:2]
print("  20 invite links issued; emailed:", sum(r["emailed"] for r in rows))
sealed = 0
for r in rows[:3]:
    s = ok(f"student {r['email']} redeem", requests.post(B+"/auth/invite/redeem", json={"token": tok(r["invite_path"]), "password": PW}))
    ok("  reused link refused", requests.post(B+"/auth/invite/redeem", json={"token": tok(r["invite_path"]), "password": PW}), 400)
    st = ok("  student login", requests.post(B+"/auth/login", json={"email": r["email"], "password": PW}))["token"]
    me = requests.get(B+"/bluebook/me/exams", headers=H(st)); ok("  sees course exam", me)
    assert ex["id"] in me.text
    ok("  start exam", requests.post(B+f"/bluebook/me/exams/{ex['id']}/start", headers=H(st)))
    ok("  seal submission", requests.post(B+"/bluebook/submissions", json={"exam_id": ex["id"], "student_id": s["user_id"] if "user_id" in s else s.get("student_id"), "word_count": 40, "text": "night city " * 20}, headers=H(st)), 201)
    sealed += 1
subs = ok("teacher sees submissions", requests.get(B+"/bluebook/submissions", params={"exam_id": ex["id"]}, headers=H(tt)))
n = len(subs) if isinstance(subs, list) else len(subs.get("submissions", subs.get("items", [])))
print("  teacher sees", n, "submissions; any score fields:", "aiScore" in str(subs) and "null" not in str(subs))
print("RESULT: OK", sealed, "students joined and sealed; tenant", t.get("tenant_id"))
