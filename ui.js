"use strict";
const $=id=>document.getElementById(id);
const content=$("content"),dialog=$("dialog"),dialogBody=$("dialog-body");
let state,view=({"#imports":"My Imports","#applications":"Application Tracker","#assisted":"Assisted Apply"})[location.hash]||"Dashboard",busy=false,tag="Candidates 60+",query="";
const labels={"Dashboard":"Dashboard","Job Discovery":"Job Discovery","Candidate Pool":"Candidate Pool","My Imports":"My Imports","Application Tracker":"Application Tracker","Assisted Apply":"Assisted Apply","Settings":"Settings"};
const words={
"United States":"United States","UK":"UK","Canada":"Canada","UAE":"UAE","Japan":"Japan","Unverified":"Unverified","Active":"Verified open","Closed":"Closed","Other":"Other",
"Full":"Full","Partial":"Partial","Displayed":"Platform display date","Reposted":"Repost date","Last published":"Last published",
"Employer website / ATS":"Employer website / ATS","Email":"Email","On platform":"On platform","External":"External","traditional":"Traditional industry","web3":"Web3 / Crypto",
"Import Jobs":"Import Jobs","Paste job URLs":"Paste job URLs","Select a CSV or JSON export":"Select a CSV or JSON export",
"Manual search sample (optional)":"Manual search sample (optional)","Listing URL":"Listing URL","Job title":"Job title","Employer":"Employer",
"Location":"Location","Official employer URL":"Official employer URL","Observed application route":"Observed application route",
"Employer closure evidence URL":"Employer closure evidence URL","Requisition ID":"Requisition ID","Date as shown":"Date as shown",
"Date type":"Date type","Verified industry":"Verified industry","JD completeness":"Job description completeness","Permitted job description":"Full job description",
"Listing":"Job","Remove listing":"Remove listing","Add pasted URLs":"Add pasted URLs","Load export":"Load export",
"Paste JSON export":"Paste JSON export","Load pasted export":"Load pasted export","Add a listing":"Add a listing",
"Preview and score":"Preview and score","Open single-job form":"Open single-job form","Controlled import preview":"Controlled import preview",
"Select all importable listings":"Select all importable listings","Import selected listings":"Import selected listings","Back to edit listings":"Back to edit listings",
"Total unique jobs":"Unique jobs","Verified active jobs":"Verified open","Verified dates within 14 days":"Verified dates within 14 days",
"Verified original posting dates":"Verified original publication dates","Jobs scoring 80+":"Score 80+","Possible duplicates":"Possible duplicates",
"Already tracked":"Already tracked","Manual review":"Manual review","Missing job descriptions":"Missing full job description",
"Work authorization requires manual evidence. Select only listings you want to import for review.":"Work authorization requires evidence. Select only listings you want to import for review.",
"Company":"Company","Source":"Discovery source","Market":"Country or region","Original posting date":"Original publication date",
"Date evidence":"Date evidence","Platform date type":"Platform date type","Platform date as displayed":"Platform date as displayed",
"Source job ID":"Source job ID","Employer requisition":"Employer requisition","Work arrangement":"Work arrangement","Salary":"Salary",
"Vacancy":"Vacancy status","Job description":"Job description","Import":"Import","Paste the complete job description":"Paste the complete job description",
"Country":"Country","Employer requisition ID":"Employer requisition","Save as a separate job":"Save as a separate job",
"Save the complete description. Eligibility will remain separate from material preparation.":"Save the full job description. Eligibility will remain separate from material preparation.",
"Confirm complete JD and save":"Confirm the job description is complete and save","Original listing":"Original listing","Verified employer listing":"Verified employer listing",
"Source listing":"Source listing","Possible employer listing":"Possible employer listing","No vacancies extracted.":"No vacancies extracted.",
"Login required":"Login required","Redirected":"Redirected","Summary only":"Summary only","Explicitly closed":"Explicitly closed",
"Request failed":"Request failed","Unknown":"Unknown","Readable":"Readable","None":"None",
"Met":"Verified met","Failed":"Not met","Not required":"Not required",
"Work authorization":"Work authorization","Visa sponsorship":"Visa sponsorship","Employer-specific restrictions":"Employer-specific restrictions",
"License / certification":"License / certification","Languages":"Languages","Technical requirements":"Technical requirements","Experience":"Experience","Location / relocation":"Location / relocation"
};
const workflowLabel=s=>({"待生成材料": "Materials pending", "待审核": "Ready for review", "待我投递": "Ready for manual submission", "需我处理": "Action needed", "提交结果待核实": "Submission unverified", "已投递": "Submitted", "面试中": "Interviewing", "被拒": "Rejected", "已关闭": "Closed"})[s]||s;
const systemLabels={"\u6a21\u62df\u6570\u636e": "Demo data", "\u6b63\u5f0f\u6570\u636e": "Live local data", "\u9694\u79bb\u9a8c\u6536": "Isolated test data", "\u5df2\u83b7\u9080\u7ea6": "Offer received", "\u65e5\u671f\u5f85\u6838\u5b9e": "Original date unverified", "\u91cd\u53d1": "Reposted", "\u67e5\u770b\u65f6\u95f4\u5f85\u6838\u5b9e": "Viewing time unverified", "\u65e5\u671f\u8fb9\u754c": "Date boundary uncertain", "\u5e73\u53f0\u663e\u793a\u8fd1\u671f": "Platform shows a recent date", "\u65e5\u671f\u8bc1\u636e\u51b2\u7a81": "Conflicting date evidence", "\u6838\u5b9e\u4e3a\u8fd1\u671f": "Verified recent original posting", "\u8d85\u8fc7 72 \u5c0f\u65f6": "Original posting more than 72 hours old", "\u5f85\u6211\u5ba1\u9605": "Ready for your review", "\u8349\u7a3f\uff0f\u5f85\u6838\u5b9e": "Draft \u00b7 not verified", "\u660e\u786e\u4e0d\u63d0\u4f9b\u8d5e\u52a9": "Explicitly no visa sponsorship", "\u63d0\u53ca\u63d0\u4f9b\u8d5e\u52a9\uff0c\u4ecd\u9700\u6838\u5b9e\u9002\u7528\u6761\u4ef6": "Mentions visa sponsorship; verify eligibility", "\u672a\u77e5\uff1aJD\u672a\u660e\u786e\u8bf4\u660e\u8d5e\u52a9": "Unknown: posting does not specify sponsorship", "\u672c\u5730\u6a21\u677f\u8349\u7a3f\u5c1a\u672a\u5b8c\u6210\u5c97\u4f4d\u4e8b\u5b9e\u5ba1\u6838": "The local template draft has not been fact-checked against this job", "\u539f\u7b80\u5386\u539f\u6587": "Original r\u00e9sum\u00e9 wording"};
const systemLabel=value=>systemLabels[value]||value;
const dateLabel=signal=>signal?[systemLabel(signal.label),...(signal.flags||[]).map(systemLabel)].filter(Boolean).join(" · "):"Original date unverified";
function tx(value){if(value==null)return value;return words[value]||value;}
const node=(name,text,attrs={})=>{const e=document.createElement(name);if(text!=null)e.textContent=tx(text);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;};
const button=(label,fn,cls)=>{const e=node("button",label,{type:"button",...(cls?{class:cls}:{})});e.addEventListener("click",()=>action(fn));return e;};
const link=(label,href,download=false)=>node("a",label,{href,target:"_blank",rel:"noopener noreferrer",class:"button",...(download?{download:""}:{})});
const box=(...items)=>{const d=node("div",null,{class:"actions"});d.append(...items);return d;};
const section=(title,...items)=>{const s=node("section");s.append(node("h2",title),...items);return s;};
const empty=label=>node("p",label,{class:"empty"});
function notice(text){$("notice").textContent=tx(text);$("notice").hidden=!text;}
async function api(path,data){const r=await fetch(path,data==null?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});const value=await r.json();if(!r.ok)throw Error(value.error||"Action failed");return value;}
async function action(fn){if(busy)return;busy=true;try{await fn();}catch(e){const text="Action not completed. "+friendlyError(e.message);if(dialog.open)alert(text);else notice(text);}finally{busy=false;}}
function friendlyError(message){return message || "Something went wrong. Please try again."; }
async function refresh(){
 try{state=await api("/api/state");render();}
 catch(error){
  let health={};try{health=await api("/api/health");}catch(ignore){}
  content.replaceChildren(section("Job data is temporarily unavailable",node("p","Keep your existing data. Do not repeat imports or material generation."),
   node("p","Scheduler status: "+(health.scheduler?.state||"Service unavailable")+" · "+(health.scheduler?.error||"")),
   button("Check again",()=>refresh())));
  throw error;
 }
}
function showDialog(title,...items){$("dialog-title").textContent=tx(title);dialogBody.replaceChildren(...items);if(!dialog.open)dialog.showModal();}
function field(label,name,opts={}){let input;if(opts.options){input=node("select",null,{name});input.append(...opts.options.map(x=>node("option",x,{value:x})));}else input=node(opts.area?"textarea":"input",null,{name,...(opts.area?{}:{type:opts.type||"text"})});if(opts.value!=null)input.value=opts.value;if(opts.required)input.required=true;const wrap=node("label",label,opts.area?{class:"wide"}:{});wrap.append(input);return wrap;}
function form(fields,label,submit){const f=node("form"),g=node("div",null,{class:"form-grid"});g.append(...fields);f.append(g,node("button",label,{class:"primary",type:"submit"}));f.addEventListener("submit",e=>{e.preventDefault();action(()=>submit(Object.fromEntries(new FormData(f))));});return f;}
function metrics(items){const g=node("div",null,{class:"metrics"});for(const[label,value]of Object.entries(items)){const card=node("div",null,{class:"metric"});card.append(node("strong",String(value)),node("small",label));g.append(card);}return g;}
function fitLabel(score,eligible){return eligible?"Eligibility verified":score>=80?"High match · needs verification":"";}
const readyCV=job=>Boolean(job.current_documents?.CV);
function current(job,kind){return job.current_documents?.[kind]||null;}
function stale(job,doc){return doc&&(job.materials_stale||doc.jd_hash!==job.match?.jd_hash||doc.source_hash!==job.match?.source_hash);}
function materialActions(job){
 const group=node("div",null,{class:"material-actions"});
 const gen=job.generation;
 group.append(button(gen?.state==="running"?"Generating…":"Generate materials",()=>generate(job),"primary"));
 if(gen?.state==='completed')group.append(node('small','Generation finished in '+gen.elapsed_seconds+' seconds. Review the materials; no application was submitted.'));
 if(gen?.state==='running')group.append(node('p',(gen.step||'Working in the background')+' · elapsed: '+gen.elapsed_seconds+' seconds'));
 if(gen?.state==="failed")group.append(node("p","Generation failed · "+friendlyError(gen.error),{class:"notice-line"}));
 for(const[kind,label]of [["CV","CV"],["CL","Cover letter"]]){
   const d=current(job,kind),row=box();
   row.append(node("strong",label));
   if(!d){row.append(node("small","Not generated"));}else{
     row.append(link("Preview "+label,"/pdf/"+d.id),link("Download "+label,"/pdf/"+d.id+"?download=1",true));
     if(kind==="CL"){
       const review=d.metadata?.cl_review;
       row.append(node("small",systemLabel(review?.status)||"Historical version · not reviewed under the current rules"),button("View, copy, or edit cover letter",()=>letterView(job,d)));
     }
     if(kind==="CV")row.append(link("Download DOCX","/docx/"+d.id,true));
     row.append(node("small",d.created+" · Version "+d.id.slice(0,8)+(stale(job,d)?" · Materials may need an update":kind==="CL"?"":" · Complete")));
   }group.append(row);
 }
 return group;
}
async function generate(job){
 const genLabel=node("p","Generating an English CV and a cover letter in the job description\u0027s language with high reasoning. New versions will be saved when ready.");
 showDialog("Generate materials",genLabel,link("View job record","/#job="+job.id));
 try{await api("/api/manual/generate",{id:job.id,use_model:true,regenerate:true});await refresh();detail(job.id);}
 catch(e){await refresh();detail(job.id);throw e;}
}
function handoffButton(job){
 return button("Open application link",async()=>{
   const tab=window.open("about:blank","_blank");
   if(!tab)throw Error("Your browser blocked the new tab. Allow pop-ups and try again.");
   tab.opener=null;
   try {const result=await api("/api/manual/handoff",{id:job.id});tab.location.replace(result.url);await refresh();}
   catch(error){tab.close();throw error;}
 });
}
function application(job){const r=job.application_record;if(r&&r.active)return r;return null;}
function recordView(job){
 const r=application(job),legacy=job.events.find(e=>e.kind==="Manually Applied");
 const lastOpen=job.events.find(e=>e.kind==="Application page opened"||e.kind==="Official application opened");
 const legacyData=legacy&&!job.application_record?JSON.parse(legacy.detail):null;
 const data=r||legacyData;const history=node("ul");
 for(const e of job.events.filter(e=>/Applied|Submitted|receipt|corrected|opened|Pilot|Materials approved/.test(e.kind)))
   history.append(node("li",e.created+" · "+eventLabel(e.kind)+" · "+eventDescription(e)));
 const actions=box();
 if(data){
   actions.append(button("Add receipt",()=>showDialog("Add receipt",form([field("Confirmation email reference or application number","receipt",{required:true})],"Save",async x=>{await api("/api/manual/receipt",{id:job.id,...x});await refresh();recordView(state.jobs.find(j=>j.id===job.id));}))),
   button("Correct record",()=>showDialog("Correct record",form([field("Application date","date",{type:"date",value:data.date,required:true}),field("Actual submission channel","channel",{options:["Employer website / ATS","LinkedIn","Indeed","Email","Other"],value:data.channel}),field("Reason for correction","reason",{required:true,area:true})],"Save correction",async x=>{await api("/api/manual/correct",{id:job.id,...x});await refresh();recordView(state.jobs.find(j=>j.id===job.id));}))),
   button("Undo incorrect status",()=>showDialog("Undo incorrect status",node("p","Give a reason to remove this from the count. The original record is retained."),form([field("Reason","reason",{required:true,area:true})],"Confirm removal from count",async x=>{await api("/api/manual/correct",{id:job.id,...x,cancel:true});await refresh();detail(job.id);}))));
 }else if(job.current_documents?.CV&&job.current_documents?.CL)actions.append(button("Record as submitted",()=>manualApplication(job)));
 showDialog("Application Tracker",node("h3",job.company+" · "+job.title),node("p","Status · "+workflowLabel(job.workflow_state)+(data&&!data.receipt?" · Receipt missing":data?" · Receipt recorded":"")),
   node("p","Discovery sources · "+[...new Set(job.source_links.map(s=>s.platform))].join(", ")),
   box(link("Job link",job.url||job.apply_url),link("Application link",job.platform_application?.url||job.apply_url||job.url)),
   data?node("p","Application date "+data.date+" · Actual channel "+tx(data.channel)+" · CV "+(data.cv||data.CV)+" · Cover letter "+(data.cl||data.CL)):node("p","No actual submission recorded."),
   lastOpen?node("p","Application page last opened "+lastOpen.created):node("span"),
   data?node("p","Time "+(data.submitted_at||legacy?.created||"History")+" · Receipt "+(data.receipt||"Not provided")+" · Notes "+(data.notes||"None")):node("span"),
   actions,section("History",history));
}
function manualApplication(job){
 const versions=(kind,label)=>field(label,kind.toLowerCase(),{options:["",...job.documents.filter(d=>d.kind===kind).map(d=>d.id)],value:current(job,kind)?.id,required:true});
 showDialog("Record as submitted",node("p","Record this only after submitting. Opening a page, downloads, drafts, and unknown outcomes do not count."),
 form([field("Application date","date",{type:"date",value:state.today,required:true}),
 field("Actual submission channel","channel",{options:["Employer website / ATS","LinkedIn","Indeed","Email","Other"]}),
 versions("CV","CV version used"),versions("CL","Cover letter version used"),field("Receipt or application number (optional)","receipt"),field("Notes","notes",{area:true})],
 "Confirm actual submission",async x=>{await api("/api/manual/application",{id:job.id,...x,confirmed:true});await refresh();recordView(state.jobs.find(j=>j.id===job.id));}));
}
function eventDescription(event){
 try {
   const d=JSON.parse(event.detail);
   if(event.kind==="Manually Applied")return "Application date "+d.date+" · Actual channel "+tx(d.channel)+" · CV "+d.CV+" · Cover letter "+d.CL+" · "+(d.notes||"");
   if(event.kind==="Manual submission corrected")return (d.cancel?"Undo incorrect status":"Correct date or channel")+" · Reason "+d.reason;
   if(event.kind==="Materials approved")return "CV "+d.CV+" · Cover letter "+d.CL;
   if(event.kind==="Pilot review")return d.blockers.length?"Awaiting review of information and eligibility":"Awaiting your confirmation of actual submission";
 }catch(error){}
 return event.detail;
}
function eventLabel(kind){return {"Manually Applied":"Manual submission","Manual submission receipt":"Receipt verified","Manual submission corrected":"Submission corrected","Application page opened":"Application page opened","Official application opened":"Employer site opened","Materials approved":"Materials reviewed","Pilot review":"Pre-submission review","Submitted":"Submission confirmed"}[kind]||kind;}
function docs(job){
 return job.documents.map(d=>box(node("span",(d.kind==="CV"?"CV":"Cover letter")+" · "+d.created+" · "+d.id.slice(0,8)),
 node("small",d.metadata?"Template "+d.metadata.template:"Historical materials · Older layout"),
 link("Preview ","/pdf/"+d.id),link("Download ","/pdf/"+d.id+"?download=1",true),...(d.kind==="CL"?[button("View, copy, or edit",()=>letterView(job,d))]:[])));
}
function qualificationForm(job){
 const fields=state.checks.flatMap(key=>[
   field(key,key,{options:key==="Work authorization"?["Unverified","Met","Failed"]:["Unverified","Met","Not required","Failed"],value:job.match?.checks[key]?.state}),
   field(tx(key)+" evidence",key+"-reason",{value:job.match?.checks[key]?.reason,area:true})
 ]);
 showDialog("Verify eligibility",node("p","Enter only confirmed facts. Unstated or uncertain conditions remain unverified."),
 form(fields,"Save and reassess",async data=>{
   const checks=Object.fromEntries(state.checks.map(key=>[key,{state:data[key],reason:data[key+"-reason"]}]));
   await api("/api/score",{id:job.id,checks});await refresh();detail(job.id);
 }));
}
function detail(id){
 const j=state.jobs.find(j=>j.id===id);if(!j)return;
 history.replaceState(null,"","#job="+id);
 const originals=[...new Set([...(j.source_links||[]).map(x=>x.url),...j.events.filter(e=>e.kind==="Manually imported").map(e=>e.detail)].filter(url=>/^https?:\/\//i.test(url||"")))];
 const actions=box(...originals.map(url=>link("Original listing link",url)),button("Manual entry / advanced editing",()=>importJob(j.url||"",j)),button("Add job description",()=>pasteJD(j)),button("Verify eligibility",()=>qualificationForm(j)),button("Application Tracker",()=>recordView(j)),button("Review before submission",async()=>{
   const r=await api("/api/pilot/review",{id:j.id});await refresh();showDialog("Pre-submission review",node("p",j.company+" · "+j.title),
   node("p","Automated submission is off. This only prepares materials."),node("pre",r.blockers.map(friendlyError).join("\n")||"Ready for you to confirm the role, answers, and document versions."),
   node("pre","CV "+(r.versions.CV||"Not generated")+"\nCover letter "+(r.versions.CL||"Not generated")));
 }));
 actions.append(button("Generate cover letter only",async()=>{
   showDialog("Generate cover letter",node("p","Matching facts, writing, and independently reviewing the draft. Without a full job description, only a general draft is saved."));
   await api("/api/cl/generate",{id:j.id});await refresh();detail(j.id);
 }));
 if(j.industry.state==="review")actions.append(button("Confirm employer is in a traditional industry",async()=>{
   await api("/api/industry",{id:j.id,decision:"traditional"});await refresh();detail(j.id);
 }));
 const cv=current(j,"CV"),cl=current(j,"CL");
 if(cv&&cl)actions.append(button("Mark materials reviewed and ready for manual submission",async()=>{await api("/api/materials/approve",{id:j.id,CV:cv.id,CL:cl.id});await refresh();detail(id);}));
 if(j.vacancy!=="Closed")actions.append(handoffButton(j));
 const checks=node("ul");for(const[k,v]of Object.entries(j.match?.checks||{}))checks.append(node("li",tx(k)+" · "+tx(v.state)+" · "+(v.jd?.length?"The description mentions this requirement. Review the original text.":"Not stated in the job description")+" · "+(v.reason||"Not yet confirmed")));
 const match=node("ul");for(const part of j.match?.parts||[])for(const e of part.evidence||[])if(e.cv?.length)match.append(node("li",e.keyword+" · "+e.cv.map(f=>f.text).join(" ")));
 const all=node("details");all.append(node("summary","Historical materials and versions ("+j.documents.length+" files)"),...docs(j));
 showDialog(j.title,node("p",j.company+" · "+tx(j.country)+" · "+(j.location||"Location not provided")+" · "+workflowLabel(j.workflow_state)),
 node("p",(j.requisition?"Requisition ID "+j.requisition+" · ":"")+(j.posted?"Page date "+j.posted+" · ":"")+(j.date_evidence||"")),
 node("p","Master résumé "+(j.match?.score??"Not scored")+(j.tailored_fit?" · Tailored CV "+j.tailored_fit.score:"")+" · "+dateLabel(j.date_signal)),actions,
 section("Application materials",materialActions(j),all),
 section("Your confirmed work status",node('p',state.work_profiles?.[j.country]?({Authorized:'Work authorization confirmed','Requires sponsorship':'Requires employer sponsorship; work authorization not confirmed','Not authorized':'Not currently authorized to work'}[state.work_profiles[j.country].state]||'Pending confirmation')+' · '+state.work_profiles[j.country].evidence:'Not confirmed for this country'),node('p','Verify employer sponsorship separately. A high score or finished materials do not establish eligibility.')),
 ...(j.japan_review?[section("Japan listing review",...j.japan_review.map(reason=>node("p",reason.replace(/^JD 明确要求日语：/, "The posting explicitly requires Japanese: "))))]:[]),
 section('Employer sponsorship evidence',node('p',systemLabel(j.sponsorship_evidence?.state)||'Unknown'),node('pre',(j.sponsorship_evidence?.evidence||[]).join('\n'))),section("Application eligibility",checks),
 section("Match evidence",node("p","This score reflects local keyword overlap, not hiring odds. Eligibility is checked separately."),
 ...((j.match?.parts||[]).map(p=>node("p",p.name+" "+p.points+"/"+p.weight+
 (p.diagnostic?" · "+p.diagnostic.formula+" · "+(!p.diagnostic.requested_terms.length?"No matching terms were detected in the job description for this category. A score of zero does not imply ineligibility.":"Terms without supporting evidence: "+(p.diagnostic.unmatched_terms.join(", ")||"None")):p.name==="Seniority"?" · Estimated from the job title only":p.name==="Location and working arrangement"?" · Target market, not proof of work authorization":" · Older scores did not store a category breakdown")))),match),section("Main gaps",node("p",j.match?j.match.gaps?.join(", ")||"No keyword gaps detected. Still verify mandatory requirements.":"Main gaps appear after scoring.")),
 section("Job description",node("pre",j.jd||"Add the full job description.")),
 ...j.events.filter(e=>e.kind==="Import screenshot").map(e=>link("View imported screenshot","/import-evidence/"+e.detail)),
 section("Notes",form([field("Notes","notes",{area:true,value:j.notes})],"Save notes",async data=>{await api("/api/update",{id,...data});await refresh();detail(id);})));
}
function jobCard(j){
 const card=node("article",null,{class:"job-card"});
 card.append(box(button(j.title,()=>detail(j.id),"row-title"),node("span",workflowLabel(j.workflow_state),{class:"tag"})),
 node("p",j.company+" · "+tx(j.country)+" · "+(j.location||"Location not provided")+(j.posted?" · "+j.posted:"")),
 node("p","Master résumé "+(j.match?.score??"Not scored")+" · "+(j.platform_application?"Platform shows applications open":tx(j.vacancy))+" · "+dateLabel(j.date_signal)));
 card.append(materialActions(j),box(button("View job",()=>detail(j.id)),button("Application Tracker",()=>recordView(j)),
 handoffButton(j)));
 return card;
}
function listJobs(rows,target){
 target.replaceChildren();let page=0;
 const controls=box(),items=node("div");
 const paint=()=>{items.replaceChildren(...rows.slice(page*10,page*10+10).map(jobCard));controls.replaceChildren(node("p","Total: "+rows.length+" jobs · Page "+(page+1)+" "),
 button("Previous",()=>{page=Math.max(0,page-1);paint();}),button("Next",()=>{if((page+1)*10<rows.length){page++;paint();}}));};
 if(!rows.length){target.append(empty("No jobs match the current filters."));return;}
 target.append(controls,items);paint();
}
function table(rows,target){listJobs(rows,target);}
function jobsPanel(records=false){
 const toolbar=box(),target=node("div");const search=node("input",null,{type:"search",placeholder:"Search companies or roles",value:query,"aria-label":"Search companies or roles"});
 const market=field("Market","market",{options:["",...state.markets]}),status=field("Status","status",{options:["","\u5f85\u751f\u6210\u6750\u6599","\u5f85\u5ba1\u6838","\u5f85\u6211\u6295\u9012","\u9700\u6211\u5904\u7406","\u63d0\u4ea4\u7ed3\u679c\u5f85\u6838\u5b9e","\u5df2\u6295\u9012","\u9762\u8bd5\u4e2d","\u88ab\u62d2","\u5df2\u5173\u95ed"]});
 for (const option of status.lastElementChild.options) option.textContent=workflowLabel(option.value);
 const tabs=box();let chosen=tag;
 const update=()=>{
   let rows=state.jobs.filter(j=>j.industry.state!=="excluded");
   if(!records){
     const groups={"Candidates 60+":state.candidate_pool,"Today's alternatives":[...state.queues.recent,...state.queues.week,...state.queues.month],"High-match shortlist":state.queues.high,"Best résumé matches":state.queues.resume};
     if(groups[chosen]){const ids=new Set(groups[chosen]);rows=rows.filter(j=>ids.has(j.id));}
     if(chosen==="Verified fresh (72 hours)")rows=rows.filter(j=>j.fresh_discovery);
     if(chosen==="Date unverified")rows=rows.filter(j=>!j.original_posted_at&&j.vacancy!=="Closed");
   }else rows=rows.filter(j=>j.application_record||j.events.some(e=>/Applied|Submitted|Pilot review|Official application opened|Materials approved/.test(e.kind))||["\u5f85\u5ba1\u6838","\u5f85\u6211\u6295\u9012","\u9700\u6211\u5904\u7406","\u63d0\u4ea4\u7ed3\u679c\u5f85\u6838\u5b9e"].includes(j.workflow_state));
   const m=market.lastElementChild.value,st=status.lastElementChild.value;
   rows=rows.filter(j=>(!m||j.country===m)&&(!st||j.workflow_state===st)&&(j.company+" "+j.title).toLowerCase().includes(search.value.toLowerCase()));
   rows.sort((a,b)=>(b.match?.score||0)-(a.match?.score||0));listJobs(rows,target);
 };
 if(!records)for(const name of ["Candidates 60+","Today's alternatives","High-match shortlist","Best résumé matches","Verified fresh (72 hours)","Date unverified","All jobs"])tabs.append(button(name,()=>{tag=chosen=name;for(const b of tabs.children)b.classList.toggle("selected",b.textContent===name);update();},name===chosen?"selected":""));
 toolbar.append(search,market,status,button("Paste job description",()=>pasteJD()),button("Score in bulk",async()=>{const r=await api("/api/match/batch",{});await refresh();notice("Scored "+r.scored+" jobs.");}));
 search.addEventListener("input",()=>{query=search.value;update();});market.addEventListener("change",update);status.addEventListener("change",update);
 content.append(tabs,toolbar,target);update();
}
let selectedApplicationDate="";
function applicationDay(){
 const date=field("Application date (UTC)","application-date",{type:"date",value:selectedApplicationDate||state.today});
 const input=date.lastElementChild, summary=box(), heading=node("h2","Today's applications");
 const load=async()=>{
   if(!input.value)return;
   const requested=input.value;
   selectedApplicationDate=requested;
   heading.textContent=requested===state.today?"Today's applications":requested+" application statistics";
   summary.replaceChildren(node("p","Loading…"));
   try{
     const groups=await api("/api/application-day?date="+encodeURIComponent(requested));
     if(input.value!==requested)return;
     const labels={automatic:"Automated submission confirmed",manual:"Manual submission confirmed",pending:"Pending confirmation",blocked:"Failed or blocked"};
     summary.replaceChildren(...Object.entries(labels).map(([key,label])=>button(label+" "+groups[key].length,()=>{
       showDialog(label+" · "+requested,...(groups[key].length?groups[key].map(r=>section(r.company+" · "+r.title,
         node("p",tx(r.country)+" · "+tx(r.channel)+" · "+r.time),
         node("p","CV "+(r.cv||"—")+" · Cover letter "+(r.cl||"—")),
         node("p",r.receipt?"Evidence · "+r.receipt:r.detail||"Not provided"),
         button("View job",()=>detail(r.job)))):[node("p","No records of this type on that day.")]));
     })));
   }catch(error){if(input.value===requested)summary.replaceChildren(node("p",friendlyError(error.message)));}
 };
 input.addEventListener("change",load);
 load();
 return section("By UTC date",heading,date,summary);
}
function dashboard(){
 const h=state.discovery_health||{}, q=state.cv_queue||{counts:{}}, receipts=state.receipt_summary||{};
 const healthLabel={done:"Completed today",failed:"Today's run failed",missing:"No run today",scheduled:"Waiting for scheduled time",running:"Discovering jobs"}[h.state]||"Unknown status";
 const eligible=state.jobs.filter(j=>!j.retention_blocker&&j.industry.state==="allowed"&&j.vacancy!=="Closed"&&!["Manually Applied","Submitted","Submission Confirmation Unknown","Rejected","Withdrawn","Not Interested","Duplicate"].includes(j.status)&&
   (j.match?.score||0)>=state.settings.high&&!Object.values(j.match?.checks||{}).some(c=>c.state==="Failed")&&!j.sponsorship_evidence?.excluded);
 const priorities=state.settings.priority_locations||[];
 const priority=j=>priorities.some(x=>(j.location||"").toLowerCase().includes(x.toLowerCase()))?1:0;
 eligible.sort((a,b)=>(b.match?.score||0)-(a.match?.score||0)||priority(b)-priority(a));
 content.append(node("p","Shortlist promising jobs, then verify eligibility and materials. You submit all applications yourself.",{class:"muted"}),
 metrics({"High matches to review":eligible.length,"CVs to prepare":q.counts.preview||0,"Receipts today":(receipts.manual||0)+(receipts.automatic||0),"Unknown submissions":state.jobs.filter(j=>j.status==="Submission Confirmation Unknown").length}));
 const health=section("Today's discovery",box(node("strong",healthLabel,{class:"tag "+(h.state==="failed"||h.stale?"warning":"")}),
 node("span",h.timezone+" · "+state.settings.schedule+" · "+(h.stale?"Results stale or no successful run":"Recent results available"))),
 node("p","Last successful run: "+(h.last_success||"None")+" · Next scheduled run: "+state.next_run),
 node("p","Keep the computer awake and the files readable. A successful run does not establish eligibility or mean application targets were met.",{class:"muted"}));
 const problems=Object.entries(state.dependency_health||{}).filter(([k,v])=>!v.readable);
 if(problems.length)health.append(node("p","Material dependencies not readable: "+problems.map(([k,v])=>k+" / "+v.reason).join(", "),{class:"notice-line"}));
 if(state.scheduler_health?.error)health.append(node("p","Scheduler check: "+state.scheduler_health.error,{class:"notice-line"}));
 content.append(health);
 const shortlist=section("High-match jobs to review first",node("p","Scores measure CV keyword overlap. Location only breaks ties. Verify work authorization, language, and sponsorship separately.",{class:"muted"}));
 for(const j of eligible.slice(0,8)){
   const row=node("article",null,{class:"compact-job"});
   const cv=j.current_documents?.CV;
   row.append(box(button(j.company+" · "+j.title,()=>detail(j.id),"row-title"),node("strong",String(j.match.score),{class:"score"})),
     node("p",tx(j.country)+" · "+j.location+" · "+(j.fresh_discovery?"Verified recent original posting":j.original_posted_at?"Original date recorded":"Original publication date unknown")),
     node("p",(cv&&!j.materials_stale?"Current CV available":"CVs to prepare")+" · "+(j.application_blockers?.length?"Eligibility checks outstanding: "+j.application_blockers.length+" ":"Eligibility checks satisfied")),
     box(button("Evidence and blockers",()=>detail(j.id)),button("Materials and versions",()=>detail(j.id))));
   shortlist.append(row);
 }
 if(!eligible.length)shortlist.append(empty("No jobs meet the review threshold. Check discovery status, market settings, or full job descriptions. The threshold will not lower automatically."));
 shortlist.append(button("View all jobs",()=>navigate("Candidate Pool")));
 content.append(shortlist);
 const queue=section("CV preparation queue",node("p",q.worker?.enabled?"Automatic CV generation is enabled. Daily limit: "+q.daily_limit+" attempts. CVs only; cover letters are on demand. Review materials manually.":"Model disabled. The queue plans only; it neither sends personal information nor calls a paid model. Verify the account, destination, data permissions, and cost before enabling it."),
 box(node("span","Planned "+(q.counts.preview||0)+" · In progress "+(q.counts.generating||0)+" · Ready "+(q.counts.ready||0)+" · Failed "+(q.counts.failed||0)+" · Blocked "+(q.counts.blocked||0)),
 button("Check queue",async()=>{await api("/api/cv-queue/reconcile",{});await refresh();})));
 queue.append(node("p","Today\u0027s attempts: "+(q.used_today||0)+" / "+q.daily_limit+". Failures and explicit retries count toward the limit.",{class:"muted"}));
 const queueList=node("details"); queueList.append(node("summary","View queue reasons and version status"));
 for(const item of (q.rows||[]).slice(0,15)){
   const j=state.jobs.find(j=>j.id===item.job);
   const itemBox=box(button(j?j.company+" · "+j.title:"Job",()=>detail(item.job)),node("span",item.state+" · "+item.reason));
   if(item.state==="failed"&&item.attempts<3)itemBox.append(button("Retry this item",async()=>{await api("/api/cv-queue/retry",{key:item.key,confirmed:true});await refresh();}));
   queueList.append(itemBox);
 }
 queue.append(queueList);content.append(queue);
 const history=node("details");history.append(node("summary","Run history and source health"),
 node("p","Missing dates: "+(state.cadence?.missing_dates?.join(", ")||"None")+" · Failed dates: "+(state.cadence?.failed_dates?.join(", ")||"None")));
 for(const r of state.runs.slice(0,10)){
   const d=node("details"),v=r.result;d.append(node("summary",r.created+" · "+r.kind+" · "+(v.running?"Incomplete":v.errors?.length?"Failed or partial":"No errors")),
   node("p","New "+(v.added||0)+" · Duplicate inputs "+(v.duplicates||0)+" · Unique jobs "+(v.discovery?.["Unique jobs discovered"]??"Statistics incomplete")),
   node("pre",(v.errors||[]).join("\n")||"No errors recorded"));
   history.append(d);
 }
 history.append(node("pre",Object.entries(state.source_health||{}).map(([k,v])=>k+" · "+v.state+" · Raw "+(v.retrieved??"—")+" / Filtered "+(v.targeted??"—")).join("\n")));
 content.append(history,section("Manual submissions and receipts",node("p","Verified receipts today "+((receipts.manual||0)+(receipts.automatic||0))+" · Awaiting confirmation today "+(receipts.pending||0)+" · Blocked today "+(receipts.blocked||0)),
 box(button("Application and receipt history",()=>navigate("Application Tracker")),button("Assisted Apply",()=>navigate("Assisted Apply")))));
}

function settings(){
 const advanced=node('details');advanced.append(node('summary','Advanced: supplementary employer feeds'),node('p','These supplementary sources do not cover the entire Canadian job market. Manual entry is optional.'),node('pre','Greenhouse: '+state.settings.boards+'\nLever: '+state.settings.lever_boards));content.append(advanced);
 const s=state.settings;content.append(section("Run settings",node("p","Assisted application mode: "+(s.assisted_apply_mode||"Dry Run")+". Change the mode and review application information in Assisted Apply."),
 node("p",`Candidate cutoff: ${state.settings.saved} points · High match: ${state.settings.high} points · Original posting window: ${state.settings.fresh_hours} hours · You confirm every submission`),
 form([field("Daily discovery time","schedule",{type:"time",value:s.schedule}),
 field("Discovery time zone (IANA)","timezone",{value:s.timezone,required:true}),
 field("Enabled countries (comma-separated)","enabled_countries",{value:s.enabled_countries.join(", "),required:true}),
 field("Preferred locations (tie-breaker)","priority_locations",{value:s.priority_locations.join(", ")}),
 field("Original publication recency (hours)","fresh_hours",{type:"number",value:s.fresh_hours}),
 field("Minimum candidate score","saved",{type:"number",value:s.saved}),
 field("Review threshold","pending",{type:"number",value:s.pending}),
 field("High-match threshold","high",{type:"number",value:s.high}),
 field("Minimum score to queue a CV","cv_queue_threshold",{type:"number",value:s.cv_queue_threshold}),
 field("Daily CV attempt cap (no model calls in preview)","cv_queue_daily_limit",{type:"number",value:s.cv_queue_daily_limit})],"Save settings",async x=>{await api("/api/settings",{...s,...x});await refresh();notice("Settings saved.");})),
 section("Application profile",node("p","Save only answers you have verified. Check work authorization by country. Missing answers pause application preparation."),
 form([field("Country","country",{options:state.markets}),field("Full name in English","name"),field("Email","email",{type:"email"}),field("Phone","phone"),
 field("Current work authorization","work_authorization"),field("Whether you require employer sponsorship","sponsorship"),field("Salary answer (optional)","salary"),field("Other confirmed answers","other",{area:true}),
 field("I confirm this information is accurate","confirmed",{type:"checkbox"})],"Save confirmed information",async x=>{
   if(x.confirmed!=="on")throw Error("Confirm that the information is accurate first.");
   const answers=Object.fromEntries(["name","email","phone","work_authorization","sponsorship","salary","other"].map(k=>[k,x[k]]));
   await api("/api/application-profile",{country:x.country,answers,confirmed:true});await refresh();notice("Confirmed information saved.");
 })),
 section("Master résumé and materials",link("Master résumé PDF","/main.pdf"),node("p","The CV layout comes from main.docx. Newly generated materials record the template fingerprint, generation time, version, and source.")),
 section("Backup",button("Create database backup",async()=>{await api("/api/backup",{});notice("Backup created.");})));
}
function navigate(next){view=next;history.replaceState(null,"",location.pathname+(next==="My Imports"?"#imports":next==="Application Tracker"?"#applications":next==="Assisted Apply"?"#assisted":""));render();}
function render(){
 document.querySelector(".local").textContent="Local job workspace · "+systemLabel(state.environment);
 content.replaceChildren();content.setAttribute("aria-busy","false");$("title").textContent=labels[view];
 for(const b of document.querySelectorAll("nav button"))b.toggleAttribute("aria-current",b.dataset.view===view);
 if(view==="Dashboard")dashboard();
 else if(view==="Job Discovery"){content.append(coverageView(),node('p','Configure Canada, the United States, Japan, the UAE, and the United Kingdom. Automatic discovery reads only connected public ATS feeds. Search links and manual imports supplement LinkedIn, Indeed, and other employer sites; this is not full-market coverage. Fresh Discovery requires a verifiable original posting date within the configured window and deduplicates against history.'),publicSearch(),box(button("Discover from public employer feeds",async()=>{const r=await api("/api/run",{active_only:true});await refresh();notice("Added "+r.added+" jobs.");}),button("Find jobs using the master résumé",async()=>{const r=await api("/api/resume/discover",{});await refresh();notice("Added "+r.added+" jobs.");}))); }
 else if(view==="Candidate Pool")jobsPanel();
 else if(view==="My Imports")myImports();
 else if(view==="Assisted Apply"){const pane=node("div","Loading application queue…");content.append(pane);assistedPanel(pane).catch(e=>pane.replaceChildren(node("p",e.message)));}
 else if(view==="Application Tracker"){content.append(applicationDay());jobsPanel(true);}
 else settings();
}
function showImportPreview(preview, back) {
  const rows=node("div"), selected=new Set();
  const confirm=button("Import selected listings",async()=>{
    const result=await api("/api/import/confirm",{id:preview.id,selected:[...selected]});
    dialog.close();view="My Imports";history.replaceState(null,"","#imports");await refresh();
    showImportResults(result.results);
  },"primary");
  confirm.disabled=true;
  const choices=[];
  const selectAll=button("Select all importable listings",()=>{
    for(const choose of choices) {
      choose.checked=true;
      choose.dispatchEvent(new Event("change"));
    }
  });
  for(const job of preview.jobs) {
    const choose=node("input",null,{type:"checkbox","aria-label":"Select "+job.title});
    choose.disabled=!job.selectable;
    if(job.selectable)choices.push(choose);
    choose.addEventListener("change",()=>{
      if(choose.checked)selected.add(job.index);else selected.delete(job.index);
      confirm.disabled=!selected.size;
    });
    const summary=node("label");
    summary.append(choose,document.createTextNode(job.title+" · "+job.company+" · "+job.source+
      " · "+({"Manual review":"Needs review","Already tracked":"Already tracked","Possible duplicate":"Possible duplicates","Excluded industry":"Excluded by industry","Employer closed":"Closed by employer","Historical listing":"Historical listing","Attach source to existing job":"Attach to existing job"}[job.status]||job.status)+" · "+(job.active?"Verified open":job.platform_open?"Platform shows applications open":job.status==="Employer closed"?"Closed":"Vacancy status unverified")+
      " · Posted "+(job.posted||"Unverified")+" · Score "+(job.score??"Not scored")));
    const links=box(link("Source listing",job.url));
    if(job.employer_url)links.append(link("Verified employer listing",job.employer_url));
    for(const url of job.possible_employer_urls||[])links.append(link("Possible employer listing",url));
    const fit=fitLabel(job.score,!job.blockers?.length);
    rows.append(section(job.title,summary,node("p",[job.shortlisted?"Shortlisted":"",job.location,fit,job.date_evidence].filter(Boolean).join(" · ")),links,
      job.platform_date_label?node("p",job.platform_date_label+" · "+job.platform_date_evidence):node("span"),
      job.fit_points?.length?node("p",job.fit_points.map(part=>part.name+" "+part.points+"/"+part.weight).join(" · ")):node("span"),
      job.fit_evidence?.length?node("p","Résumé match evidence: "+job.fit_evidence.join(", ")):node("span"),
      job.fit_gaps?.length?node("p","Missing evidence: "+job.fit_gaps.join(", ")):node("span"),
      job.coverage_notes?.length?node("p",job.coverage_notes.join(" · ")):node("span"),
      job.blockers?.length?node("p",job.blockers.join(" ")):node("span")));
  }
  const sample=preview.manual_sample;
  const sampleSection=sample?section(sample.platform+" manual search sample",metrics({
    "Raw rows supplied":sample.raw_rows,"Unique vacancies":sample.unique_jobs,"Already in Tracker":sample.already_tracked,
    "Complete JDs supplied":sample.complete_jds,"New 60+ in sample":sample.new_fit_60,"Verified originals within 72 hours":sample.verified_originals_72h,
    "Meet filters and eligibility":sample.qualified,"Other platform or invalid rows":sample.out_of_scope_or_invalid}),
    node("p",sample.has_20_complete_jds?"Sample contains at least 20 unique complete JDs.":"Sample has fewer than 20 unique complete JDs."),
    node("p","The 20 confirmed submissions per platform per day setting is a separate limit.")):node("span");
  const failures=Object.values(preview.source_health||{}).filter(source=>source.state==="Failed").length;
  showDialog("Controlled import preview",sampleSection,metrics(preview.counts),
    node("p","Work authorization requires manual evidence. Select only listings you want to import for review."),
    node("p",failures?failures+" employer feeds unavailable. Their listings remain unverified.":""),
    ...Object.entries(preview.markets||{}).map(([country,market])=>
      node("p",country+" · "+market.discovered+" discovered · "+market.shortlisted+" shortlisted of "+market.target+
        " target · "+market.dated+" original dates · "+market.high_fit+" high fit · "+market.blocked+" blocked")),
    choices.length?selectAll:node("span"),rows,back?button("Back to edit listings",back):node("span"),preview.id?confirm:empty("No vacancies extracted."));
}


function bulkImport(initialJob) {
  const links=node("textarea",null,{"aria-label":"Paste job URLs",placeholder:"Paste LinkedIn or Indeed job links, one per line"});
  const exportText=field("Paste JSON export","export",{area:true});
  const file=node("input",null,{type:"file",accept:".csv,.json","aria-label":"Select a CSV or JSON export"});
  const rows=node("div");
  const sample=field("Manual search sample (optional)","sample",{options:["","LinkedIn","Indeed"]});
  const editors=[];
  function add(initial) {
    if(!initial||typeof initial!=="object"||Array.isArray(initial))throw Error("Each export row must be a listing object.");
    const fields=node("div",null,{class:"form-grid"}), inputs={};
    for(const [label,name,options] of [
      ["Listing URL","url",{}],["Job title","title",{}],["Employer","company",{}],["Location","location",{}],
      ["Official employer URL","apply_url",{}],["Observed application route","platform_apply",{options:["","On platform","External"]}],["Employer closure evidence URL","closure_url",{}],["Requisition ID","requisition",{}],
      ["Date as shown","platform_date_evidence",{}],["Date type","platform_date_kind",{options:["","Displayed","Reposted","Last published"]}],
      ["Verified industry","industry_declared",{options:["","traditional","web3"]}],
      ["JD completeness","jd_quality",{options:["Partial","Full"]}],["Permitted job description","jd",{area:true}]
    ]) {
      const wrap=field(label,name,{...options,value:initial[name]});
      inputs[name]=wrap.lastElementChild;fields.append(wrap);
    }
    const card=section("Listing",fields);
    editors.push({card,initial,inputs});
    card.append(button("Remove listing",()=>card.remove()));
    rows.append(card);
  }
  function addLinks() {
    const pasted=links.value.match(/\[[^\]\n]+\]\(https:\/\/[^\s)]+\)|https?:\/\/[^\s]+/g)||[];
    for(const url of pasted)add({url});
    links.value="";
  }
  const showEditor=()=>showDialog("Import Jobs",node("p","Paste job links or select a CSV file. Add the job description and original date details before previewing."),
    sample,links,button("Add pasted URLs",addLinks),exportText,button("Load pasted export",async()=>{
      const input=exportText.lastElementChild;
      const result=await api("/api/import/read-export",{format:"json",content:input.value});
      for(const entry of result.jobs)add(entry);
      input.value="";
    }),file,button("Load export",async()=>{
      const chosen=file.files[0];
      if(!chosen)throw Error("Choose a CSV or JSON file.");
      if(chosen.size>400000)throw Error("Split this export into files smaller than 400 KB.");
      const result=await api("/api/import/read-export",{format:chosen.name.toLowerCase().endsWith(".csv")?"csv":"json",
                                                       content:await chosen.text()});
      for(const entry of result.jobs)add(entry);
      file.value="";
    }),button("Add a listing",()=>add({})),rows,
    button("Preview and score",async()=>{
      addLinks();
      const jobs=editors.filter(entry=>entry.card.isConnected).map(({initial,inputs})=>
        ({...initial,...Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,input.value]))}));
      showImportPreview(await api("/api/import/preview",{jobs,sample_platform:sample.lastElementChild.value||null}),showEditor);
    },"primary"),button("Open single-job form",importJob));
  if(initialJob) add({url:initialJob.url,title:initialJob.title,company:initialJob.company,location:initialJob.location,requisition:initialJob.requisition||""});
  showEditor();
}

