"""Generate explicitly fake, local-only demo data; never import personal files."""
from pathlib import Path
import json
import os
from zipfile import ZipFile
from xml.sax.saxutils import escape

def create_profile(folder):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    pdfmetrics.registerFont(TTFont("Fixture", str(Path(reportlab.__file__).parent/"fonts/Vera.ttf")))
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    lines=["Alex Example","demo@example.invalid","SUMMARY",
        "Operations professional coordinating projects, clients and partnerships with practical research, logistics and analytical skills.",
        "EDUCATION","Example University | Business Studies",
        "PROFESSIONAL EXPERIENCE"]
    for i in range(1,5):
        lines += [f"Example Organization {i} | Operations Coordinator",
          "• Coordinated project delivery, supplier contracts and client onboarding with stakeholder reporting.",
          "• Used Excel, SQL, Tableau and CRM analytics for research, campaigns and commercial analysis."]
    lines += ["SKILLS","Excel, SQL, Tableau, CRM, Analytics, Stakeholder Management, Project Coordination"]
    pdf=folder/"main.pdf"; c=canvas.Canvas(str(pdf))
    y=800
    for line in lines:
        c.setFont("Fixture",8); c.drawString(42,y,line); y-=17
    c.save()
    paragraphs=[]
    for line in lines:
        props='<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>' if line.startswith("•") else ''
        paragraphs.append("<w:p>"+props+"<w:r><w:t>"+escape(line.lstrip("• "))+"</w:t></w:r></w:p>")
    with ZipFile(folder/"main.docx","w") as z:
        z.writestr("[Content_Types].xml",'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>')
        z.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+"".join(paragraphs)+'<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="600" w:bottom="600" w:left="600" w:right="600"/></w:sectPr></w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>')
        z.writestr("word/numbering.xml",'<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
    (folder/"confirmed_facts.json").write_text('{"facts":[]}')

def demo_jobs():
    # Publication times are deliberately unknown; no production dates are fabricated.
    return [dict(title="Operations Coordinator",company="Demo Employer "+str(i),location=location,country=country,
        source="Manual",external_id="fixture-"+str(i),url="https://example.invalid/jobs/"+str(i),
        vacancy="Active",industry_declared="traditional",jd_quality="Full",posted="",
        jd="Responsibilities: Manage operations, projects, clients, partnerships, suppliers, contracts, campaigns and research. Coordinate vendor onboarding, logistics and delivery. Required tools include Excel, SQL, Tableau, CRM, analytics and commercial analysis. This is an enterprise software operations role. Visa sponsorship is not stated.")
        for i,(country,location) in enumerate([("Canada","Vancouver"),("United States","Seattle"),("Japan","Tokyo"),("UAE","Dubai"),("UK","London")],1)]

def setup(root):
    root=Path(root).resolve()
    config_path=root/"runtime.local.json"
    if (root/"data/tracker.sqlite3").exists() and (not config_path.exists() or not json.loads(config_path.read_text()).get("fixture_mode")):
        raise ValueError("Refusing to seed an existing non-fixture workspace.")
    profile=root/"data/profile"; create_profile(profile)
    config={"fixture_mode":True,"data_dir":"data","resume_pdf":"data/profile/main.pdf","resume_docx":"data/profile/main.docx",
            "facts_file":"data/profile/confirmed_facts.json","model_calls_enabled":False}
    (root/"runtime.local.json").write_text(json.dumps(config,indent=2))
    # Imports occur after local config exists.
    from core import Store
    import app
    store=Store(root/"data")
    for job in demo_jobs(): store.ingest(job)
    app.batch_match(store)
    with store.connect() as c:
        for key,value in (("boards",""),("lever_boards","")):
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",(key,json.dumps(value)))
    return store

if __name__=="__main__":
    setup(Path(__file__).resolve().parent)
    print("Created fake local demo. Start with: python app.py --no-scheduler --port 8137")
