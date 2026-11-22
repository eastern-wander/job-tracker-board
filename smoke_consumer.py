"""Durable consumer and restart test; fake profile, loopback only, no model."""
import json,pathlib,shutil,sqlite3,subprocess,sys,tempfile
# Reuse the fixture HTTP helpers without executing its top-level smoke.
source=(pathlib.Path(__file__).parent/"smoke_fixture.py").read_text()
exec(source[:source.index('with tempfile.TemporaryDirectory(prefix=')])
def child(folder,code):
    return subprocess.run([sys.executable,"-B","-c",code],cwd=folder,check=True,capture_output=True,text=True).stdout
with tempfile.TemporaryDirectory(prefix="tracker-consumer-") as name:
    folder=pathlib.Path(name)
    for p in ROOT.iterdir():
        if p.is_file() and p.suffix in {".py",".js",".html",".css",".svg"}:shutil.copy2(p,folder/p.name)
    subprocess.run([sys.executable,"-B","fixture_demo.py"],cwd=folder,check=True,stdout=subprocess.DEVNULL)
    child(folder,'import core,cv_worker; s=core.Store(core.ROOT/"data"); assert cv_worker.claim(s)')
    process=boot(folder)
    fake="""import core,cv_worker,runtime_config,cv_queue,io
from reportlab.pdfgen import canvas
def artifact(job,profile):
 out=io.BytesIO();pdf=canvas.Canvas(out);pdf.drawString(50,750,"TEST ONLY");pdf.save()
 return out.getvalue(),[{"id":f["id"],"text":f["text"]} for f in profile["facts"] if f["role"]],runtime_config.resume_docx().read_bytes(),{"template_sha256":cv_queue.digest_file(runtime_config.resume_docx())}
s=core.Store(core.ROOT/"data")
print(cv_worker.consume(s,adapter=artifact,test_mode=True))
"""
    try:
        state=request("/api/state")
        assert state["cv_queue"]["counts"]["failed"]==1
        assert not state["cv_queue"]["worker"]["enabled"]
        assert child(folder,fake).count("ready")==4
        assert child(folder,fake).strip()=="[]"
        with sqlite3.connect(folder/"data/tracker.sqlite3") as c:
            before=c.execute("SELECT id,kind FROM documents ORDER BY id").fetchall()
            assert len(before)==4 and all(kind=="CV" for _,kind in before)
            assert c.execute("SELECT count(*) FROM cv_queue_attempts").fetchone()[0]==5
            assert c.execute("SELECT count(*) FROM application_records").fetchone()[0]==0
    finally:
        process.terminate();process.wait(timeout=10)
    process=boot(folder)
    try:
        state=request("/api/state")
        assert state["cv_queue"]["counts"]["ready"]==4
        assert state["cv_queue"]["counts"]["failed"]==1
        assert state["cv_queue"]["used_today"]==5
        with sqlite3.connect(folder/"data/tracker.sqlite3") as c:
            assert c.execute("SELECT id,kind FROM documents ORDER BY id").fetchall()==before
        print(json.dumps({"interrupted_claim_failed":1,"ready_CV":4,"CL":0,"applications":0,"daily_attempts":5,
                          "second_process_no_duplicate":True,"clean_restart_preserved_document_ids":True,"model_enabled":False},indent=2))
    finally:
        process.terminate();process.wait(timeout=10)