function importJob(initialUrl="",existing=null) {
  const screenshot=node("input",null,{type:"file",accept:"image/png,image/jpeg","aria-label":"Optional listing screenshot"});
  const editor=form([
    field("Job title","title",{required:true,value:existing?.title}),field("Company","company",{required:true,value:existing?.company}),
    field("Location","location",{value:existing?.location}),field("Market","country",{options:["Unverified",...state.markets,"Other"],value:existing?.country}),
    field("Source","source",{options:[...new Set([existing?.source||"Manual","Manual","LinkedIn","Indeed","Company career page","Authorized feed","Authorized alert"])],value:existing?.source}),
    field("Primary industry (if verified)","industry_declared",{options:["","traditional","web3"]}),
    field("Original URL","url",{type:"url",value:initialUrl}),field("Application URL","apply_url",{type:"url",value:existing?.apply_url}),
    field("Verified original posting date","posted",{type:"date"}),
    field("Verified original timestamp (ISO with timezone)","original_posted_at"),
    field("Original date evidence","posting_date_evidence"),
    field("Platform date type","platform_date_kind",{options:["","Displayed","Reposted","Last published"]}),
    field("Platform date as displayed","platform_date_evidence"),field("Source job ID","external_id"),field("Employer requisition","requisition",{value:existing?.requisition}),
    field("Work arrangement","arrangement"),field("Salary","salary"),
    field("Vacancy","vacancy",{options:["Unverified","Active","Closed"],value:existing?.vacancy}),field("JD completeness","jd_quality",{options:["Partial","Full"],value:existing?.jd&&!existing.jd.startsWith("[Partial JD]")?"Full":"Partial"}),
    field("Job description","jd",{area:true,value:existing?.jd?.replace(/^\[Partial JD\]\n/,"")})
  ],"Save job",async data=>{
    const file=screenshot.files[0];
    if(file&&file.size>350000)throw Error("Choose a screenshot of 350 KB or less.");
    let result=await api("/api/import",{...data,edit_id:existing?.id});
    if(result.result==="review") {
      const names=state.jobs.filter(j=>result.ids.includes(j.id)).map(j=>j.company+" — "+j.title).join("\n");
      if(!confirm("Possible duplicates:\n"+names+"\n\nSave this as a separate listing?")) return;
      result=await api("/api/import",{...data,allow_similar:true});
    }
    if(result.result==="conflict") throw Error("Multiple existing records match the identifiers. Nothing was merged.");
    if(result.id&&file&&["added","duplicate","enriched","linked"].includes(result.result)){
      const bytes=new Uint8Array(await file.arrayBuffer());let binary="";
      for(const byte of bytes)binary+=String.fromCharCode(byte);
      try{await api("/api/import/screenshot",{id:result.id,image:btoa(binary)});}
      catch(error){result.analysis_error="Job saved, screenshot not saved: "+error.message;}
    }
    view="My Imports";history.replaceState(null,"","#imports");await refresh();showImportResults([result]);
  });
  const picture=node("label","Optional job screenshot (PNG/JPEG, up to 350 KB)");picture.append(screenshot);
  editor.insertBefore(picture,editor.lastElementChild);
  showDialog("Manual entry / advanced editing",node("p","Screenshots are saved with the job for verification. Choose Needs details if the job description is incomplete."),editor);
}

