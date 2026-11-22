"use strict";
const $=id=>document.getElementById(id);
const content=$("content"),dialog=$("dialog"),dialogBody=$("dialog-body");
let state,view=({"#imports":"My Imports","#applications":"Application Tracker","#assisted":"Assisted Apply"})[location.hash]||"Dashboard",busy=false,tag="候选60",query="";
const labels={"Dashboard":"首页","Job Discovery":"搜索岗位","Candidate Pool":"岗位与材料","My Imports":"我导入的岗位","Application Tracker":"投递记录","Assisted Apply":"辅助投递","Settings":"设置"};
const words={
"United States":"美国","UK":"英国","Canada":"加拿大","UAE":"阿联酋","Japan":"日本","Unverified":"待核实","Active":"雇主确认开放","Closed":"已关闭","Other":"其他",
"Full":"完整","Partial":"待补全","Displayed":"平台显示时间","Reposted":"重发时间","Last published":"最近发布",
"Employer website / ATS":"雇主官网或ATS","Email":"电子邮件","On platform":"平台内申请","External":"外部申请","traditional":"传统行业","web3":"Web3 / 加密行业",
"Import Jobs":"导入岗位","Paste job URLs":"粘贴岗位链接","Select a CSV or JSON export":"选择 CSV 或 JSON 文件",
"Manual search sample (optional)":"手动搜索样本（可选）","Listing URL":"平台岗位链接","Job title":"职位名称","Employer":"雇主",
"Location":"地点","Official employer URL":"雇主直达链接","Observed application route":"已观察到的申请方式",
"Employer closure evidence URL":"雇主关闭证据链接","Requisition ID":"招聘编号","Date as shown":"原始时间标签",
"Date type":"时间类型","Verified industry":"已核实行业","JD completeness":"JD 完整程度","Permitted job description":"完整职位描述",
"Listing":"岗位","Remove listing":"移除此待导入项","Add pasted URLs":"添加粘贴链接","Load export":"读取文件",
"Paste JSON export":"粘贴 JSON 导出内容","Load pasted export":"读取粘贴内容","Add a listing":"手动增加岗位",
"Preview and score":"预览并评分","Open single-job form":"单条导入","Controlled import preview":"确认导入预览",
"Select all importable listings":"全选可导入项","Import selected listings":"确认导入所选岗位","Back to edit listings":"返回修改",
"Total unique jobs":"唯一岗位","Verified active jobs":"雇主确认开放","Verified dates within 14 days":"核实为14天内",
"Verified original posting dates":"已核实首次发布时间","Jobs scoring 80+":"80分及以上","Possible duplicates":"疑似重复",
"Already tracked":"已有记录","Manual review":"待人工核对","Missing job descriptions":"缺少完整JD",
"Work authorization requires manual evidence. Select only listings you want to import for review.":"工作许可需要真实证据。请勾选需要导入审核的岗位。",
"Company":"公司","Source":"发现来源","Market":"国家或地区","Original posting date":"首次发布时间",
"Date evidence":"日期证据","Platform date type":"平台时间类型","Platform date as displayed":"平台时间原文",
"Source job ID":"平台岗位ID","Employer requisition":"雇主招聘编号","Work arrangement":"工作方式","Salary":"薪资",
"Vacancy":"开放状态","Job description":"职位描述","Import":"导入","Paste the complete job description":"粘贴完整职位描述",
"Country":"国家","Employer requisition ID":"雇主招聘编号","Save as a separate job":"另存为不同岗位",
"Save the complete description. Eligibility will remain separate from material preparation.":"保存完整JD。材料准备与申请资格分别处理。",
"Confirm complete JD and save":"确认JD完整并保存","Original listing":"原始岗位","Verified employer listing":"雇主岗位",
"Source listing":"原来源岗位","Possible employer listing":"可能对应的雇主岗位","No vacancies extracted.":"未提取到可用岗位。",
"Login required":"需要登录","Redirected":"发生跳转","Summary only":"仅摘要","Explicitly closed":"明确下架",
"Request failed":"读取失败","Unknown":"原因未知","Readable":"可读","None":"无",
"Met":"已核实满足","Failed":"不满足","Not required":"雇主不要求",
"Work authorization":"工作许可","Visa sponsorship":"签证赞助","Employer-specific restrictions":"雇主硬性限制",
"License / certification":"证书","Languages":"语言","Technical requirements":"技术要求","Experience":"经验","Location / relocation":"地点及搬迁"
};
function tx(value){if(value==null)return value;return words[value]||value;}
const node=(name,text,attrs={})=>{const e=document.createElement(name);if(text!=null)e.textContent=tx(text);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;};
const button=(label,fn,cls)=>{const e=node("button",label,{type:"button",...(cls?{class:cls}:{})});e.addEventListener("click",()=>action(fn));return e;};
const link=(label,href,download=false)=>node("a",label,{href,target:"_blank",rel:"noopener noreferrer",class:"button",...(download?{download:""}:{})});
const box=(...items)=>{const d=node("div",null,{class:"actions"});d.append(...items);return d;};
const section=(title,...items)=>{const s=node("section");s.append(node("h2",title),...items);return s;};
const empty=label=>node("p",label,{class:"empty"});
function notice(text){$("notice").textContent=tx(text);$("notice").hidden=!text;}
async function api(path,data){const r=await fetch(path,data==null?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});const value=await r.json();if(!r.ok)throw Error(value.error||"操作失败");return value;}
async function action(fn){if(busy)return;busy=true;try{await fn();}catch(e){const text="操作未完成。"+friendlyError(e.message);if(dialog.open)alert(text);else notice(text);}finally{busy=false;}}
function friendlyError(message){const errors={"The original-template CV could not be rendered.":"原模板CV转PDF失败，请重试。",
"The revised CV did not fit one page at the original settings.":"内容无法在原版式内排成一页，本次未保存材料。",
"The editable CV bullets differ from the verified Main CV.":"main.docx的经历要点与已核实主简历不一致，请核对源文件。",
"The model summary does not fit the source CV slot.":"生成的摘要不符合原模板长度，请重试。",
"A CV bullet exceeds the template slot or adds unsupported numbers.":"生成的要点超出模板容量或包含未核实数字，请重试。",
"The cover letter must have 250 to 350 words.":"求职信字数未达到250至350词要求，请重试。",
"The cover letter referenced unavailable evidence.":"求职信引用了不可用的经历证据，请重新生成。",
"A cover letter paragraph contains unsupported numbers.":"求职信出现未经核实的数字，未保存本次材料。",
"Job changed during generation. Reopen and retry.":"生成期间岗位内容发生变化，请打开最新岗位重试。",
"Use two distinct examples with verified fact references.":"求职信需要引用两段独立的已核实经历，请重新生成。","The signed-in Codex generation did not complete. No model versions were saved.":"模型调用未完成，未保存材料，请稍后重试。","Verify the alert details and supply the full job description.":"平台来源的原始日期、地点或雇主信息仍需核实。",
"Work authorization needs verified evidence.":"需要确认该国家的合法工作权利。",
"Visa sponsorship compatibility needs verified evidence.":"需要确认是否需要签证赞助及雇主是否支持。",
"Employer-specific restrictions need verified evidence.":"需要核对雇主明确的限制条件。",
"Mandatory eligibility is not fully verified.":"硬性申请条件尚未全部核实。",
"Active vacancy needs verification.":"自动申请仍需雇主开放状态证据，手动候选可保留。",
"Verify an original posting date within 14 days.":"自动申请所需的14天内首次发布时间尚未核实。",
"Match score must be at least 80.":"自动申请需要至少80分。",
"A complete JD is required.":"请先补充完整JD。","Job not found.":"未找到岗位。","Material version not found.":"材料版本不存在。","This vacancy is closed.":"岗位已关闭。","Confirm that you submitted this application yourself.":"请确认你已经实际提交。","This vacancy already has a confirmed or unresolved application record.":"该岗位已有投递记录或结果未明，请先核对历史。","Select the exact CV and cover-letter versions used.":"请选择实际使用的CV和求职信版本。"};return errors[message]||(/[a-z]{5}/i.test(message)?"请核对岗位记录或生成失败详情。技术原因："+message:message);}
async function refresh(){
 try{state=await api("/api/state");render();}
 catch(error){
  let health={};try{health=await api("/api/health");}catch(ignore){}
  content.replaceChildren(section("暂时无法读取岗位数据",node("p","请保留现有数据，不要重复导入或生成材料。"),
   node("p","调度状态："+(health.scheduler?.state||"服务不可达")+" · "+(health.scheduler?.error||"")),
   button("重新检查",()=>refresh())));
  throw error;
 }
}
function showDialog(title,...items){$("dialog-title").textContent=tx(title);dialogBody.replaceChildren(...items);if(!dialog.open)dialog.showModal();}
function field(label,name,opts={}){let input;if(opts.options){input=node("select",null,{name});input.append(...opts.options.map(x=>node("option",x,{value:x})));}else input=node(opts.area?"textarea":"input",null,{name,...(opts.area?{}:{type:opts.type||"text"})});if(opts.value!=null)input.value=opts.value;if(opts.required)input.required=true;const wrap=node("label",label,opts.area?{class:"wide"}:{});wrap.append(input);return wrap;}
function form(fields,label,submit){const f=node("form"),g=node("div",null,{class:"form-grid"});g.append(...fields);f.append(g,node("button",label,{class:"primary",type:"submit"}));f.addEventListener("submit",e=>{e.preventDefault();action(()=>submit(Object.fromEntries(new FormData(f))));});return f;}
function metrics(items){const g=node("div",null,{class:"metrics"});for(const[label,value]of Object.entries(items)){const card=node("div",null,{class:"metric"});card.append(node("strong",String(value)),node("small",label));g.append(card);}return g;}
function fitLabel(score,eligible){return eligible?"申请资格已核实":score>=80?"高匹配 · 待核实":"";}
const readyCV=job=>Boolean(job.current_documents?.CV);
function current(job,kind){return job.current_documents?.[kind]||null;}
function stale(job,doc){return doc&&(job.materials_stale||doc.jd_hash!==job.match?.jd_hash||doc.source_hash!==job.match?.source_hash);}
function materialActions(job){
 const group=node("div",null,{class:"material-actions"});
 const gen=job.generation;
 group.append(button(gen?.state==="running"?"生成中…":"生成材料",()=>generate(job),"primary"));
 if(gen?.state==='completed')group.append(node('small','本次任务完成 · 耗时 '+gen.elapsed_seconds+' 秒；材料需你审核，未提交申请'));
 if(gen?.state==='running')group.append(node('p',(gen.step||'后台处理中')+' · 已耗时 '+gen.elapsed_seconds+' 秒'));
 if(gen?.state==="failed")group.append(node("p","生成失败 · "+friendlyError(gen.error),{class:"notice-line"}));
 for(const[kind,label]of [["CV","CV"],["CL","求职信"]]){
   const d=current(job,kind),row=box();
   row.append(node("strong",label));
   if(!d){row.append(node("small","未生成"));}else{
     row.append(link("预览"+label,"/pdf/"+d.id),link("下载"+label,"/pdf/"+d.id+"?download=1",true));
     if(kind==="CL"){
       const review=d.metadata?.cl_review;
       row.append(node("small",review?.status||"历史版本 · 尚未执行新审核"),button("查看／复制／编辑求职信",()=>letterView(job,d)));
     }
     if(kind==="CV")row.append(link("下载DOCX","/docx/"+d.id,true));
     row.append(node("small",d.created+" · 版本 "+d.id.slice(0,8)+(stale(job,d)?" · 材料可能需要更新":kind==="CL"?"":" · 已完成")));
   }group.append(row);
 }
 return group;
}
async function generate(job){
 const genLabel=node("p","正在使用 high 生成英文 CV 和跟随JD语言的求职信，完成后会保存为新版本。");
 showDialog("生成材料",genLabel,link("查看岗位记录","/#job="+job.id));
 try{await api("/api/manual/generate",{id:job.id,use_model:true,regenerate:true});await refresh();detail(job.id);}
 catch(e){await refresh();detail(job.id);throw e;}
}
function handoffButton(job){
 return button("打开申请入口",async()=>{
   const tab=window.open("about:blank","_blank");
   if(!tab)throw Error("浏览器拦截了新标签页，请允许后重试。");
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
   actions.append(button("补充回执",()=>showDialog("补充回执",form([field("确认邮件引用或申请编号","receipt",{required:true})],"保存",async x=>{await api("/api/manual/receipt",{id:job.id,...x});await refresh();recordView(state.jobs.find(j=>j.id===job.id));}))),
   button("更正记录",()=>showDialog("更正记录",form([field("投递日期","date",{type:"date",value:data.date,required:true}),field("实际提交渠道","channel",{options:["Employer website / ATS","LinkedIn","Indeed","Email","Other"],value:data.channel}),field("更正原因","reason",{required:true,area:true})],"保存更正",async x=>{await api("/api/manual/correct",{id:job.id,...x});await refresh();recordView(state.jobs.find(j=>j.id===job.id));}))),
   button("纠正误标",()=>showDialog("纠正误标",node("p","填写原因后撤销有效计数，原记录继续留档。"),form([field("原因","reason",{required:true,area:true})],"确认撤销误标",async x=>{await api("/api/manual/correct",{id:job.id,...x,cancel:true});await refresh();detail(job.id);}))));
 }else if(job.current_documents?.CV&&job.current_documents?.CL)actions.append(button("标记为已投递",()=>manualApplication(job)));
 showDialog("投递记录",node("h3",job.company+" · "+job.title),node("p","状态 · "+job.workflow_state+(data&&!data.receipt?" · 回执待补充":data?" · 回执已记录":"")),
   node("p","发现来源 · "+[...new Set(job.source_links.map(s=>s.platform))].join("、")),
   box(link("岗位链接",job.url||job.apply_url),link("申请入口",job.platform_application?.url||job.apply_url||job.url)),
   data?node("p","投递日期 "+data.date+" · 实际渠道 "+tx(data.channel)+" · CV "+(data.cv||data.CV)+" · 求职信 "+(data.cl||data.CL)):node("p","尚未记录实际投递。"),
   lastOpen?node("p","上次打开申请页 "+lastOpen.created):node("span"),
   data?node("p","时间 "+(data.submitted_at||legacy?.created||"历史记录")+" · 回执 "+(data.receipt||"待补充")+" · 备注 "+(data.notes||"无")):node("span"),
   actions,section("历史记录",history));
}
function manualApplication(job){
 const versions=(kind,label)=>field(label,kind.toLowerCase(),{options:["",...job.documents.filter(d=>d.kind===kind).map(d=>d.id)],value:current(job,kind)?.id,required:true});
 showDialog("标记为已投递",node("p","仅在你实际提交后记录。打开页面、下载、草稿和结果不明均计0份。"),
 form([field("投递日期","date",{type:"date",value:state.today,required:true}),
 field("实际提交渠道","channel",{options:["Employer website / ATS","LinkedIn","Indeed","Email","Other"]}),
 versions("CV","使用的CV版本"),versions("CL","使用的求职信版本"),field("回执或申请编号（可选）","receipt"),field("备注","notes",{area:true})],
 "确认已实际提交",async x=>{await api("/api/manual/application",{id:job.id,...x,confirmed:true});await refresh();recordView(state.jobs.find(j=>j.id===job.id));}));
}
function eventDescription(event){
 try {
   const d=JSON.parse(event.detail);
   if(event.kind==="Manually Applied")return "投递日期 "+d.date+" · 实际渠道 "+tx(d.channel)+" · CV "+d.CV+" · 求职信 "+d.CL+" · "+(d.notes||"");
   if(event.kind==="Manual submission corrected")return (d.cancel?"撤销误标":"更正日期或渠道")+" · 原因 "+d.reason;
   if(event.kind==="Materials approved")return "CV "+d.CV+" · 求职信 "+d.CL;
   if(event.kind==="Pilot review")return d.blockers.length?"等待核对资料与资格":"等待你确认本次真实提交";
 }catch(error){}
 return event.detail;
}
function eventLabel(kind){return {"Manually Applied":"手动投递","Manual submission receipt":"回执核实","Manual submission corrected":"投递更正","Application page opened":"打开申请页","Official application opened":"打开官网","Materials approved":"材料已审核","Pilot review":"试点核对","Submitted":"提交已确认"}[kind]||kind;}
function docs(job){
 return job.documents.map(d=>box(node("span",(d.kind==="CV"?"CV":"求职信")+" · "+d.created+" · "+d.id.slice(0,8)),
 node("small",d.metadata?"模板 "+d.metadata.template:"历史材料 · 旧版排版"),
 link("预览","/pdf/"+d.id),link("下载","/pdf/"+d.id+"?download=1",true),...(d.kind==="CL"?[button("查看／复制／编辑",()=>letterView(job,d))]:[])));
}
function qualificationForm(job){
 const fields=state.checks.flatMap(key=>[
   field(key,key,{options:key==="Work authorization"?["Unverified","Met","Failed"]:["Unverified","Met","Not required","Failed"],value:job.match?.checks[key]?.state}),
   field(tx(key)+"证据",key+"-reason",{value:job.match?.checks[key]?.reason,area:true})
 ]);
 showDialog("核实申请资格",node("p","只填写你已确认的事实。未说明或不确定的条件继续保持待核实。"),
 form(fields,"保存并重评",async data=>{
   const checks=Object.fromEntries(state.checks.map(key=>[key,{state:data[key],reason:data[key+"-reason"]}]));
   await api("/api/score",{id:job.id,checks});await refresh();detail(job.id);
 }));
}
function detail(id){
 const j=state.jobs.find(j=>j.id===id);if(!j)return;
 history.replaceState(null,"","#job="+id);
 const originals=[...new Set([...(j.source_links||[]).map(x=>x.url),...j.events.filter(e=>e.kind==="Manually imported").map(e=>e.detail)].filter(url=>/^https?:\/\//i.test(url||"")))];
 const actions=box(...originals.map(url=>link("原始岗位链接",url)),button("手动补充／高级编辑",()=>importJob(j.url||"",j)),button("补充JD",()=>pasteJD(j)),button("核实申请资格",()=>qualificationForm(j)),button("投递记录",()=>recordView(j)),button("准备提交前试点",async()=>{
   const r=await api("/api/pilot/review",{id:j.id});await refresh();showDialog("提交前核对",node("p",j.company+" · "+j.title),
   node("p","真实投递开关关闭。当前仅准备资料，不提交。"),node("pre",r.blockers.map(friendlyError).join("\n")||"条件已齐备，等待你对具体岗位、答案和版本的明确确认。"),
   node("pre","CV "+(r.versions.CV||"未生成")+"\n求职信 "+(r.versions.CL||"未生成")));
 }));
 actions.append(button("单独生成求职信",async()=>{
   showDialog("生成求职信",node("p","正在匹配事实、写作并执行独立内容修订；缺少完整JD时只保存通用草稿。"));
   await api("/api/cl/generate",{id:j.id});await refresh();detail(j.id);
 }));
 if(j.industry.state==="review")actions.append(button("确认雇主属于传统行业",async()=>{
   await api("/api/industry",{id:j.id,decision:"traditional"});await refresh();detail(j.id);
 }));
 const cv=current(j,"CV"),cl=current(j,"CL");
 if(cv&&cl)actions.append(button("材料已审核，转待我投递",async()=>{await api("/api/materials/approve",{id:j.id,CV:cv.id,CL:cl.id});await refresh();detail(id);}));
 if(j.vacancy!=="Closed")actions.append(handoffButton(j));
 const checks=node("ul");for(const[k,v]of Object.entries(j.match?.checks||{}))checks.append(node("li",tx(k)+" · "+tx(v.state)+" · "+(v.jd?.length?"JD有相关要求，请核对原文":"JD未说明")+" · "+(v.reason||"尚未确认")));
 const match=node("ul");for(const part of j.match?.parts||[])for(const e of part.evidence||[])if(e.cv?.length)match.append(node("li",e.keyword+" · "+e.cv.map(f=>f.text).join(" ")));
 const all=node("details");all.append(node("summary","历史材料与版本（"+j.documents.length+"份）"),...docs(j));
 showDialog(j.title,node("p",j.company+" · "+tx(j.country)+" · "+(j.location||"地点待补充")+" · "+j.workflow_state),
 node("p",(j.requisition?"招聘编号 "+j.requisition+" · ":"")+(j.posted?"页面日期 "+j.posted+" · ":"")+(j.date_evidence||"")),
 node("p","主简历 "+(j.match?.score??"待评分")+(j.tailored_fit?" · 定制CV "+j.tailored_fit.score:"")+" · "+(j.date_signal?.label||"日期待核实")),actions,
 section("对应材料",materialActions(j),all),
 section("本人已确认的工作状态",node('p',state.work_profiles?.[j.country]?({Authorized:'已确认有工作权利','Requires sponsorship':'需要雇主赞助（不代表已有工作许可）','Not authorized':'目前无合法工作权利'}[state.work_profiles[j.country].state]||'待确认')+' · '+state.work_profiles[j.country].evidence:'该国家尚未确认'),node('p','雇主是否支持赞助需另行核实；高分和材料完成不会使申请资格自动通过。')),
 ...(j.japan_review?[section("日本岗位核对",...j.japan_review.map(reason=>node("p",reason)))]:[]),
 section('雇主赞助证据',node('p',j.sponsorship_evidence?.state||'未知'),node('pre',(j.sponsorship_evidence?.evidence||[]).join('\n'))),section("申请资格",checks),
 section("匹配依据",node("p","本地关键词重叠分，不是录用概率。资格检查独立于分数。"),
 ...((j.match?.parts||[]).map(p=>node("p",p.name+" "+p.points+"/"+p.weight+
 (p.diagnostic?" · "+p.diagnostic.formula+" · "+(!p.diagnostic.requested_terms.length?"JD未识别到本项词汇，0分不代表资格不符":"缺少词汇证据："+(p.diagnostic.unmatched_terms.join("、")||"无")):p.name==="Seniority"?" · 仅按职称估计":p.name==="Location and working arrangement"?" · 目标市场，不代表工作许可":" · 历史评分未保存逐项诊断")))),match),section("主要缺口",node("p",j.match?j.match.gaps?.join("、")||"规则未检测到关键词缺口，仍需核对硬性要求。":"完成评分后显示主要缺口。")),
 section("职位描述",node("pre",j.jd||"请补充完整JD。")),
 ...j.events.filter(e=>e.kind==="Import screenshot").map(e=>link("查看导入截图","/import-evidence/"+e.detail)),
 section("备注",form([field("备注","notes",{area:true,value:j.notes})],"保存备注",async data=>{await api("/api/update",{id,...data});await refresh();detail(id);})));
}
function jobCard(j){
 const card=node("article",null,{class:"job-card"});
 card.append(box(button(j.title,()=>detail(j.id),"row-title"),node("span",j.workflow_state,{class:"tag"})),
 node("p",j.company+" · "+tx(j.country)+" · "+(j.location||"地点待补充")+(j.posted?" · "+j.posted:"")),
 node("p","主简历 "+(j.match?.score??"未评分")+" · "+(j.platform_application?"平台显示可申请":tx(j.vacancy))+" · "+j.date_signal.label));
 card.append(materialActions(j),box(button("查看岗位",()=>detail(j.id)),button("投递记录",()=>recordView(j)),
 handoffButton(j)));
 return card;
}
function listJobs(rows,target){
 target.replaceChildren();let page=0;
 const controls=box(),items=node("div");
 const paint=()=>{items.replaceChildren(...rows.slice(page*10,page*10+10).map(jobCard));controls.replaceChildren(node("p","共"+rows.length+"条 · 第"+(page+1)+"页"),
 button("上一页",()=>{page=Math.max(0,page-1);paint();}),button("下一页",()=>{if((page+1)*10<rows.length){page++;paint();}}));};
 if(!rows.length){target.append(empty("当前筛选下没有岗位。"));return;}
 target.append(controls,items);paint();
}
function table(rows,target){listJobs(rows,target);}
function jobsPanel(records=false){
 const toolbar=box(),target=node("div");const search=node("input",null,{type:"search",placeholder:"搜索公司或职位",value:query,"aria-label":"搜索公司或职位"});
 const market=field("地区","market",{options:["",...state.markets]}),status=field("状态","status",{options:["","待生成材料","待审核","待我投递","需我处理","提交结果待核实","已投递","面试中","被拒","已关闭"]});
 const tabs=box();let chosen=tag;
 const update=()=>{
   let rows=state.jobs.filter(j=>j.industry.state!=="excluded");
   if(!records){
     const groups={"候选60":state.candidate_pool,"当日补位":[...state.queues.recent,...state.queues.week,...state.queues.month],"高匹配常驻":state.queues.high,"简历最佳匹配":state.queues.resume};
     if(groups[chosen]){const ids=new Set(groups[chosen]);rows=rows.filter(j=>ids.has(j.id));}
     if(chosen==="72小时近期")rows=rows.filter(j=>j.fresh_discovery);
     if(chosen==="日期待核实")rows=rows.filter(j=>!j.original_posted_at&&j.vacancy!=="Closed");
   }else rows=rows.filter(j=>j.application_record||j.events.some(e=>/Applied|Submitted|Pilot review|Official application opened|Materials approved/.test(e.kind))||["待审核","待我投递","需我处理","提交结果待核实"].includes(j.workflow_state));
   const m=market.lastElementChild.value,st=status.lastElementChild.value;
   rows=rows.filter(j=>(!m||j.country===m)&&(!st||j.workflow_state===st)&&(j.company+" "+j.title).toLowerCase().includes(search.value.toLowerCase()));
   rows.sort((a,b)=>(b.match?.score||0)-(a.match?.score||0));listJobs(rows,target);
 };
 if(!records)for(const name of ["候选60","当日补位","高匹配常驻","简历最佳匹配","72小时近期","日期待核实","全部岗位"])tabs.append(button(name,()=>{tag=chosen=name;for(const b of tabs.children)b.classList.toggle("selected",b.textContent===name);update();},name===chosen?"selected":""));
 toolbar.append(search,market,status,button("粘贴JD",()=>pasteJD()),button("批量评分",async()=>{const r=await api("/api/match/batch",{});await refresh();notice("已完成"+r.scored+"条评分。");}));
 search.addEventListener("input",()=>{query=search.value;update();});market.addEventListener("change",update);status.addEventListener("change",update);
 content.append(tabs,toolbar,target);update();
}
let selectedApplicationDate="";
function applicationDay(){
 const date=field("投递日期（UTC）","application-date",{type:"date",value:selectedApplicationDate||state.today});
 const input=date.lastElementChild, summary=box(), heading=node("h2","今日投递");
 const load=async()=>{
   if(!input.value)return;
   const requested=input.value;
   selectedApplicationDate=requested;
   heading.textContent=requested===state.today?"今日投递":requested+" 投递统计";
   summary.replaceChildren(node("p","正在读取…"));
   try{
     const groups=await api("/api/application-day?date="+encodeURIComponent(requested));
     if(input.value!==requested)return;
     const labels={automatic:"自动提交成功",manual:"手动提交成功",pending:"待确认",blocked:"失败／受阻"};
     summary.replaceChildren(...Object.entries(labels).map(([key,label])=>button(label+" "+groups[key].length,()=>{
       showDialog(label+" · "+requested,...(groups[key].length?groups[key].map(r=>section(r.company+" · "+r.title,
         node("p",tx(r.country)+" · "+tx(r.channel)+" · "+r.time),
         node("p","CV "+(r.cv||"—")+" · 求职信 "+(r.cl||"—")),
         node("p",r.receipt?"凭据 · "+r.receipt:r.detail||"待补充"),
         button("查看岗位",()=>detail(r.job)))):[node("p","该日没有此类记录。")]));
     })));
   }catch(error){if(input.value===requested)summary.replaceChildren(node("p",friendlyError(error.message)));}
 };
 input.addEventListener("change",load);
 load();
 return section("按UTC日期",heading,date,summary);
}
function dashboard(){
 const h=state.discovery_health||{}, q=state.cv_queue||{counts:{}}, receipts=state.receipt_summary||{};
 const healthLabel={done:"今日已完成",failed:"今日运行失败",missing:"今日尚无运行",scheduled:"等待计划时间",running:"正在发现"}[h.state]||"状态未知";
 const eligible=state.jobs.filter(j=>!j.retention_blocker&&j.industry.state==="allowed"&&j.vacancy!=="Closed"&&!["Manually Applied","Submitted","Submission Confirmation Unknown","Rejected","Withdrawn","Not Interested","Duplicate"].includes(j.status)&&
   (j.match?.score||0)>=state.settings.high&&!Object.values(j.match?.checks||{}).some(c=>c.state==="Failed")&&!j.sponsorship_evidence?.excluded);
 const priorities=state.settings.priority_locations||[];
 const priority=j=>priorities.some(x=>(j.location||"").toLowerCase().includes(x.toLowerCase()))?1:0;
 eligible.sort((a,b)=>(b.match?.score||0)-(a.match?.score||0)||priority(b)-priority(a));
 content.append(node("p","先看值得保留的岗位，再核实资格和材料。所有申请由你手动提交。",{class:"muted"}),
 metrics({"高匹配待复核":eligible.length,"CV待准备":q.counts.preview||0,"今日有回执":(receipts.manual||0)+(receipts.automatic||0),"提交结果未知":state.jobs.filter(j=>j.status==="Submission Confirmation Unknown").length}));
 const health=section("今日发现",box(node("strong",healthLabel,{class:"tag "+(h.state==="failed"||h.stale?"warning":"")}),
 node("span",h.timezone+" · "+state.settings.schedule+" · "+(h.stale?"结果已过期／尚无成功记录":"最近结果有效"))),
 node("p","最近无报错运行："+(h.last_success||"无")+" · 下次计划："+state.next_run),
 node("p","Mac需要运行且文件可读；无报错不等于岗位资格或投递目标达标。",{class:"muted"}));
 const problems=Object.entries(state.dependency_health||{}).filter(([k,v])=>!v.readable);
 if(problems.length)health.append(node("p","材料依赖不可读："+problems.map(([k,v])=>k+" / "+v.reason).join("、"),{class:"notice-line"}));
 if(state.scheduler_health?.error)health.append(node("p","调度检查："+state.scheduler_health.error,{class:"notice-line"}));
 content.append(health);
 const shortlist=section("优先查看 · 高匹配岗位",node("p","分数是CV词汇匹配；地点优先仅用于同分排序，工签、语言与赞助仍独立核实。",{class:"muted"}));
 for(const j of eligible.slice(0,8)){
   const row=node("article",null,{class:"compact-job"});
   const cv=j.current_documents?.CV;
   row.append(box(button(j.company+" · "+j.title,()=>detail(j.id),"row-title"),node("strong",String(j.match.score),{class:"score"})),
     node("p",tx(j.country)+" · "+j.location+" · "+(j.fresh_discovery?"已证实近期首次发布":j.original_posted_at?"原始日期已记录":"原始发布时间未知")),
     node("p",(cv&&!j.materials_stale?"CV已有当前版本":"CV待准备")+" · "+(j.application_blockers?.length?"资格待核实："+j.application_blockers.length+"项":"资格检查已满足")),
     box(button("证据与阻断",()=>detail(j.id)),button("材料与版本",()=>detail(j.id))));
   shortlist.append(row);
 }
 if(!eligible.length)shortlist.append(empty("当前没有达到阈值的可复核岗位；可检查发现状态、地区配置或完整JD，不会自动降低门槛。"));
 shortlist.append(button("查看全部岗位",()=>navigate("Candidate Pool")));
 content.append(shortlist);
 const queue=section("CV准备队列",node("p",q.worker?.enabled?"CV自动生成已明确启用：每日最多 "+q.daily_limit+" 次尝试；仅CV，CL按需，仍须人工审阅。":"模型已禁用：仅保留规划，不发送个人资料、不调用付费模型。启用需先核实账号、目的地、资料授权与成本。"),
 box(node("span","已规划 "+(q.counts.preview||0)+" · 进行中 "+(q.counts.generating||0)+" · 已就绪 "+(q.counts.ready||0)+" · 失败 "+(q.counts.failed||0)+" · 阻断 "+(q.counts.blocked||0)),
 button("检查队列",async()=>{await api("/api/cv-queue/reconcile",{});await refresh();})));
 queue.append(node("p","今日消费尝试 "+(q.used_today||0)+" / "+q.daily_limit+"；失败及明确重试也计入上限。",{class:"muted"}));
 const queueList=node("details"); queueList.append(node("summary","查看排队原因和版本状态"));
 for(const item of (q.rows||[]).slice(0,15)){
   const j=state.jobs.find(j=>j.id===item.job);
   const itemBox=box(button(j?j.company+" · "+j.title:"岗位",()=>detail(item.job)),node("span",item.state+" · "+item.reason));
   if(item.state==="failed"&&item.attempts<3)itemBox.append(button("明确重试本条",async()=>{await api("/api/cv-queue/retry",{key:item.key,confirmed:true});await refresh();}));
   queueList.append(itemBox);
 }
 queue.append(queueList);content.append(queue);
 const history=node("details");history.append(node("summary","运行历史与来源健康"),
 node("p","无记录日期："+(state.cadence?.missing_dates?.join("、")||"无")+" · 失败日期："+(state.cadence?.failed_dates?.join("、")||"无")));
 for(const r of state.runs.slice(0,10)){
   const d=node("details"),v=r.result;d.append(node("summary",r.created+" · "+r.kind+" · "+(v.running?"未完成":v.errors?.length?"失败／部分完成":"无报错")),
   node("p","新增 "+(v.added||0)+" · 重复输入命中 "+(v.duplicates||0)+" · 唯一岗位 "+(v.discovery?.["Unique jobs discovered"]??"未完成统计")),
   node("pre",(v.errors||[]).join("\n")||"无记录错误"));
   history.append(d);
 }
 history.append(node("pre",Object.entries(state.source_health||{}).map(([k,v])=>k+" · "+v.state+" · 原始 "+(v.retrieved??"—")+" / 筛选 "+(v.targeted??"—")).join("\n")));
 content.append(history,section("人工提交与凭据",node("p","今日成功凭据 "+((receipts.manual||0)+(receipts.automatic||0))+" · 今日登记待确认 "+(receipts.pending||0)+" · 今日受阻 "+(receipts.blocked||0)),
 box(button("投递与回执记录",()=>navigate("Application Tracker")),button("辅助投递",()=>navigate("Assisted Apply")))));
}

function settings(){
 const advanced=node('details');advanced.append(node('summary','高级：系统维护的补充雇主源'),node('p','这些公司列表仅是补充来源，不代表全加拿大招聘市场。无需手动填写。'),node('pre','Greenhouse: '+state.settings.boards+'\nLever: '+state.settings.lever_boards));content.append(advanced);
 const s=state.settings;content.append(section("运行设置",node("p","辅助投递模式："+(s.assisted_apply_mode||"Dry Run")+"。切换及申请资料复核在「辅助投递」。"),
 node("p",`候选门槛 ${state.settings.saved} 分 · 高匹配 ${state.settings.high} 分 · 原始发布窗口 ${state.settings.fresh_hours} 小时 · 投递仍由本人确认`),
 form([field("每日发现时间","schedule",{type:"time",value:s.schedule}),
 field("发现时区（IANA）","timezone",{value:s.timezone,required:true}),
 field("启用国家（逗号分隔）","enabled_countries",{value:s.enabled_countries.join(", "),required:true}),
 field("优先地点（同分排序）","priority_locations",{value:s.priority_locations.join(", ")}),
 field("近期原始发布时间（小时）","fresh_hours",{type:"number",value:s.fresh_hours}),
 field("候选最低分","saved",{type:"number",value:s.saved}),
 field("待复核分界","pending",{type:"number",value:s.pending}),
 field("高匹配分界","high",{type:"number",value:s.high}),
 field("自动CV排队最低分","cv_queue_threshold",{type:"number",value:s.cv_queue_threshold}),
 field("每日CV预算上限（当前预览不调用）","cv_queue_daily_limit",{type:"number",value:s.cv_queue_daily_limit})],"保存设置",async x=>{await api("/api/settings",{...s,...x});await refresh();notice("设置已保存。");})),
 section("申请资料",node("p","仅保存你亲自确认的答案。工作许可按国家核对，未填写的问题会暂停申请。"),
 form([field("国家","country",{options:state.markets}),field("英文姓名","name"),field("邮箱","email",{type:"email"}),field("电话","phone"),
 field("合法工作权利的具体状态","work_authorization"),field("是否需要雇主赞助","sponsorship"),field("薪资答案（可留空）","salary"),field("其他已确认答案","other",{area:true}),
 field("我确认以上资料真实准确","confirmed",{type:"checkbox"})],"保存已确认资料",async x=>{
   if(x.confirmed!=="on")throw Error("请先确认资料真实准确。");
   const answers=Object.fromEntries(["name","email","phone","work_authorization","sponsorship","salary","other"].map(k=>[k,x[k]]));
   await api("/api/application-profile",{country:x.country,answers,confirmed:true});await refresh();notice("已确认资料已保存。");
 })),
 section("主简历与材料",link("主简历PDF","/main.pdf"),node("p","CV唯一排版底稿为 main.docx。新生成材料保存模板指纹、生成时间、版本和源文件。")),
 section("备份",button("创建数据库备份",async()=>{await api("/api/backup",{});notice("备份已创建。");})));
}
function navigate(next){view=next;history.replaceState(null,"",location.pathname+(next==="My Imports"?"#imports":next==="Application Tracker"?"#applications":next==="Assisted Apply"?"#assisted":""));render();}
function render(){
 document.querySelector(".local").textContent="本地求职工作台 · "+state.environment;
 content.replaceChildren();content.setAttribute("aria-busy","false");$("title").textContent=labels[view];
 for(const b of document.querySelectorAll("nav button"))b.toggleAttribute("aria-current",b.dataset.view===view);
 if(view==="Dashboard")dashboard();
 else if(view==="Job Discovery"){content.append(coverageView(),node('p','地区可配置为加拿大、美国、日本、阿联酋和英国；自动读取仅覆盖已接入的公开ATS雇主。LinkedIn、Indeed及其他公司官网通过搜索入口和人工导入补充，不代表已自动遍历全市场。Fresh Discovery按配置窗口要求可核验的首次发布时间，并共用历史去重。'),publicSearch(),box(button("公开雇主源发现",async()=>{const r=await api("/api/run",{active_only:true});await refresh();notice("新增"+r.added+"条岗位。");}),button("根据主简历找岗位",async()=>{const r=await api("/api/resume/discover",{});await refresh();notice("新增"+r.added+"条岗位。");}))); }
 else if(view==="Candidate Pool")jobsPanel();
 else if(view==="My Imports")myImports();
 else if(view==="Assisted Apply"){const pane=node("div","正在读取投递队列…");content.append(pane);assistedPanel(pane).catch(e=>pane.replaceChildren(node("p",e.message)));}
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
      " · "+({"Manual review":"待核对","Already tracked":"已有记录","Possible duplicate":"疑似重复","Excluded industry":"行业排除","Employer closed":"雇主已关闭","Historical listing":"历史岗位","Attach source to existing job":"关联到已有岗位"}[job.status]||job.status)+" · "+(job.active?"雇主确认开放":job.platform_open?"平台显示可申请":job.status==="Employer closed"?"已关闭":"开放状态待核实")+
      " · 发布时间 "+(job.posted||"待核实")+" · 分数 "+(job.score??"待评分")));
    const links=box(link("Source listing",job.url));
    if(job.employer_url)links.append(link("Verified employer listing",job.employer_url));
    for(const url of job.possible_employer_urls||[])links.append(link("Possible employer listing",url));
    const fit=fitLabel(job.score,!job.blockers?.length);
    rows.append(section(job.title,summary,node("p",[job.shortlisted?"Shortlisted":"",job.location,fit,job.date_evidence].filter(Boolean).join(" · ")),links,
      job.platform_date_label?node("p",job.platform_date_label+" · "+job.platform_date_evidence):node("span"),
      job.fit_points?.length?node("p",job.fit_points.map(part=>part.name+" "+part.points+"/"+part.weight).join(" · ")):node("span"),
      job.fit_evidence?.length?node("p","简历匹配依据："+job.fit_evidence.join(", ")):node("span"),
      job.fit_gaps?.length?node("p","缺少的依据："+job.fit_gaps.join(", ")):node("span"),
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
  const links=node("textarea",null,{"aria-label":"Paste job URLs",placeholder:"粘贴LinkedIn或Indeed岗位链接，每行一条"});
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
  const showEditor=()=>showDialog("Import Jobs",node("p","粘贴岗位链接或选择CSV文件，补上JD和原始时间标签后预览。"),
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
  const screenshot=node("input",null,{type:"file",accept:"image/png,image/jpeg","aria-label":"可选岗位截图"});
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
  ],"保存岗位",async data=>{
    const file=screenshot.files[0];
    if(file&&file.size>350000)throw Error("请选择不超过 350 KB 的截图。");
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
      catch(error){result.analysis_error="岗位已保存，截图未保存："+error.message;}
    }
    view="My Imports";history.replaceState(null,"","#imports");await refresh();showImportResults([result]);
  });
  const picture=node("label","可选岗位截图（PNG/JPEG，不超过350 KB）");picture.append(screenshot);
  editor.insertBefore(picture,editor.lastElementChild);
  showDialog("手动补充／高级编辑",node("p","截图随岗位保存供核对。JD 不完整时选「待补全」。"),editor);
}

function pasteJD(job) {
  const common=field("完整职位描述","jd",{area:true,required:true,value:job?.jd?.startsWith("[Partial JD]")?"":job?.jd});
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
        button("更新已有岗位 · "+existing.title+" · "+existing.company,()=>save({...data,id:existing.id})));
      if(result.result==="review")choices.push(button("Save as a separate job",()=>save({...data,allow_similar:true})));
      showDialog("核对已有岗位",...choices);
      return;
    }
    if(!job)view="My Imports";
    await refresh();detail(result.id);
  }
  showDialog(job?"补充JD · "+job.title:"粘贴JD",
    node("p","Save the complete description. Eligibility will remain separate from material preparation."),
    form(fields,"Confirm complete JD and save",data=>save({...data,id:job?.id})));
}

