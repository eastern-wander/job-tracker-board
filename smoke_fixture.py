"""Offline fixture API and clean-process-restart smoke test. Run with Python dependencies installed."""
import json, pathlib, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
PORT=8147
def request(route,payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}"+route,data=data,
        headers={"Origin":f"http://127.0.0.1:{PORT}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
def boot(folder):
    process=subprocess.Popen([sys.executable,"-B","app.py","--no-scheduler","--port",str(PORT)],
        cwd=folder,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(60):
        if process.poll() is not None:raise RuntimeError("Fixture server failed to start")
        try:
            health=request("/api/health")
            assert health["fixture_mode"] is True
            return process
        except OSError:time.sleep(.1)
    process.terminate();process.wait();raise RuntimeError("Fixture server timeout")
def counts(folder):
    with sqlite3.connect(folder/"data/tracker.sqlite3") as c:
        return {table:c.execute("SELECT count(*) FROM "+table).fetchone()[0]
                for table in ["jobs","cv_queue","documents","application_records","runs"]}
with tempfile.TemporaryDirectory(prefix="tracker-fixture-") as name:
    folder=pathlib.Path(name)
    for p in ROOT.iterdir():
        if p.is_file() and p.suffix in {".py",".js",".html",".css",".svg"}:shutil.copy2(p,folder/p.name)
    subprocess.run([sys.executable,"-B","fixture_demo.py"],cwd=folder,check=True,stdout=subprocess.DEVNULL)
    process=boot(folder)
    try:
        initial=counts(folder)
        a=request("/api/run",{"active_only":True})
        b=request("/api/run",{"active_only":True})
        assert a["added"]==b["added"]==0
        after=counts(folder)
        assert after["jobs"]==initial["jobs"]==5
        assert after["cv_queue"]==initial["cv_queue"]==5
        assert after["documents"]==after["application_records"]==0
        request("/api/cv-queue/mock",{})
        before_restart=counts(folder)
        state=request("/api/state")
        assert state["cv_queue"]["counts"]["mock_completed"]==5
    finally:
        process.terminate();process.wait(timeout=10)
    process=boot(folder)
    try:
        state=request("/api/state")
        assert counts(folder)==before_restart
        assert state["cv_queue"]["counts"]["mock_completed"]==5
        assert state["scheduler_health"]["state"]=="disabled"
        print(json.dumps({"initial":initial,"after_two_discoveries":after,"after_mock_and_restart":counts(folder),
                          "fixture_only":True,"clean_restart":"passed","live_calls":0},indent=2))
    finally:
        process.terminate();process.wait(timeout=10)