function pasteJD(job) {
  const common=field("Full job description","jd",{area:true,required:true,value:job?.jd?.startsWith("[Partial JD]")?"":job?.jd});
  const fields=job?[common]:[field("Job title","title",{required:true}),field("Employer","company",{required:true}),
    field("Location","location"),field("Country","country",{options:["Unverified",...state.markets,"Other"]}),
    field("Listing URL","url",{type:"url"}),field("Employer requisition ID","requisition"),
    field("Verified industry","industry_declared",{options:["","traditional"]}),common];
  async function save(data) {
    const result=await api("/api/manual/jd",{...data,complete:true});
    if(result.result==="excluded")throw Error(result.industry.reason);
    if(result.result==="conflict")throw Error("Multiple exact records match. Open the correct job and paste the JD there.");
    if(result.result==="duplicate"||result.result==="review") {
      const ids=result.ids||[result.id];
      const choices=state.jobs.filter(existing=>ids.includes(existing.id)).map(existing=>
        button("Update existing job · "+existing.title+" · "+existing.company,()=>save({...data,id:existing.id})));
      if(result.result==="review")choices.push(button("Save as a separate job",()=>save({...data,allow_similar:true})));
      showDialog("Review existing jobs",...choices);
      return;
    }
    if(!job)view="My Imports";
    await refresh();detail(result.id);
  }
  showDialog(job?"Add job description · "+job.title:"Paste job description",
    node("p","Save the complete description. Eligibility will remain separate from material preparation."),
    form(fields,"Confirm complete JD and save",data=>save({...data,id:job?.id})));
}