function publicSearch() {
  const family=field("职业方向","family",{options:state.career_families});
  const market=field("地区","market",{options:["Canada","Vancouver","Greater Toronto Area","United States","UAE","Dubai","Abu Dhabi","Remote Canada","Remote UAE","Japan","Tokyo","Yokohama","UK"]});
  const channels={"LinkedIn 公开索引":"site:linkedin.com/jobs/view","Indeed":"site:indeed.com/viewjob",
    "行业招聘板":"(site:jobbank.gc.ca OR site:gulftalent.com OR site:bayt.com)",
    "招聘机构":"(site:roberthalf.com OR site:michaelpage.ae OR site:hays.ca)"};
  const links=box();
  const update=()=>{
    links.replaceChildren(...Object.entries(channels).map(([label,site])=>link(label,"https://www.google.com/search?q="+encodeURIComponent(family.lastElementChild.value+" "+market.lastElementChild.value+" "+site))));
    if(["Canada","Vancouver","Greater Toronto Area","Remote Canada"].includes(market.lastElementChild.value))links.append(link('Job Bank：全加拿大官方搜索（需导入）','https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring='+encodeURIComponent(family.lastElementChild.value)));
  };
  const presets=box();
  const updatePresets=()=>{
    const geo={"Canada":"101174742","Vancouver":"101226900","Greater Toronto Area":"100025096","UAE":"104305776",
      "Dubai":"106204383","Abu Dhabi":"104306859","Remote Canada":"101174742","Remote UAE":"104305776"};
    presets.replaceChildren(...[[86400,"过去 24 小时"],[604800,"过去 1 周"],[2592000,"过去 1 个月"]].map(([seconds,label])=>{
      const region=market.lastElementChild.value;
      const query=new URLSearchParams({keywords:family.lastElementChild.value,f_TPR:"r"+seconds});
      query.set(geo[region]?"geoId":"location",geo[region]||region);
      if(region.startsWith("Remote")) query.set("f_WT","2");
      return link("LinkedIn · "+label,"https://www.linkedin.com/jobs/search/?"+query);
    }));
  };
  for(const field of [family,market]) field.addEventListener("change",()=>{update();updatePresets();});
  update();updatePresets();
  return section("按方向和地区搜索公开结果",box(family,market),presets,links,node("p","先查 24 小时，再查一周补缺。把找到的链接或 JD 粘贴到 Import Jobs，按岗位 ID 去重。"));
}

