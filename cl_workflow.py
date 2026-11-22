"""Evidence review for cover letters; a model review is never a hiring guarantee."""
import hashlib
import io
import json
import re
from pathlib import Path

FACTS_FILE = __import__('runtime_config').facts_file()
POLICY_VERSION = 'CL-evidence-v3'
CRITERIA = ['opening_match', 'specific_evidence', 'scope_tools_numbers', 'transferable_not_direct',
            'distinct_examples', 'no_flattery_or_company_guesses', 'defensible_claims', 'length_and_page']


def confirmed_facts():
    raw = FACTS_FILE.read_bytes() if FACTS_FILE.exists() else b'{"facts":[]}'
    return {**json.loads(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def cl_profile(profile):
    import copy
    result = copy.deepcopy(profile)
    overrides={item.get("fact_id"):item.get("canonical_english") for item in confirmed_facts().get("facts",[]) if item.get("fact_id")}
    for fact in result["facts"]:
        if overrides.get(fact["id"]): fact["text"]=overrides[fact["id"]]
    return result


def review_schema(profile):
    def obj(fields):
        return {'type':'object','additionalProperties':False,'required':list(fields),'properties':fields}
    text={'type':'string'}
    refs={'type':'array','items':{'type':'string','enum':[f['id'] for f in profile['facts'] if f['role']]}}
    paragraph=obj({'text':text,'refs':refs})
    requirement=obj({'requirement':text,'priority':{'type':'string','enum':['Core','Preferred']},
                     'evidence_type':{'type':'string','enum':['Direct','Transferable','No evidence']},
                     'refs':refs,'explanation':text})
    return obj({'language':text,'requirements':{'type':'array','minItems':3,'maxItems':5,'items':requirement},
                'letter':{'type':'array','minItems':4,'maxItems':4,'items':paragraph},
                'chinese':{'type':'array','minItems':4,'maxItems':4,'items':text},
                'unverified':{'type':'array','items':text}, 'writing_gaps':{'type':'array','items':text}, 'revisions':{'type':'array','items':text},
                'checks':obj({key:obj({'passed':{'type':'boolean'},'note':text}) for key in CRITERIA})})


def validate_review(bundle, profile):
    evidence={f['id']:f for f in cl_profile(profile)['facts'] if f['role']}
    paragraphs=bundle.get('letter',[])
    if len(paragraphs)!=4 or len(bundle.get('chinese',[]))!=4 or not all(bundle['chinese']):
        raise ValueError('CL必须包含四段正文及单独的四段中文对照。')
    if any(not p.get('text','').strip() for p in paragraphs):
        raise ValueError('CL正文段落不能为空。')
    if not 3<=len(bundle.get('requirements',[]))<=5:
        raise ValueError('CL需要3至5项岗位要求与证据匹配。')
    for req in bundle['requirements']:
        if req['priority'] not in {'Core','Preferred'} or req['evidence_type'] not in {'Direct','Transferable','No evidence'}:
            raise ValueError('岗位要求分类无效。')
        if any(ref not in evidence for ref in req['refs']) or (req['evidence_type']!='No evidence' and not req['refs']):
            raise ValueError('岗位匹配缺少已确认的事实依据。')
    if bundle['language'].lower().startswith('en') and not 250<=sum(len(p['text'].split()) for p in paragraphs)<=350:
        raise ValueError('英文CL正文必须为250至350词。')
    if not paragraphs[1]['refs'] or not paragraphs[2]['refs'] or set(paragraphs[1]['refs']) & set(paragraphs[2]['refs']):
        raise ValueError('CL两个经历段需要不同事实依据。')
    for p in paragraphs:
        if any(ref not in evidence for ref in p['refs']):
            raise ValueError('CL引用了不存在的简历事实。')
        source=' '.join(evidence[ref]['text'] for ref in p['refs'])
        numbers=lambda s:set(re.findall(r'\d+(?:[.,]\d+)*',s))
        if numbers(p['text'])-numbers(source):
            raise ValueError('CL包含缺少事实支持的数字。')
        validate_metric(p['text'])
    if set(bundle.get('checks',{})) != set(CRITERIA) or any(not isinstance(v.get('passed'),bool) or not v.get('note','').strip() for v in bundle['checks'].values()):
        raise ValueError('CL审核记录不完整。')
    return bundle


def validate_metric(text):
    for rule in confirmed_facts().get("metric_rules",[]):
        if re.search(rule["match"],text,re.I):
            if any(not re.search(pattern,text,re.I) for pattern in rule.get("required",[])):
                raise ValueError("A metric is missing required scope, ownership or units.")
            if any(re.search(pattern,text,re.I) for pattern in rule.get("forbidden",[])):
                raise ValueError("A metric uses a prohibited interpretation.")


def metadata(bundle, profile, *, complete=True, audit=None):
    passed=all(item['passed'] for item in bundle['checks'].values())
    return {'policy':POLICY_VERSION,'status':'待我审阅' if complete and passed and not bundle.get('writing_gaps',bundle['unverified']) else '草稿／待核实',
            'tailored':bool(complete and passed and not bundle.get('writing_gaps',bundle['unverified'])),'language':bundle['language'],'body':'\n\n'.join(p['text'] for p in bundle['letter']),
            'translation_zh':bundle['chinese'],'requirements':bundle['requirements'],'unverified':bundle['unverified'], 'writing_gaps':bundle.get('writing_gaps',bundle['unverified']),
            'revisions':bundle['revisions'],'checks':bundle['checks'],'facts_sha256':confirmed_facts()['sha256'],
            'resume_sha256':profile['sha256'],'audit':audit or {},'review_note':'模型辅助审核和确定性检查已执行，仍需本人审阅；不保证招聘结果。'}


def render_letter(profile, job, paragraphs, language='en'):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from pypdf import PdfReader
    from html import escape
    if language.lower().startswith(('ar','he','fa')):
        raise ValueError('当前PDF排版尚未支持该JD语言的从右到左文字，不能标记为完成；请人工排版。')
    chinese=language.lower().startswith(('zh','chinese'))
    font='Helvetica'
    if chinese:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light')); font='STSong-Light'
    body=ParagraphStyle('cl-body',fontName=font,fontSize=11,leading=16,spaceAfter=13)
    heading=ParagraphStyle('cl-heading',parent=body,fontSize=13,leading=17)
    story=[Paragraph(escape(profile['identity'][0]),heading),Paragraph(escape(profile['identity'][1]),body),
           Paragraph(escape(job['title']+' | '+job['company']),body),Paragraph('Dear Hiring Team,' if not chinese else '尊敬的招聘团队：',body)]
    story += [Paragraph(escape(p['text']),body) for p in paragraphs]
    story += [Spacer(1,3),Paragraph(('Kind regards,<br/>' if not chinese else '此致<br/>')+escape(profile['identity'][0]),body)]
    out=io.BytesIO();SimpleDocTemplate(out,leftMargin=62,rightMargin=62,topMargin=45,bottomMargin=45).build(story)
    pdf=out.getvalue()
    if len(PdfReader(io.BytesIO(pdf)).pages)!=1:
        raise ValueError('CL超出一页，请压缩措辞后重新生成；未保存该版本。')
    return pdf


def save_reviewed(store, job, profile, bundle_plan, paired_cv, connection):
    import uuid
    from core import stamp
    review=dict(bundle_plan['cl_review'])
    if review['facts_sha256']!=confirmed_facts()['sha256']:
        raise ValueError('已确认事实在生成期间发生变化，请重新生成。')
    pdf=render_letter(profile,job,bundle_plan['letter'],review['language'])
    review['local_checks']={'pdf_pages':1,'paragraphs':len(bundle_plan['letter']),
                            'body_words':sum(len(p['text'].split()) for p in bundle_plan['letter']),
                            'numeric_references_checked':bool(review.get('checks')),'metric_scope_checked':bool(review.get('checks'))}
    doc=uuid.uuid4().hex
    mapping=[{'text':p['text'],'facts':p['refs']} for p in bundle_plan['letter']]
    connection.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)',(doc,job['id'],stamp(),'CL',profile['sha256'],json.dumps(mapping),pdf,job['match']['jd_hash']))
    meta={'template':POLICY_VERSION,'created':stamp(),'renderer':'ReportLab','paired_cv':paired_cv,
          'pdf_sha256':hashlib.sha256(pdf).hexdigest(),'cl_review':review}
    connection.execute('INSERT INTO document_assets VALUES(?,NULL,?)',(doc,json.dumps(meta)))
    store.event(connection,job['id'],'CL evidence review',json.dumps({'version':doc,'status':review['status'],'facts_sha256':review['facts_sha256']}))
    return doc


def _generate_cl(store, job_id, *, parent=None):
    """Independent user-initiated CL entry, including explicitly labelled generic drafts."""
    from manual_workflow import job_row
    from matching import analyze, candidate, persist_match
    from industry import require_allowed
    job=job_row(store,job_id); require_allowed(job)
    profile=candidate(); match=analyze(job,profile,(job.get('match') or {}).get('checks'))
    persist_match(store,job,match,advance=False); job['match']=match
    if match['score'] is None:
        facts=[f for f in cl_profile(profile)['facts'] if f['role']]
        # Deliberately short generic draft: no claim to completed job-specific writing/review.
        paragraphs=[{'text':f"I am interested in discussing the {job['title']} role at {job['company']}. A complete job description is needed to tailor this draft.",'refs':[]},
                    {'text':facts[0]['text'],'refs':[facts[0]['id']]},
                    {'text':next(f['text'] for f in facts if f['role']!=facts[0]['role']),
                     'refs':[next(f['id'] for f in facts if f['role']!=facts[0]['role'])]},
                    {'text':'I would welcome a conversation once the responsibilities and requirements have been confirmed.','refs':[]}]
        review={'status':'草稿／待核实','tailored':False,'language':'en','body':'\n\n'.join(p['text'] for p in paragraphs),
                'translation_zh':[],'requirements':[],'unverified':['缺少完整JD；此为通用草稿，未完成岗位定制与事实审核'],
                'facts_sha256':confirmed_facts()['sha256'],'resume_sha256':profile['sha256'],'checks':{},'policy':POLICY_VERSION}
        selected={'letter':paragraphs,'cl_review':review}
    else:
        from material_model import plan_letter
        if parent:
            from manual_workflow import document_text
            original=document_text(store,parent)
            if original['job']!=job_id or original['kind']!='CL':
                raise ValueError('待审核材料不属于当前岗位。')
            selected,audit=plan_letter(job,profile,draft=original.get('body') or original['text'])
        else:
            selected,audit=plan_letter(job,profile)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        latest=job_row(store,job_id)
        if latest['jd']!=job['jd'] or candidate()['sha256']!=profile['sha256']:
            raise ValueError('JD或主简历在生成时发生变化，请重试。')
        cv=c.execute("SELECT id FROM documents WHERE job=? AND kind='CV' AND source_hash=? AND jd_hash=? ORDER BY rowid DESC LIMIT 1",(job_id,profile['sha256'],match['jd_hash'])).fetchone()
        doc=save_reviewed(store,job,profile,selected,cv[0] if cv else None,c)
        if parent:
            store.event(c,job_id,'CL revised after edit',json.dumps({'parent':parent,'version':doc}))
    return {'CL':doc}


def generate_cl(store, job_id, *, parent=None):
    from core import stamp, now
    import datetime as dt
    from manual_workflow import job_row
    job_row(store,job_id)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        previous=c.execute('SELECT * FROM generation_jobs WHERE job=?',(job_id,)).fetchone()
        if previous and previous['state']=='running' and (now()-dt.datetime.fromisoformat(previous['started'])).total_seconds()<900:
            raise ValueError('该岗位的材料仍在生成或审核，请等待本次任务完成。')
        c.execute("INSERT OR REPLACE INTO generation_jobs VALUES(?,'running',?,NULL,'')",(job_id,stamp()))
    try:
        result=_generate_cl(store,job_id,parent=parent)
    except Exception as error:
        with store.connect() as c:
            c.execute("UPDATE generation_jobs SET state='failed',finished=?,error=? WHERE job=?",(stamp(),str(error)[:1500],job_id))
            store.event(c,job_id,'CL generation failed',str(error)[:1500])
        raise
    with store.connect() as c:
        c.execute("UPDATE generation_jobs SET state='completed',finished=?,error='' WHERE job=?",(stamp(),job_id))
    return result