function publicSearch() {
  const family=field("Career area","family",{options:state.career_families});
  const market=field("Market","market",{options:["Canada","Vancouver","Greater Toronto Area","United States","UAE","Dubai","Abu Dhabi","Remote Canada","Remote UAE","Japan","Tokyo","Yokohama","UK"]});
  const channels={"LinkedIn public index":"site:linkedin.com/jobs/view","Indeed":"site:indeed.com/viewjob",
    "Industry job boards":"(site:jobbank.gc.ca OR site:gulftalent.com OR site:bayt.com)",
    "Recruitment agencies":"(site:roberthalf.com OR site:michaelpage.ae OR site:hays.ca)"};
  const links=box();
  const update=()=>{
    links.replaceChildren(...Object.entries(channels).map(([label,site])=>link(label,"https://www.google.com/search?q="+encodeURIComponent(family.lastElementChild.value+" "+market.lastElementChild.value+" "+site))));
    if(["Canada","Vancouver","Greater Toronto Area","Remote Canada"].includes(market.lastElementChild.value))links.append(link('Job Bank: official Canada-wide search (manual import)','https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring='+encodeURIComponent(family.lastElementChild.value)));
  };
  const presets=box();
  const updatePresets=()=>{
    const geo={"Canada":"101174742","Vancouver":"101226900","Greater Toronto Area":"100025096","UAE":"104305776",
      "Dubai":"106204383","Abu Dhabi":"104306859","Remote Canada":"101174742","Remote UAE":"104305776"};
    presets.replaceChildren(...[[86400,"Past 24 hours"],[604800,"Past week"],[2592000,"Past month"]].map(([seconds,label])=>{
      const region=market.lastElementChild.value;
      const query=new URLSearchParams({keywords:family.lastElementChild.value,f_TPR:"r"+seconds});
      query.set(geo[region]?"geoId":"location",geo[region]||region);
      if(region.startsWith("Remote")) query.set("f_WT","2");
      return link("LinkedIn · "+label,"https://www.linkedin.com/jobs/search/?"+query);
    }));
  };
  for(const field of [family,market]) field.addEventListener("change",()=>{update();updatePresets();});
  update();updatePresets();
  return section("Search public results by career area and market",box(family,market),presets,links,node("p","Search the last 24 hours first, then fill any gaps from the last week. Paste links or descriptions into Import Jobs to deduplicate by job ID."));
}