function observeListing(job) {
  const urls=job.source_links.map(link=>link.url).filter(Boolean);
  return urls.length?button("记录页面读取和时间证据",()=>showDialog("记录页面观察",
    form([field("来源链接","url",{options:[...new Set(urls)]}),
      field("读取结果","state",{options:["Login required","Redirected","Summary only","Explicitly closed","Request failed","Unknown","Readable"]}),
      field("页面提示、跳转地址或其他实见证据","detail",{area:true,required:true}),
      field("平台原始时间标签","label"),field("实际查看时间（留空使用现在）","viewed",{type:"datetime-local"}),field("时间类型","kind",{options:["Displayed","Reposted"]})],
      "保存",async data=>{await api("/api/listing/observe",{id:job.id,...data,viewed:data.viewed?new Date(data.viewed).toISOString():""});await refresh();detail(job.id);}))):node("span");
}
document.querySelector("nav").addEventListener("click",e=>{if(state&&e.target.dataset.view)navigate(e.target.dataset.view);});
$("close").addEventListener("click",()=>dialog.close());
$("import").addEventListener("click",()=>{if(state)linkImport();});
action(async()=>{await refresh();const id=new URLSearchParams(location.hash.slice(1)).get("job");if(id)detail(id);});

async function letterView(job,doc){
 const data=await api('/api/material/'+doc.id),review=data.metadata?.cl_review||{};
 const copyState=node('p','',{role:'status'});
 const body=field('正式求职信正文','body',{area:true,value:data.body||data.text});
 const zh=node('details');zh.append(node('summary','中文对照（不进入正式申请文件）'),node('pre',(review.translation_zh||[]).join('\n\n')||'此版本尚无已审核中文对照。'));
 const proof=node('ul');for(const req of review.requirements||[])proof.append(node('li',
  ({Core:'核心',Preferred:'加分'}[req.priority]||req.priority)+' · '+req.requirement+' · '+
  ({Direct:'直接经验',Transferable:'可迁移经验','No evidence':'暂无证据'}[req.evidence_type]||req.evidence_type)+' · '+req.explanation+' · '+req.refs.join(', ')));
 const checks=node('details');checks.append(node('summary','审核记录（仍需本人审阅）'),node('pre',Object.entries(review.checks||{}).map(([k,v])=>({opening_match:'前三句匹配点',specific_evidence:'具体经历证据',scope_tools_numbers:'职责、地区、工具与数字',transferable_not_direct:'直接与可迁移经验',distinct_examples:'两段不同经历',no_flattery_or_company_guesses:'空话与公司推测',defensible_claims:'可解释的事实',length_and_page:'字数与页面'}[k]||k)+' · '+(v.passed?'已检查':'待处理')+' · '+v.note).join('\n')||'尚未执行新审核'));
 showDialog('求职信 · '+doc.id.slice(0,8),node('p',review.status||'历史版本 · 待核实'),
 node('p','生成时间 '+doc.created+' · 简历 '+(review.resume_sha256||doc.source_hash)+' · 关联CV '+(data.metadata?.paired_cv||'未关联特定CV')),
 form([body],'保存为新版本（原版本保留）',async values=>{await api('/api/manual/edit',{id:doc.id,text:values.body});await refresh();detail(job.id);}),
 button('审核并修订此版本（保留原文）',async()=>{
  showDialog('审核求职信',node('p','正在依据已确认事实审核并修订，完成后另存新版本。'));
  await api('/api/cl/review',{id:doc.id});await refresh();detail(job.id);
 }),
 button('复制正式正文',async()=>{
  const area=body.querySelector('textarea');area.focus();area.select();
  if(!document.execCommand('copy'))await navigator.clipboard.writeText(area.value);
  copyState.textContent='已复制正式正文（不含中文对照与审核说明）';
 }),copyState,
 link('预览PDF','/pdf/'+doc.id),link('下载PDF','/pdf/'+doc.id+'?download=1',true),zh,
 section('匹配依据',proof),section('影响写作的事实缺口',node('pre',(review.writing_gaps||[]).join('\n')||'未列出；仍需本人审阅。')),section('岗位要求待核实项',node('pre',(review.unverified||[]).join('\n')||(review.policy?'未列出影响写作的关键事实缺口；申请资格请另行核对。':'此历史版本尚未执行新版事实审核。'))),checks);
}

