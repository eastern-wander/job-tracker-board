"""Patch only the verified summary and bullet text in a copy of main.docx."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from html import escape
from zipfile import ZipFile

from pypdf import PdfReader
from io import BytesIO
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
DOC = "word/document.xml"


def norm(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def edited_copy(source, destination, profile, selected):
    facts = {row["id"]: row for row in profile["facts"] if row["role"]}
    rewrites = {row["id"]: row["text"] for row in selected["resume_bullets"]}
    order = [row["id"] for row in selected["resume_bullets"]]
    with ZipFile(source) as original:
        tree = etree.fromstring(original.read(DOC))
        paragraphs = tree.xpath("./w:body/w:p", namespaces=NS)
        texts = ["".join(p.xpath(".//w:t/text()", namespaces=NS)) for p in paragraphs]
        summary = [i for i, text in enumerate(texts[:-1]) if text.strip() == "SUMMARY"]
        if len(summary) != 1:
            raise ValueError("Could not identify the original CV summary slot.")
        changed = {summary[0]+1: selected["resume_summary"]}
        groups = {}
        unused = {}
        for key,row in facts.items():
            unused.setdefault(norm(row["text"]),[]).append(key)
        for index, paragraph in enumerate(paragraphs):
            text = norm(texts[index])
            if not text or not paragraph.xpath("./w:pPr/w:numPr", namespaces=NS):
                continue
            ids=unused.get(text,[])
            key=ids.pop(0) if ids else None
            if text in unused and not ids:
                del unused[text]
            if not key:
                raise ValueError("The editable CV bullets differ from the verified Main CV.")
            groups.setdefault(facts[key]["role"], []).append(index)
        if unused:
            raise ValueError("The editable CV is missing verified experience slots.")
        for role, slots in groups.items():
            replacements = [rewrites[key] for key in order if facts[key]["role"] == role]
            if len(replacements) != len(slots):
                raise ValueError("The model did not preserve the template bullet counts.")
            changed.update(zip(slots, replacements))
        for index, text in changed.items():
            nodes = paragraphs[index].xpath(".//w:t", namespaces=NS)
            if not nodes:
                raise ValueError("Could not edit an original text run.")
            # Preserve the original paragraphs, runs, run properties and numbering.
            nodes[0].text = text
            for node in nodes[1:]:
                node.text = ""
        with ZipFile(destination, "w") as out:
            for entry in original.infolist():
                out.writestr(entry, etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
                             if entry.filename == DOC else original.read(entry))


_CACHE = {}


def render(profile, selected, *, with_source=False):
    source = __import__("runtime_config").resume_docx()
    if not source.is_file():
        raise ValueError("Configure a readable resume_docx matching the verified resume PDF.")
    cache_key = hashlib.sha256(source.read_bytes() + profile["sha256"].encode() + json.dumps(selected, sort_keys=True).encode()).hexdigest()
    if cache_key in _CACHE:
        cached = _CACHE[cache_key]
        return cached if with_source else cached[:2]
    office = shutil.which("soffice")
    if not office:
        raise ValueError("The local Word-to-PDF renderer is unavailable.")
    with tempfile.TemporaryDirectory(prefix="tracker-cv-template-") as folder:
        root = Path(folder)
        editable = root/"tailored.docx"
        config = root/"fonts.conf"
        font_paths = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                      str(Path.home()/"Library/Fonts"), "/Applications/wpsoffice.app/Contents/Resources/office6/fonts"]
        config.write_text("<fontconfig>"+ "".join(f"<dir>{escape(path)}</dir>" for path in font_paths)
                          +f"<cachedir>{escape(str(root/'font-cache'))}</cachedir>"
                          +"""<match target="pattern">
                            <test name="family" compare="eq"><string>Times New Roman Bold</string></test>
                            <edit name="family" mode="assign" binding="strong"><string>Times New Roman</string></edit>
                            <edit name="weight" mode="assign"><const>bold</const></edit>
                          </match></fontconfig>""")
        # Shorten only the least relevant slots until the original page budget is met.
        full = selected["resume_bullets"]
        alternatives = [full]
        if all("compact" in row for row in full):
            priority = set(selected["cv_facts"])
            candidates = sorted(range(len(full)), key=lambda i: (full[i]["id"] in priority,
                                -(len(full[i]["text"]) - len(full[i]["compact"]))))
            adjusted = list(full)
            for index in candidates:
                adjusted[index] = {**adjusted[index], "text": adjusted[index]["compact"]}
                alternatives.append(list(adjusted))
        if selected.get("local_source"):
            alternatives = [alternatives[-1]]
        output = root/"tailored.pdf"
        for bullets in alternatives:
            edited_copy(source, editable, profile, {**selected, "resume_bullets": bullets})
            output.unlink(missing_ok=True)
            try:
                result = subprocess.run([office, f"-env:UserInstallation={(root/'office').as_uri()}",
                                         "--headless", "--convert-to", "pdf", "--outdir", folder, str(editable)],
                                        env={**os.environ, "FONTCONFIG_FILE":str(config)}, capture_output=True, timeout=55)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError("The original-template CV could not be rendered.") from error
            if result.returncode or not output.exists():
                raise ValueError("The original-template CV could not be rendered.")
            pdf = output.read_bytes()
            reader = PdfReader(BytesIO(pdf))
            if len(reader.pages) == 1 and "SKILLS" in reader.pages[0].extract_text():
                if with_source:
                    metadata = {"template": "main.docx-v2", "template_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                "template_filename": source.name, "bullet_count": len(bullets),
                                "renderer": "LibreOffice / original OOXML", "pages": 1}
                    result = (pdf, bullets, editable.read_bytes(), metadata)
                    if len(_CACHE) >= 16:
                        _CACHE.pop(next(iter(_CACHE)))
                    _CACHE[cache_key] = result
                    return result
                return pdf, bullets
        raise ValueError("The revised CV did not fit one page at the original settings.")