function observeListing(job) {
  const urls=job.source_links.map(link=>link.url).filter(Boolean);
  return urls.length?button("Record page access and date evidence",()=>showDialog("Record a page observation",
    form([field("Source link","url",{options:[...new Set(urls)]}),
      field("Access result","state",{options:["Login required","Redirected","Summary only","Explicitly closed","Request failed","Unknown","Readable"]}),
      field("Page message, redirect URL, or other observed evidence","detail",{area:true,required:true}),
      field("Original platform date label","label"),field("Time observed (leave blank to use now)","viewed",{type:"datetime-local"}),field("Date type","kind",{options:["Displayed","Reposted"]})],
      "Save",async data=>{await api("/api/listing/observe",{id:job.id,...data,viewed:data.viewed?new Date(data.viewed).toISOString():""});await refresh();detail(job.id);}))):node("span");
}
document.querySelector("nav").addEventListener("click",e=>{if(state&&e.target.dataset.view)navigate(e.target.dataset.view);});
$("close").addEventListener("click",()=>dialog.close());
$("import").addEventListener("click",()=>{if(state)linkImport();});
action(async()=>{await refresh();const id=new URLSearchParams(location.hash.slice(1)).get("job");if(id)detail(id);});

async function letterView(job,doc){
 const data=await api('/api/material/'+doc.id),review=data.metadata?.cl_review||{};
 const copyState=node('p','',{role:'status'});
 const body=field('Cover letter text','body',{area:true,value:data.body||data.text});
 const zh=node('details');zh.append(node('summary','Optional Chinese translation (not included in the application document)'),node('pre',(review.translation_zh||[]).join('\n\n')||'This version has no reviewed Chinese translation.'));
 const proof=node('ul');for(const req of review.requirements||[])proof.append(node('li',
  ({Core:'Core',Preferred:'Preferred'}[req.priority]||req.priority)+' · '+req.requirement+' · '+
  ({Direct:'Direct experience',Transferable:'Transferable experience','No evidence':'No evidence'}[req.evidence_type]||req.evidence_type)+' · '+req.explanation+' · '+req.refs.join(', ')));
 const checks=node('details');checks.append(node('summary','Review record (requires your review)'),node('pre',Object.entries(review.checks||{}).map(([k,v])=>({opening_match:'Opening alignment',specific_evidence:'Specific experience evidence',scope_tools_numbers:'Responsibilities, regions, tools, and metrics',transferable_not_direct:'Direct versus transferable experience',distinct_examples:'Two distinct examples',no_flattery_or_company_guesses:'Flattery and unsupported company claims',defensible_claims:'Defensible facts',length_and_page:'Word count and page length'}[k]||k)+' · '+(v.passed?'Checked':'Needs attention')+' · '+v.note).join('\n')||'Not reviewed under the current rules'));
 showDialog('Cover letter · '+doc.id.slice(0,8),node('p',systemLabel(review.status)||'Historical version · unverified'),
 node('p','Generated '+doc.created+' · Résumé '+(review.resume_sha256||doc.source_hash)+' · Linked CV '+(data.metadata?.paired_cv||'No specific CV linked')),
 form([body],'Save a new version (keep the original)',async values=>{await api('/api/manual/edit',{id:doc.id,text:values.body});await refresh();detail(job.id);}),
 button('Review and revise this version (keep the original)',async()=>{
  showDialog('Review cover letter',node('p','Checking verified facts and revising. A new version will be saved when ready.'));
  await api('/api/cl/review',{id:doc.id});await refresh();detail(job.id);
 }),
 button('Copy application text',async()=>{
  const area=body.querySelector('textarea');area.focus();area.select();
  if(!document.execCommand('copy'))await navigator.clipboard.writeText(area.value);
  copyState.textContent='Copied the application text without translation or review notes.';
 }),copyState,
 link('Preview PDF','/pdf/'+doc.id),link('Download PDF','/pdf/'+doc.id+'?download=1',true),zh,
 section('Match evidence',proof),section('Evidence gaps affecting the draft',node('pre',(review.writing_gaps||[]).map(systemLabel).join('\n')||'None listed. Your review is still required.')),section('Job requirements to verify',node('pre',(review.unverified||[]).map(systemLabel).join('\n')||(review.policy?'No critical drafting gaps identified. Verify application eligibility separately.':'This older version has not been reviewed under the current evidence policy.'))),checks);
}