setInterval(async()=>{
 if(!state||busy)return;
 const running=state.jobs.filter(j=>j.generation?.state==='running');if(!running.length)return;
 const title=$('dialog-title').textContent;
 try{await refresh();const j=running.find(j=>j.title===title||title==='生成材料');if(j&&dialog.open)detail(j.id);}catch(e){notice('暂时无法读取后台任务状态；请刷新核对，不要重复提交生成。');}
},2500);

function coverageView(){
 const d=node('details');d.append(node('summary','实际来源覆盖与限制'));
 for(const platform of ['Greenhouse','Lever','Ashby']){
  const rows=Object.entries(state.source_health||{}).filter(([name])=>name.startsWith(platform+':'));
  d.append(node('p',platform+' · 雇主源 '+rows.length+' · 上轮读取成功 '+rows.filter(([,r])=>r.state==='Retrieved').length+' · 原始岗位 '+rows.reduce((sum,[,r])=>sum+(r.retrieved||0),0)),node('small',rows.map(([name,r])=>name+'：'+r.state).join('；')));
 }
 d.append(node('p','原始岗位数为招聘源整批数量，包含其他地区和较早岗位，不等于加拿大新增或72小时岗位数。'),node('p','LinkedIn / Indeed：登录搜索及导入渠道，未实现无人值守全站遍历。其他公司官网：仅已接入的公开来源或手动导入。全加拿大是地域范围，不是全市场覆盖承诺。'),node('p',`调度：${state.settings.schedule} ${state.settings.timezone}；服务每30秒检查。睡眠、关机或退出登录时不保证运行。恢复后仅有限补跑，不能补回历史市场快照。`));
 return d;
}

