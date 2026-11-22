"""JD sponsorship evidence. Silence never implies an offer or a refusal."""
import re

def evidence(jd, needs_sponsorship=False):
    sentences=[x.strip() for x in re.split(r'\n+|(?<=[.!?])\s+',jd or '') if x.strip()]
    negative=r"no\s+(?:visa\s+|work\s+permit\s+)?sponsorship(?:\s+(?:is\s+)?(?:available|provided|offered))?|(?:cannot|can not|unable to|will not|do not|does not|not able to)\s+(?:provide\s+|offer\s+)?(?:visa\s+)?sponsor(?:ship)?|sponsorship\s+(?:is\s+)?not\s+(?:available|provided|offered)|不提供.{0,6}(?:签证|担保|赞助)|(?:ビザ|在留資格).{0,15}(?:サポートなし|支援なし|支援しません|不可)"
    quotes=[s for s in sentences if re.search(negative,s,re.I)]
    # "No sponsorship required" describes applicant needs, not employer refusal.
    quotes=[s for s in quotes if not re.search(r'no\s+(?:visa\s+)?sponsorship\s+(?:is\s+)?required',s,re.I)]
    if quotes:return {'state':'明确不提供赞助','evidence':quotes,'excluded':bool(needs_sponsorship)}
    offered=[s for s in sentences if re.search(r'(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|provided|offered)|(?:provide|offer)\s+(?:visa\s+)?sponsorship|\b(?:we\s+(?:do\s+)?sponsor\s+visas?|visa\s+sponsorship\s*[:：]\s*provided)\b|(?:ビザ|在留資格).{0,12}(?:サポートあり|支援あり)',s,re.I)]
    if offered:return {'state':'提及提供赞助，仍需核实适用条件','evidence':offered,'excluded':False}
    return {'state':'未知：JD未明确说明赞助','evidence':[],'excluded':False}