setInterval(async()=>{
 if(!state||busy)return;
 const running=state.jobs.filter(j=>j.generation?.state==='running');if(!running.length)return;
 const title=$('dialog-title').textContent;
 try{await refresh();const j=running.find(j=>j.title===title||title==='Generate materials');if(j&&dialog.open)detail(j.id);}catch(e){notice('Background task status is unavailable. Refresh before attempting another generation.');}
},2500);

function coverageView(){
 const d=node('details');d.append(node('summary','Source coverage and limitations'));
 for(const platform of ['Greenhouse','Lever','Ashby']){
  const rows=Object.entries(state.source_health||{}).filter(([name])=>name.startsWith(platform+':'));
  d.append(node('p',platform+' · Employer feeds '+rows.length+' · Retrieved last run '+rows.filter(([,r])=>r.state==='Retrieved').length+' · Raw jobs '+rows.reduce((sum,[,r])=>sum+(r.retrieved||0),0)),node('small',rows.map(([name,r])=>name+': '+r.state).join('; ')));
 }
 d.append(node('p','Raw job totals cover full feeds, including other regions and older roles. They are not counts of new Canadian or 72-hour jobs.'),node('p','LinkedIn and Indeed support search and manual import, not unattended site-wide scanning. Other employer sites require a connected public feed or manual import. Canada-wide refers to geography, not coverage of every job.'),node('p',`Schedule: ${state.settings.schedule} ${state.settings.timezone}. The service checks every 30 seconds. It may not run while asleep, powered off, or signed out. Catch-up runs are limited and cannot reconstruct historical market snapshots.`));
 return d;
}