function myImports(){
 const latest=(a,b)=>(b.manual_import||b.first_seen).localeCompare(a.manual_import||a.first_seen);
 const manual=state.jobs.filter(job=>job.manual_import).sort(latest);
 const historical=state.jobs.filter(job=>job.legacy_import).sort(latest);
 const list=node("div");listJobs(manual,list);
 const old=node("details"),oldList=node("div");
 old.append(node("summary","历史手动或平台来源 · "+historical.length+" 条"),node("p","旧记录未统一标记导入方式。这里保留 Manual、LinkedIn 和 Indeed 来源的历史岗位，供你找回。"),oldList);
 listJobs(historical,oldList);
 content.append(box(button("导入岗位",()=>linkImport(),"primary"),button("查看全部岗位",()=>{tag="全部岗位";query="";navigate("Candidate Pool");})),list,old);
}

function importResultRow(result,url=""){
 const row=node("div");
 const job=state.jobs.find(j=>j.id===result.id);
 const saved=["added","duplicate","enriched","linked","saved"].includes(result.result);
 const names={duplicate:"已有记录 · 已保存至我导入的岗位",added:"已保存至我导入的岗位",enriched:"已补全并保存至我导入的岗位",linked:"已关联至我导入的岗位",saved:"已保存至我导入的岗位",
   unreadable:"读取失败，链接已保留",review:"存在相似岗位，请核对",conflict:"编号或链接匹配多条已有岗位，请核对",excluded:"根据现有行业规则排除",rejected:"未保存",changed:"记录已变化，请重新读取"};
 row.append(node("p",(names[result.result]||"未保存")+(job?" · "+job.title+" · "+job.company:"")));
 if(url)row.append(node("small",url));
 if(result.reason||result.industry?.reason&&!saved)row.append(node("p",result.reason||result.industry.reason));
 if(result.analysis_error)row.append(node("p",result.analysis_error));
 if(saved&&job?.industry.state==="review")row.append(node("p","行业待核实 · 评分仅反映简历与 JD 匹配，生成材料前请确认行业。"));
 if(saved&&job)row.append(node("p",job.match?.score!=null?"主简历 "+job.match.score+" 分 · "+job.date_signal.label:
   result.analysis_error||(!result.complete_jd?"JD 待补充，暂未评分":"待评分 · 请核对行业或岗位信息")));
 const actions=box();
 for(const id of result.ids||(result.id?[result.id]:[]))actions.append(button("查看岗位",()=>detail(id)));
 if(url&&(!saved||!result.complete_jd))actions.append(button("手动补充／高级编辑",()=>importJob(url,job)));
 if(actions.childElementCount)row.append(actions);
 return row;
}

function showImportResults(results){
 showDialog("导入结果",...results.map(r=>importResultRow(r)),button("查看我导入的岗位",()=>{dialog.close();navigate("My Imports");}));
}

function linkImport(){
 const input=field("岗位链接（每行一个）","urls",{area:true,value:localStorage.getItem("tracker-import-links")||""});
 const progress=node("p","",{role:"status"});
 const results=node("div"),advanced=node("details");
 advanced.append(node("summary","手动补充／高级编辑"),button("手动填写岗位",()=>importJob(input.lastElementChild.value.trim().split(/\s+/)[0])),
   button("CSV／JSON 或批量补充",()=>bulkImport()));
 input.lastElementChild.addEventListener("input",()=>localStorage.setItem("tracker-import-links",input.lastElementChild.value));
 const editor=form([input],"读取并导入",async data=>{
   const urls=[...new Set(data.urls.split(/\r?\n/).map(x=>x.trim()).filter(Boolean))];
   if(!urls.length||urls.length>20)throw Error("请每批粘贴 1 至 20 条链接。");
   localStorage.setItem("tracker-import-links",data.urls);
   results.replaceChildren();
   const failures=[];
   for(const [index,url] of urls.entries()){
     progress.textContent="正在读取 "+(index+1)+" / "+urls.length;
     let result;
     try{result=await api("/api/import/link",{url});}
     catch(error){result={result:"unreadable",reason:error.message};}
     if(["added","duplicate","enriched","linked"].includes(result.result)){view="My Imports";history.replaceState(null,"","#imports");await refresh();}
     else failures.push(url);
     results.append(importResultRow(result,url));
   }
   input.lastElementChild.value=failures.join("\n");
   localStorage.setItem("tracker-import-links",input.lastElementChild.value);
   progress.textContent="处理完成 "+urls.length+" 条 · "+failures.length+" 条待重试或补充";
 });
 showDialog("导入岗位",editor,progress,results,advanced,button("查看我导入的岗位",()=>{dialog.close();navigate("My Imports");}));
}