function myImports(){
 const latest=(a,b)=>(b.manual_import||b.first_seen).localeCompare(a.manual_import||a.first_seen);
 const manual=state.jobs.filter(job=>job.manual_import).sort(latest);
 const historical=state.jobs.filter(job=>job.legacy_import).sort(latest);
 const list=node("div");listJobs(manual,list);
 const old=node("details"),oldList=node("div");
 old.append(node("summary","Historical manual or platform sources · "+historical.length+" jobs"),node("p","Older records may not have a consistent import label. Manual, LinkedIn, and Indeed jobs remain here for reference."),oldList);
 listJobs(historical,oldList);
 content.append(box(button("Import Jobs",()=>linkImport(),"primary"),button("View all jobs",()=>{tag="All jobs";query="";navigate("Candidate Pool");})),list,old);
}

function importResultRow(result,url=""){
 const row=node("div");
 const job=state.jobs.find(j=>j.id===result.id);
 const saved=["added","duplicate","enriched","linked","saved"].includes(result.result);
 const names={duplicate:"Already recorded · saved in Imported Jobs",added:"Saved in Imported Jobs",enriched:"Completed and saved in Imported Jobs",linked:"Linked in Imported Jobs",saved:"Saved in Imported Jobs",
   unreadable:"Read failed; link retained",review:"Similar job found; review required",conflict:"The requisition or link matches multiple tracked jobs. Review the matches.",excluded:"Excluded by the current industry policy",rejected:"Not saved",changed:"The record changed. Reload and try again."};
 row.append(node("p",(names[result.result]||"Not saved")+(job?" · "+job.title+" · "+job.company:"")));
 if(url)row.append(node("small",url));
 if(result.reason||result.industry?.reason&&!saved)row.append(node("p",result.reason||result.industry.reason));
 if(result.analysis_error)row.append(node("p",result.analysis_error));
 if(saved&&job?.industry.state==="review")row.append(node("p","Industry unverified. The score reflects résumé fit only. Verify industry before generating materials."));
 if(saved&&job)row.append(node("p",job.match?.score!=null?"Master résumé "+job.match.score+" points · "+dateLabel(job.date_signal):
   result.analysis_error||(!result.complete_jd?"More job description needed before scoring":"Not scored. Verify the industry or job details.")));
 const actions=box();
 for(const id of result.ids||(result.id?[result.id]:[]))actions.append(button("View job",()=>detail(id)));
 if(url&&(!saved||!result.complete_jd))actions.append(button("Manual entry / advanced editing",()=>importJob(url,job)));
 if(actions.childElementCount)row.append(actions);
 return row;
}

function showImportResults(results){
 showDialog("Import results",...results.map(r=>importResultRow(r)),button("View My Imports",()=>{dialog.close();navigate("My Imports");}));
}

function linkImport(){
 const input=field("Job links (one per line)","urls",{area:true,value:localStorage.getItem("tracker-import-links")||""});
 const progress=node("p","",{role:"status"});
 const results=node("div"),advanced=node("details");
 advanced.append(node("summary","Manual entry / advanced editing"),button("Enter a job manually",()=>importJob(input.lastElementChild.value.trim().split(/\s+/)[0])),
   button("CSV / JSON or bulk entry",()=>bulkImport()));
 input.lastElementChild.addEventListener("input",()=>localStorage.setItem("tracker-import-links",input.lastElementChild.value));
 const editor=form([input],"Read and import",async data=>{
   const urls=[...new Set(data.urls.split(/\r?\n/).map(x=>x.trim()).filter(Boolean))];
   if(!urls.length||urls.length>20)throw Error("Paste between 1 and 20 links per batch.");
   localStorage.setItem("tracker-import-links",data.urls);
   results.replaceChildren();
   const failures=[];
   for(const [index,url] of urls.entries()){
     progress.textContent="Reading "+(index+1)+" / "+urls.length;
     let result;
     try{result=await api("/api/import/link",{url});}
     catch(error){result={result:"unreadable",reason:error.message};}
     if(["added","duplicate","enriched","linked"].includes(result.result)){view="My Imports";history.replaceState(null,"","#imports");await refresh();}
     else failures.push(url);
     results.append(importResultRow(result,url));
   }
   input.lastElementChild.value=failures.join("\n");
   localStorage.setItem("tracker-import-links",input.lastElementChild.value);
   progress.textContent="Processed "+urls.length+" jobs · "+failures.length+" to retry or complete";
 });
 showDialog("Import Jobs",editor,progress,results,advanced,button("View My Imports",()=>{dialog.close();navigate("My Imports");}));
}