const assistedFields={
 identity:{name:"英文姓名",email:"邮箱",phone:"电话",city:"城市",address:"街道地址",postal:"邮政编码",education:"教育经历",gender:"性别（可选）",ethnicity:"族裔（可选）"},
 answers:{work_authorization:"已有工作许可",sponsorship:"需要雇主赞助",salary:"期望薪资（注明币种、月薪或年薪）",available:"可入职日期",locations:"可接受地点（逗号分隔；空白表示不限制）"}
};
const assistedLabels={
 Discovered:"已发现",Reviewed:"已预审","Materials ready":"材料就绪","Assisted filling":"填写中",
 "Awaiting my confirmation":"待我最终确认",Submitted:"已点提交","Receipt verified":"回执已核实",
 "Submission unverified":"提交结果待核实",Blocked:"受阻"
};
const assistedNotice="将在我的已登录浏览器中填写真实申请，最终提交前由我确认";
function assistedProfile(pane){
 return async()=>{
  const profile=await api("/api/assisted/profile");
  const region=field("国家／地区","country",{options:state.markets}), editor=node("div");
  const update=()=>{
   const country=region.lastElementChild.value, saved=profile.countries[country]||{};
   const inputs=(fields,values,prefix)=>Object.entries(fields).map(([key,title])=>field(title,prefix+key,
    {value:values[key]||"",type:key==="available"?"date":key==="email"?"email":"text",
     options:["work_authorization","sponsorship"].includes(key)?["","Yes","No"]:null,area:key==="education"}));
   editor.replaceChildren(form([...inputs(assistedFields.identity,profile.identity,"i_"),...inputs(assistedFields.answers,saved,"a_"),
     field("我确认以上资料真实准确","confirmed",{type:"checkbox",required:true})],"保存申请资料",async values=>{
     const take=(fields,prefix)=>Object.fromEntries(Object.keys(fields).map(k=>[k,values[prefix+k]]));
     await api("/api/assisted/profile",{country,identity:take(assistedFields.identity,"i_"),answers:take(assistedFields.answers,"a_"),confirmed:values.confirmed==="on"});
     dialog.close();await assistedPanel(pane);
   }));
  };
  region.addEventListener("change",update);update();
  showDialog("Application Profile",node("p","资料仅存本机。每个岗位发送前复核实际字段、材料和法律声明；可选敏感字段可留空。"+(profile.draft?"以下旧资料是草稿，保存前请逐项核对。":"")),region,editor);
 };
}
async function assistedPanel(pane){
 const result=await api("/api/assisted");
 const refreshPanel=async()=>{dialog.close();await assistedPanel(pane);};
 const send=async(row,action,data={})=>{await api("/api/assisted/action",{id:row.id,action,...data});await refreshPanel();};
 const evidenceForm=(row,requeue=false)=>showDialog(requeue?"核实未投并重新排队":"人工核实成功回执",node("p","仅凭独立证据更新状态。邮件未找到或缺少回执不能证明未投。"),
   form([...(requeue?[field("未投证据类型","proof_kind",{options:["Platform rejected","Employer confirmed no application","Platform confirms no application"]})]:[field("回执类型","proof_kind",{options:["Success page","Application number","Confirmation email"]}),
    field("实际投递时间（UTC时间）","submitted_at",{type:"datetime-local",required:!row.attempt.submitted}),
    ...(["CV","CL"].map(kind=>field("实际使用的 "+kind+" 版本（未知可留空）",kind.toLowerCase(),
      {options:["",...new Set((state.jobs.find(j=>j.id===row.id)?.documents||[]).filter(d=>d.kind===kind).map(d=>d.id))]})))]),
    field("证据文字或回执编号","proof",{area:true,required:true}),field("我已核实上述证据","confirmed",{type:"checkbox",required:true})],
    requeue?"确认未投并重新排队":"保存已核实回执",async v=>send(row,requeue?"requeue":"receipt",
    {...v,submitted_at:v.submitted_at?v.submitted_at+utcOffset(v.submitted_at):null,confirmed:v.confirmed==="on"})));
 const precheck=row=>{
   const p=row.attempt.payload?.precheck||{};
   showDialog("该岗位的附加答案",form([field("岗位专属薪资（注明币种与周期）","salary",{value:p.salary}),
     field("我授权此岗位使用已保存的街道地址和邮编","address_authorized",{type:"checkbox"}),
     field("我已经在原浏览器页完成了验证","captcha_cleared",{type:"checkbox"}),
     field("我确认以上答案适用于此岗位","confirmed",{type:"checkbox",required:true})],
     "保存本岗位答案",v=>send(row,"precheck",Object.fromEntries(Object.entries(v).map(([k,x])=>[k,k==="salary"?x:x==="on"])))));
   for(const key of ["address_authorized","captcha_cleared"])if(p[key])dialogBody.querySelector('[name="'+key+'"]').checked=true;
 };
 const prepare=async row=>{
   const p=await api("/api/assisted/profile");
   const values={...p.identity,...p.countries[row.country]};
   const docLinks=Object.entries(row.documents).map(([kind,id])=>link("下载 "+kind+" · "+id.slice(0,8),"/pdf/"+id+"?download=1",true));
   showDialog("复核申请资料 · "+row.company,node("p",row.title+" · "+row.channel),node("p",assistedNotice),
    node("p","在目标页使用已核实资料、上传下面的岗位材料。遇必填未知、验证或法律条款时先记录；最终提交由你操作。"),
    node("pre",Object.entries(values).filter(([,v])=>v).map(([k,v])=>(assistedFields.identity[k]||assistedFields.answers[k]||k)+" · "+v).join("\n")),
    box(...docLinks),
    form([field("我已复核接收方、显示的资料及材料","reviewed",{type:"checkbox",required:true})],"在新标签打开申请",async v=>{
      const tab=window.open("about:blank","_blank");if(!tab)throw Error("浏览器拦截新标签。请允许本地 Tracker 打开新标签后重试。");
      tab.opener=null;
      try{const opened=await api("/api/assisted/action",{id:row.id,action:"open",reviewed:v.reviewed==="on"});tab.location.replace(opened.url);}
      catch(e){tab.close();throw e;}
      await refreshPanel();
    }));
 };
 const verifyActual=row=>showDialog("最终提交前复核",node("p","核对浏览器表单的实际资料、法律声明和上传文件。保存复核后，请在招聘网站亲自点提交。"),
   form([field("实际上传的 CV","cv",{options:Object.values({CV:row.attempt.payload.docs.CV}),required:true}),
     field("实际上传的 CL（没有上传则留空）","cl",{options:["",row.attempt.payload.docs.CL].filter(x=>x!=null)}),
     field("我已经复核实际资料、材料及声明","reviewed",{type:"checkbox",required:true})],
     "标记为待我最终确认",v=>send(row,"review",{docs:{CV:v.cv,...(v.cl?{CL:v.cl}:{})},reviewed:v.reviewed==="on"})));
 const block=row=>showDialog("记录岗位受阻",form([field("具体原因（验证码、登录、缺资料等）","reason",{area:true,required:true})],"记录受阻",v=>send(row,"blocked",v)));
 const rows=node("div"),filter=field("筛选队列","assisted_filter",{options:["全部","可进入 Assisted Apply","提交待核实","受阻","回执已核实"]});
 const showRows=()=>{
   const selection=filter.lastElementChild.value;
   const items=result.jobs.filter(r=>selection==="全部"||selection==="可进入 Assisted Apply"&&r.queue_ready||
      selection==="提交待核实"&&["Submitted","Submission unverified"].includes(r.stage)||
      selection==="受阻"&&r.stage==="Blocked"||selection==="回执已核实"&&r.stage==="Receipt verified");
   rows.replaceChildren(node("p","共 "+items.length+" 条 · 已按近期、分数、可投递性排序"));
   for(const row of items){
    const actions=box(), task=node("article",null,{class:"job"});
    if(row.url)actions.append(link(row.route==="Manual application required"?"打开官网（人工）":"打开原申请页",row.url));
    actions.append(button("查看岗位和材料",()=>detail(row.id)));
    if(row.queue_ready&&result.mode==="Assisted Apply"&&row.documents.CV)actions.append(button("复核并开启填写",()=>prepare(row),"primary"));
    if(!["Submitted","Submission unverified","Receipt verified","Assisted filling","Awaiting my confirmation"].includes(row.stage)){
     actions.append(button("本岗位附加答案",()=>precheck(row)));
     if(row.stage==="Blocked"&&row.attempt.stage==="Blocked")actions.append(button("阻断已解除，恢复",()=>showDialog("恢复该岗位",
       form([field("我已核实阻断解除","confirmed",{type:"checkbox",required:true})],"恢复",v=>send(row,"resume",{confirmed:v.confirmed==="on"})))));
     else actions.append(button("记录阻断",()=>block(row)));
    }
    if(row.stage==="Assisted filling")actions.append(button("填写完成，复核实际资料",()=>verifyActual(row)),button("记录阻断",()=>block(row)));
    if(row.stage==="Awaiting my confirmation")actions.append(button("我已在网站点击提交",()=>showDialog("记录点击提交",
      form([field("我确实已在招聘网站点击提交","confirmed",{type:"checkbox",required:true})],"记录点击",v=>send(row,"submitted",{confirmed:v.confirmed==="on"})))),button("记录阻断",()=>block(row)));
    if(["Submitted","Submission unverified"].includes(row.stage))actions.append(
     ...(row.url?[link("检查页面回执",row.url)]:[]),link("搜索确认邮件",row.search_mail),
     button("人工确认已投",()=>evidenceForm(row)),button("核实未投并重新排队",()=>evidenceForm(row,true)));
    task.append(node("h3",row.company+" · "+row.title),node("p",[row.country,row.location,row.score==null?"待评分":row.score+" 分",
       row.fresh?"72 小时内首次发布":"日期待核实或较早",row.channel,assistedLabels[row.stage]||row.stage].filter(Boolean).join(" · ")),
     ...(row.blockers.length?[node("p",row.blockers.join("；"))]:[]),
     ...(row.attempt.submitted?[node("p","记录提交时间 · "+row.attempt.submitted)]:[]),
     ...(row.receipt?[node("p","核实证据 · "+row.receipt)]:[]),actions);
    rows.append(task);
   }
 };
 filter.addEventListener("change",showRows);showRows();
 const modeBox=form([field("投递模式","mode",{options:["Dry Run","Assisted Apply"],value:result.mode}),
   field("我确认以上浏览器操作说明","ack",{type:"checkbox"})],"保存模式",async v=>{
    await api("/api/assisted/mode",{mode:v.mode,ack:v.ack==="on"});state.settings.assisted_apply_mode=v.mode;await assistedPanel(pane);
   });
 const c=result.counts;
 pane.replaceChildren(section("每日执行面板 · "+result.today,node("p","UTC时区。待确认、待核实和受阻为当前队列数量。只有已核实回执计入今日实际投递。"),
  metrics({"今天发现":c.discovered,"可进入队列":c.actionable,"已打开待确认":c.awaiting,"今日真实成功投递":c.submitted,"待核实":c.unverified,"被阻塞":c.blocked})),
  section("投递模式 · "+result.mode,node("p",assistedNotice),modeBox,
   box(button("编辑 Application Profile",assistedProfile(pane)),button("粘贴岗位链接",()=>linkImport()))),
  ...(result.backlog.length?[section("待补全岗位链接",...result.backlog.map(r=>box(link("打开岗位链接",r.url),node("span",r.reason),
     button("重试读取",async()=>{await api("/api/import/link",{url:r.url});await assistedPanel(pane);}),
     button("补全岗位",()=>importJob(r.url)))))]:[]),filter,rows);
}
function utcOffset(local){ return "+00:00"; }

setInterval(async()=>{
 if(!state||busy||view!=="Dashboard"||dialog.open||!state.cv_queue?.worker?.enabled)return;
 try{
   const next=await api("/api/cv-queue/status");
   if(JSON.stringify(next.counts)!==JSON.stringify(state.cv_queue.counts)||next.worker.enabled!==state.cv_queue.worker.enabled)await refresh();
 }catch(error){/* Keep the last rendered state; user refresh exposes connection errors. */}
},10000);