const assistedFields={
 identity:{name:"Full name in English",email:"Email",phone:"Phone",city:"City",address:"Street address",postal:"Postal code",education:"Education",gender:"Gender (optional)",ethnicity:"Ethnicity (optional)"},
 answers:{work_authorization:"Already authorized to work",sponsorship:"Need employer sponsorship",salary:"Expected pay (include currency and monthly or annual)",available:"Available start date",locations:"Acceptable locations (comma-separated; blank means any)"}
};
const assistedLabels={
 Discovered:"Discovered",Reviewed:"Reviewed","Materials ready":"Materials ready","Assisted filling":"Filling in progress",
 "Awaiting my confirmation":"Awaiting my final confirmation",Submitted:"Submit clicked","Receipt verified":"Receipt verified",
 "Submission unverified":"Submission unverified",Blocked:"Blocked"
};
const assistedNotice="The application is opened in your signed-in browser for you to complete and submit yourself.";
function assistedProfile(pane){
 return async()=>{
  const profile=await api("/api/assisted/profile");
  const region=field("Country / region","country",{options:state.markets}), editor=node("div");
  const update=()=>{
   const country=region.lastElementChild.value, saved=profile.countries[country]||{};
   const inputs=(fields,values,prefix)=>Object.entries(fields).map(([key,title])=>field(title,prefix+key,
    {value:values[key]||"",type:key==="available"?"date":key==="email"?"email":"text",
     options:["work_authorization","sponsorship"].includes(key)?["","Yes","No"]:null,area:key==="education"}));
   editor.replaceChildren(form([...inputs(assistedFields.identity,profile.identity,"i_"),...inputs(assistedFields.answers,saved,"a_"),
     field("I confirm this information is accurate","confirmed",{type:"checkbox",required:true})],"Save application profile",async values=>{
     const take=(fields,prefix)=>Object.fromEntries(Object.keys(fields).map(k=>[k,values[prefix+k]]));
     await api("/api/assisted/profile",{country,identity:take(assistedFields.identity,"i_"),answers:take(assistedFields.answers,"a_"),confirmed:values.confirmed==="on"});
     dialog.close();await assistedPanel(pane);
   }));
  };
  region.addEventListener("change",update);update();
  showDialog("Application Profile",node("p","Your profile stays on this device. Before sending an application, review its fields, materials, and legal statements. Leave optional sensitive fields blank if you prefer."+(profile.draft?"The previous information is a draft. Verify each field before saving.":"")),region,editor);
 };
}
async function assistedPanel(pane){
 const result=await api("/api/assisted");
 const refreshPanel=async()=>{dialog.close();await assistedPanel(pane);};
 const send=async(row,action,data={})=>{await api("/api/assisted/action",{id:row.id,action,...data});await refreshPanel();};
 const evidenceForm=(row,requeue=false)=>showDialog(requeue?"Verify not submitted and requeue":"Verify a receipt manually",node("p","Update the status only with independent evidence. A missing email or receipt does not prove that nothing was submitted."),
   form([...(requeue?[field("Evidence type for non-submission","proof_kind",{options:["Platform rejected","Employer confirmed no application","Platform confirms no application"]})]:[field("Receipt type","proof_kind",{options:["Success page","Application number","Confirmation email"]}),
    field("Actual submission time (UTC)","submitted_at",{type:"datetime-local",required:!row.attempt.submitted}),
    ...(["CV","CL"].map(kind=>field("Actual "+kind+" version used (leave blank if unknown)",kind.toLowerCase(),
      {options:["",...new Set((state.jobs.find(j=>j.id===row.id)?.documents||[]).filter(d=>d.kind===kind).map(d=>d.id))]})))]),
    field("Evidence text or receipt number","proof",{area:true,required:true}),field("I verified this evidence","confirmed",{type:"checkbox",required:true})],
    requeue?"Confirm not submitted and requeue":"Save verified receipt",async v=>send(row,requeue?"requeue":"receipt",
    {...v,submitted_at:v.submitted_at?v.submitted_at+utcOffset(v.submitted_at):null,confirmed:v.confirmed==="on"})));
 const precheck=row=>{
   const p=row.attempt.payload?.precheck||{};
   showDialog("Additional answers for this job",form([field("Pay for this role (include currency and period)","salary",{value:p.salary}),
     field("I authorize use of the saved street address and postal code for this job","address_authorized",{type:"checkbox"}),
     field("I completed verification on the original browser page","captcha_cleared",{type:"checkbox"}),
     field("I confirm these answers apply to this job","confirmed",{type:"checkbox",required:true})],
     "Save answers for this job",v=>send(row,"precheck",Object.fromEntries(Object.entries(v).map(([k,x])=>[k,k==="salary"?x:x==="on"])))));
   for(const key of ["address_authorized","captcha_cleared"])if(p[key])dialogBody.querySelector('[name="'+key+'"]').checked=true;
 };
 const prepare=async row=>{
   const p=await api("/api/assisted/profile");
   const values={...p.identity,...p.countries[row.country]};
   const docLinks=Object.entries(row.documents).map(([kind,id])=>link("Download  "+kind+" · "+id.slice(0,8),"/pdf/"+id+"?download=1",true));
   showDialog("Review application materials · "+row.company,node("p",row.title+" · "+row.channel),node("p",assistedNotice),
    node("p","Use verified answers and upload the materials below on the employer\u0027s site. Log any unknown required answers, verification steps, or legal terms. You make the final submission."),
    node("pre",Object.entries(values).filter(([,v])=>v).map(([k,v])=>(assistedFields.identity[k]||assistedFields.answers[k]||k)+" · "+v).join("\n")),
    box(...docLinks),
    form([field("I reviewed the recipient, information, and documents displayed","reviewed",{type:"checkbox",required:true})],"Open application in a new tab",async v=>{
      const tab=window.open("about:blank","_blank");if(!tab)throw Error("Your browser blocked a new tab. Allow Tracker to open tabs and retry.");
      tab.opener=null;
      try{const opened=await api("/api/assisted/action",{id:row.id,action:"open",reviewed:v.reviewed==="on"});tab.location.replace(opened.url);}
      catch(e){tab.close();throw e;}
      await refreshPanel();
    }));
 };
 const verifyActual=row=>showDialog("Review before final submission",node("p","Check the actual form, legal statements, and uploaded files. After saving your review, submit it yourself on the employer site."),
   form([field("CV actually uploaded","cv",{options:Object.values({CV:row.attempt.payload.docs.CV}),required:true}),
     field("Cover letter actually uploaded (leave blank if none)","cl",{options:["",row.attempt.payload.docs.CL].filter(x=>x!=null)}),
     field("I reviewed the actual information, materials, and statements","reviewed",{type:"checkbox",required:true})],
     "Mark as awaiting my final confirmation",v=>send(row,"review",{docs:{CV:v.cv,...(v.cl?{CL:v.cl}:{})},reviewed:v.reviewed==="on"})));
 const block=row=>showDialog("Record a blocker",form([field("Specific reason (CAPTCHA, login, missing information, etc.)","reason",{area:true,required:true})],"Record blocker",v=>send(row,"blocked",v)));
 const rows=node("div"),filter=field("Filter queue","assisted_filter",{options:["All","Ready for Assisted Apply","Submission unverified","Blocked","Receipt verified"]});
 const showRows=()=>{
   const selection=filter.lastElementChild.value;
   const items=result.jobs.filter(r=>selection==="All"||selection==="Ready for Assisted Apply"&&r.queue_ready||
      selection==="Submission unverified"&&["Submitted","Submission unverified"].includes(r.stage)||
      selection==="Blocked"&&r.stage==="Blocked"||selection==="Receipt verified"&&r.stage==="Receipt verified");
   rows.replaceChildren(node("p","Total: "+items.length+" jobs · Sorted by recency, score, and readiness"));
   for(const row of items){
    const actions=box(), task=node("article",null,{class:"job"});
    if(row.url)actions.append(link(row.route==="Manual application required"?"Open employer site (manual)":"Open original application page",row.url));
    actions.append(button("View job and materials",()=>detail(row.id)));
    if(row.queue_ready&&result.mode==="Assisted Apply"&&row.documents.CV)actions.append(button("Review and open the application",()=>prepare(row),"primary"));
    if(!["Submitted","Submission unverified","Receipt verified","Assisted filling","Awaiting my confirmation"].includes(row.stage)){
     actions.append(button("Additional answers for this job",()=>precheck(row)));
     if(row.stage==="Blocked"&&row.attempt.stage==="Blocked")actions.append(button("Resume after resolving the blocker",()=>showDialog("Resume this job",
       form([field("I verified the blocker was resolved","confirmed",{type:"checkbox",required:true})],"Resume",v=>send(row,"resume",{confirmed:v.confirmed==="on"})))));
     else actions.append(button("Record a blocker",()=>block(row)));
    }
    if(row.stage==="Assisted filling")actions.append(button("Review completed form",()=>verifyActual(row)),button("Record a blocker",()=>block(row)));
    if(row.stage==="Awaiting my confirmation")actions.append(button("I clicked Submit on the employer site",()=>showDialog("Record a submission attempt",
      form([field("I actually clicked Submit on the employer site","confirmed",{type:"checkbox",required:true})],"Record click",v=>send(row,"submitted",{confirmed:v.confirmed==="on"})))),button("Record a blocker",()=>block(row)));
    if(["Submitted","Submission unverified"].includes(row.stage))actions.append(
     ...(row.url?[link("Check page receipt",row.url)]:[]),link("Search confirmation email",row.search_mail),
     button("Verify submission manually",()=>evidenceForm(row)),button("Verify not submitted and requeue",()=>evidenceForm(row,true)));
    task.append(node("h3",row.company+" · "+row.title),node("p",[row.country,row.location,row.score==null?"Not scored":row.score+" points",
       row.fresh?"Originally posted within 72 hours":"Original date unknown or older",row.channel,assistedLabels[row.stage]||row.stage].filter(Boolean).join(" · ")),
     ...(row.blockers.length?[node("p",row.blockers.join("; "))]:[]),
     ...(row.attempt.submitted?[node("p","Recorded submission time · "+row.attempt.submitted)]:[]),
     ...(row.receipt?[node("p","Verification evidence · "+row.receipt)]:[]),actions);
    rows.append(task);
   }
 };
 filter.addEventListener("change",showRows);showRows();
 const modeBox=form([field("Application mode","mode",{options:["Dry Run","Assisted Apply"],value:result.mode}),
   field("I understand the browser workflow","ack",{type:"checkbox"})],"Save mode",async v=>{
    await api("/api/assisted/mode",{mode:v.mode,ack:v.ack==="on"});state.settings.assisted_apply_mode=v.mode;await assistedPanel(pane);
   });
 const c=result.counts;
 pane.replaceChildren(section("Daily application dashboard · "+result.today,node("p","Dates use UTC. Awaiting confirmation, unverified, and blocked counts reflect the current queue. Only verified receipts count toward today's submissions."),
  metrics({"Discovered today":c.discovered,"Ready for queue":c.actionable,"Opened, awaiting confirmation":c.awaiting,"Verified submissions today":c.submitted,"Unverified":c.unverified,"Blocked":c.blocked})),
  section("Application mode · "+result.mode,node("p",assistedNotice),modeBox,
   box(button("Edit application profile",assistedProfile(pane)),button("Paste job URLs",()=>linkImport()))),
  ...(result.backlog.length?[section("Links needing more details",...result.backlog.map(r=>box(link("Open job link",r.url),node("span",r.reason),
     button("Retry loading",async()=>{await api("/api/import/link",{url:r.url});await assistedPanel(pane);}),
     button("Complete job details",()=>importJob(r.url)))))]:[]),filter,rows);
}
function utcOffset(local){ return "+00:00"; }

setInterval(async()=>{
 if(!state||busy||view!=="Dashboard"||dialog.open||!state.cv_queue?.worker?.enabled)return;
 try{
   const next=await api("/api/cv-queue/status");
   if(JSON.stringify(next.counts)!==JSON.stringify(state.cv_queue.counts)||next.worker.enabled!==state.cv_queue.worker.enabled)await refresh();
 }catch(error){/* Keep the last rendered state; user refresh exposes connection errors. */}
},10000);
