import fs from 'node:fs/promises';
import {slides as original} from './build.mjs';
const N='#111F31',B='#BEDDFF',W='#FFFFFF';
export const slides=[
{bg:W,title:'papr',items:[
 ['rect',992,0,288,720,B],
 ['PROOF-BASED PURCHASING',88,66,820,32,18,'Bahnschrift'],
 ['image','assets/papr-logo.svg',72,202,820,250.56],
 ["Terrence Tao's weapon of choice,\nnow aimed at corporate finance.",88,490,820,110,37],
 ['Max Prince  /  Derek Nester  /  Will Hamlin',88,651,820,30,20,'Bahnschrift'],
 ['image','assets/papr-mark.svg',1040,278,192,134.1],
 ['DUBHACKS 2026',1044,653,220,24,16,'Bahnschrift']
]},
{bg:N,title:'The paperwork has a cost',items:[
 ['The paperwork has a cost',76,63,1130,90,64],
 ['TIME',82,222,310,32,19,'Bahnschrift',B],
 ['2 days',76,278,340,104,87,'Times New Roman',B],
 ['[APQC]',82,392,310,30,19,'Bahnschrift',B,'https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/average-days-issue-purchase-order'],
 ['Median PO cycle time',82,455,320,80,30],
 ['Requisition to release.\nProjects wait on approvals.',82,561,325,88,25,'Bahnschrift'],
 ['rect',444,222,1,420,'#38516B'],
 ['COST',482,222,330,32,19,'Bahnschrift',B],
 ['$14–54+',476,287,355,100,76,'Times New Roman',B],
 ['[APQC]',482,392,310,30,19,'Bahnschrift',B,'https://www.apqc.org/resource-library/resource/how-efficient-your-procurement-process-benchmarks-reveal-wide-performance'],
 ['Cost to process one PO',482,455,330,80,30],
 ['Varies by organization.\nStaff effort adds up.',482,561,325,88,25,'Bahnschrift'],
 ['rect',844,222,1,420,'#38516B'],
 ['REWORK + RECORDS',882,222,330,32,19,'Bahnschrift',B],
 ['18.4%',876,278,350,104,87,'Times New Roman',B],
 ['[Ardent Partners]',882,392,330,30,19,'Bahnschrift',B,'https://payablesplace.ardentpartners.com/2026/01/state-of-epayables-part-nine-ap-benchmarks-and-best-in-class-performance/'],
 ['Invoices with an issue\nto resolve, 2025',882,455,330,80,30],
 ['An “exception”: missing PO,\nmismatched data, or another\nissue needing review.',882,555,330,112,23,'Bahnschrift']
]},
{bg:B,title:'An agent that shows its work',items:[
 ['An agent that shows its work',76,64,1135,90,60],
 ['OpenAI used formal verification for a Millennium Prize problem.\nWe’re tackling the harder problem: getting a PO approved.',82,160,1120,64,24,'Bahnschrift'],
 ['01 / FORMALIZE THE REQUEST',82,246,1050,32,19,'Bahnschrift'],
 ['H(x) = A ∧ B ∧ R ∧ V',78,294,755,88,59],
 ['A  requester authorized       B  within budget',84,390,735,42,25,'Bahnschrift'],
 ['R  required specs met          V  allowed vendor',84,430,735,42,25,'Bahnschrift'],
 ['S = {x : H(x)}',870,300,350,80,43],
 ['The eligible candidate set.\nEvery hard rule must hold.',872,390,345,85,25,'Bahnschrift'],
 ['rect',80,493,1120,2,N],
 ['02 / VERIFY WITH SMT',82,530,530,32,18,'Bahnschrift'],
 ['facts ⊢ H(x)',80,577,540,63,48],
 ['Check encoded rules against product evidence.',84,658,610,36,22,'Bahnschrift'],
 ['03 / SEARCH + RANK',730,530,480,32,18,'Bahnschrift'],
 ['x* ∈ argmax score(x)',726,577,490,63,43],
 ['Rank verified search results x ∈ S.',732,658,480,36,22,'Bahnschrift']
]},
{bg:W,title:'Every decision leaves a record',items:[
 ['Every decision leaves a record',76,60,1130,90,61],
 ['REQUEST',84,200,540,32,18,'Bahnschrift'],
 ['“A laptop ≤ $1,200.\nAt least 16 GB.\nPreferably light.”',80,248,550,160,41],
 ['CHECKED CANDIDATE',84,451,540,32,18,'Bahnschrift'],
 ['$1,149.  16 GB.\nCompany-approved vendor.',82,498,560,90,31],
 ['∴ eligible',80,613,550,70,50],
 ['rect',704,192,500,491,B],
 ['REQUEST / 001',736,219,280,37,22,'Bahnschrift'],
 ['ILLUSTRATIVE',1046,225,145,24,14,'Bahnschrift'],
 ['rect',736,274,436,1,N],
 ['WHO',736,300,125,30,17,'Bahnschrift'],['Derek',886,294,280,44,29],
 ['WHAT',736,363,125,30,17,'Bahnschrift'],['Laptop request',886,357,290,44,29],
 ['RESULT',736,426,125,30,17,'Bahnschrift'],['Eligible',886,420,280,44,29],
 ['WHY',736,489,125,30,17,'Bahnschrift'],['Budget, RAM, and\nvendor checks pass.',886,483,290,82,26],
 ['rect',736,581,436,1,N],
 ['Approvals and denials stay on record,\nwith submitter and proof-based reason.',738,608,440,62,22,'Bahnschrift']
]},
{bg:W,title:'The opportunity in procurement',items:[
 ['The opportunity in procurement',76,62,1030,90,60],
 ['PROCUREMENT SOFTWARE',82,170,370,28,18,'Bahnschrift'],
 ['$10.9B',78,205,370,78,65],
 ['[Grand View Research]',82,288,370,25,17,'Bahnschrift',N,'https://www.grandviewresearch.com/industry-analysis/procurement-software-market-report'],
 ['Global market, 2026 estimate',82,327,365,64,26],
 ['Broader than PO software alone.',82,390,370,25,18,'Bahnschrift'],
 ['rect',454,170,1,240,B],
 ['AGENT ADOPTION',494,170,325,28,18,'Bahnschrift'],
 ['40%',490,205,335,78,65],
 ['[McKinsey]',494,288,325,25,17,'Bahnschrift',N,'https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai'],
 ['Large firms scaling agents\nin at least one function',494,327,330,64,26],
 ['Firms with >$1B annual revenue.',494,390,335,25,18,'Bahnschrift'],
 ['rect',850,170,1,240,B],
 ['AI VALUE REALIZED',890,170,320,28,18,'Bahnschrift'],
 ['6%',886,205,325,78,65],
 ['[McKinsey]',890,288,320,25,17,'Bahnschrift',N,'https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai'],
 ['Respondents qualifying\nas AI high performers',890,327,320,64,26],
 ['≥5% EBIT impact + significant value',890,390,320,25,17,'Bahnschrift'],
 ['rect',0,442,1280,278,B],
 ['NEXT EXPANSION STEPS',82,464,1110,28,18,'Bahnschrift'],
 ['01 / Win finance teams',82,512,340,42,29],
 ['Start with routine IT purchases.\nSell faster approvals and\ntraceable decisions.',82,567,340,85,23,'Bahnschrift'],
 ['rect',454,512,1,180,'#8FABCA'],
 ['02 / Fit the workflow',494,512,340,42,29],
 ['Link ERP + supplier catalogs.\nKeep existing approval\ncontrols.',494,567,340,85,23,'Bahnschrift'],
 ['rect',850,512,1,180,'#8FABCA'],
 ['03 / Expand with proof',890,512,320,42,29],
 ['Add categories and teams.\nReuse verified rules and\ndecision records.',890,567,320,85,23,'Bahnschrift'],
]},
{bg:B,title:'Thank you',items:[
 ['Thank you.',78,62,960,90,64],
 ['image','assets/papr-logo.svg',70,210,650,198.63],
 ['rect',769,218,1,197,N],
 ['agentic efficiency,\nacademic accuracy',818,262,385,110,34],
 ['rect',0,539,1280,181,N],
 ['Bring us your next purchase order.',78,580,1120,64,44,'Times New Roman',W],
 ['Max Prince  /  Derek Nester  /  Will Hamlin',82,657,1110,28,20,'Bahnschrift',B]
]}

].map((s,i)=>({...s,notes:original[i>=4?i+1:i].notes}));

slides[1].notes='Industry benchmarks, not papr performance measurements. Time: APQC measure 110916, cross-industry median 2.0 days from requisition received to PO released, including waiting. https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/average-days-issue-purchase-order . Cost: APQC, How Efficient Is Your Procurement Process?, April 29, 2026, about $14 to more than $54 per purchase order across organizations. This is not a manual-only range and is not purchase value. https://www.apqc.org/resource-library/resource/how-efficient-your-procurement-process-benchmarks-reveal-wide-performance . Record-keeping: Ardent Partners, State of ePayables 2025, average invoice exception rate 18.4%, reported by Andrew Bartolini January 22, 2026. https://payablesplace.ardentpartners.com/2026/01/state-of-epayables-part-nine-ap-benchmarks-and-best-in-class-performance/ . This is a downstream AP metric, not a PO error rate. Exceptions have multiple causes; the deck does not attribute all of them to missing records. Retrieved October 18, 2026.';
slides[2].notes='Conceptual logic model, not a literal solver trace. Natural-language requests and company/user configuration become explicit predicates. For each candidate x, H(x) is the conjunction of authorization, budget, required specifications, and vendor-policy checks in the current context. S is the eligible set of discovered candidates. SMT verification checks the encoded conditions against supplied evidence. Preferences such as low weight guide ranking within S, not across every possible product on the web. argmax assumes a defined preference score and nonempty S; if no candidate qualifies, no candidate is selected. Ambiguous language and uncertain product facts need clarification or review. Formal proof guarantees only what follows from its modeled assumptions, not the independent truth of a vendor listing.';
slides[3].notes='Illustrative request, requester, and candidate values. Documentation is a core output of papr: keep all PO requests, the submitter, and the proof-based reason for approval or denial. The original request and resulting decision remain associated, so finance can understand what was asked and why it passed or failed. The sample shows eligibility under the encoded rules, not completion of a real purchase. Do not claim immutable logs, cryptographic signatures, automatic regulatory compliance, or fields beyond the demonstrated product story. Mention that denials are retained too, rather than keeping only successful purchases.';

slides[1].notes += ' An invoice exception is an issue that interrupts normal processing and needs resolution, such as missing PO information or data that does not match. Definition and examples: Ardent Partners, https://payablesplace.ardentpartners.com/2017/06/aps-need-speed-invoice-exception-handling/ and https://payablesplace.ardentpartners.com/2020/09/overcoming-traditional-challenges-in-ap-will-result-in-modern-success/ . The 18.4% remains the 2025 average invoice exception rate, not a rate of fraud or papr errors.';
slides[4].notes='Market context: Grand View Research, Procurement Software Market Size, Share & Trends Analysis Report, 2026-2033, estimates global procurement software revenue at USD 10.9 billion in 2026 (USD 10.1 billion in 2025). https://www.grandviewresearch.com/industry-analysis/procurement-software-market-report . This broad category includes sourcing, contracts, suppliers, spend analysis, and e-procurement. It is not a PO-only addressable market or purchasing transaction volume. AI adoption and value: McKinsey, The state of AI in 2026: On the road to ROI, August 25, 2026, survey of 1,719 participants across 97 countries, May 4-June 8, 2026. https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai . 40% of respondents at large organizations (annual revenue greater than USD 1 billion) report scaling AI agents in at least one function. 6% of all respondents qualify as AI high performers: they attribute at least 5% of EBIT (earnings before interest and taxes) to AI and describe AI value as significant. These are cross-industry respondent reports, not procurement-specific penetration or a comparison with papr. papr has no measured effectiveness or commercial traction benchmark yet. Sources rechecked October 18, 2026.';

slides[4].notes += ' Proposed expansion strategy, not achieved traction: enter through finance teams handling routine IT purchases. Position papr around faster approvals and traceable decisions, using a recurring purchasing workflow as the initial entry point. Next, build integrations with existing ERP and supplier catalogs while preserving approval controls; these integrations are planned, not claimed as built. Expand into more categories and teams within each customer, reusing encoded policies and decision records where applicable. This is the proposed route into the broad procurement-software category. The AI adoption and value statistics provide cross-industry context, not evidence of procurement-specific demand or papr effectiveness.';

slides[5].notes='Thank the audience and invite a finance team to pilot papr on its purchase-order workflow. Team: Max Prince, Derek Nester, and Will Hamlin. Keep the invitation open for questions and discussion; no deployment, customer, or measured-result claim is implied.';

slides[2].notes += ' OpenAI comparison: OpenAI, On the Navier–Stokes Millennium Prize Problem, September 8, 2026, describes AI agents producing a proof and subsequent Lean formalization and verification. https://openai.com/index/navier-stokes-solution/ . The comparison is to the broad pattern of AI work checked formally, not identical tools: OpenAI describes Lean, whereas this deck describes papr using SMT. This line does not claim an awarded Millennium Prize or equivalent mathematical difficulty. Retrieved October 18, 2026.';


const pilotTargets = {
 bg:N, title:'What if papr cuts the friction?', reveal:true,
 metricFrom:{'20 min':['2 days',87], '$10':['$14–54+',76], '≤10%':['18.4%',87]},
 items:[
  ['What if papr cuts the friction?',76,63,1030,90,62],
  ['TIME',82,222,310,32,19,'Bahnschrift',B],
  ['20 min',76,278,350,104,82,'Times New Roman',B],
  ['Pilot target',82,392,310,30,19,'Bahnschrift',B],
  ['Requisition to PO release',82,455,330,80,30],
  ['For routine, in-policy POs.\nElapsed time, including waits.',82,561,330,88,23,'Bahnschrift'],
  ['rect',444,222,1,420,'#38516B'],
  ['COST',482,222,330,32,19,'Bahnschrift',B],
  ['$10',476,278,355,104,87,'Times New Roman',B],
  ['Illustrative estimate / PO',482,392,330,30,19,'Bahnschrift',B],
  ['Labor + allocated costs',482,455,330,80,30],
  ['6 min labor × $60/hour\n+ $4 tools and overhead.',482,561,330,88,23,'Bahnschrift'],
  ['rect',844,222,1,420,'#38516B'],
  ['REWORK + RECORDS',882,222,330,32,19,'Bahnschrift',B],
  ['≤10%',876,278,350,104,87,'Times New Roman',B],
  ['Pilot hypothesis',882,392,330,30,19,'Bahnschrift',B],
  ['Invoice exception rate',882,455,330,80,30],
  ['Downstream target: invoices\nand receiving still affect it.',882,561,330,88,23,'Bahnschrift'],
  ['Hypothetical targets, not measured results. Benchmark populations and pilot scope differ.',82,677,1120,27,18,'Bahnschrift',B]
 ],
 notes:'Hypothetical pilot targets, not observed papr performance or statistically comparable before-and-after results. The prior slide uses cross-industry benchmark populations; this scenario concerns routine in-policy purchases handled through papr. Time: user-selected target of 20 minutes from requisition received to PO released, including waits, to validate in a matched pilot. Procurement is broader than PO processing, so do not call this total procurement lead time. Cost: illustrative fully allocated per-PO estimate of 6 minutes of human labor at an assumed loaded USD 60/hour (USD 6) plus USD 4 allocated technology and overhead cost = USD 10. The USD 4 allowance must cover applicable model/search services, platform fees, integration amortization, support, and other overhead without double counting; actual allocation and achieved throughput need measurement. This is not a vendor quote, measured unit cost, validated savings, or the pricing assumption on the opportunity slide. Exceptions: at most 10% is an aspirational pilot hypothesis for invoice exceptions, not a model prediction or a claim papr can control all accounts-payable outcomes. A proposed pilot would track the share of downstream invoices linked to papr-issued POs requiring exception handling and compare with a matched baseline using the same exception definition. Supplier invoice quality, receipt confirmation, matching, price changes and other downstream processes remain material. The 18.4% industry benchmark is not a measured baseline for those customers. No relative savings or improvement percentages should be claimed from this comparison.'
};
for (const item of slides[1].items) {
 if(item[0] === '[APQC]') item[0] = '[APQC] baseline';
 if(item[0] === '[Ardent Partners]') item[0] = '[Ardent Partners, 2025] baseline';
 if(item[0] === 'Invoices with an issue\nto resolve, 2025') item[0] = 'Invoices with an issue\nto resolve';
}
pilotTargets.title = 'The paperwork has a cost';
pilotTargets.metricFrom = {'20 min':['2 days',87], '$10':['$14–54+',76], '≤10%':['18.4%',87]};
pilotTargets.highlightWidths = {'20 min':246,'$10':114,'≤10%':208};
pilotTargets.items = slides[1].items.map(item => {
 const result = [...item];
 result[0] = ({'2 days':'20 min','$14–54+':'$10','18.4%':'≤10%'})[item[0]] || item[0];
 return result;
});
pilotTargets.citationNotes = {
 '[Projected time]':'20 minutes is the project team’s requested pilot target for elapsed time from requisition to PO release on routine, in-policy purchases. It is not a measured result or an external benchmark. Source: papr pitch planning, October 18, 2026.',
 '[Illustrative cost model]':'Illustrative estimate: 6 minutes of human work × an assumed loaded labor rate of $60/hour = $6; add an assumed $4 per PO for technology and allocated overhead = $10. Both inputs are unvalidated. The overhead allowance must cover applicable model/search services, platform fees, integration amortization, support, and other costs without double counting. Source: illustrative model developed for this deck, October 18, 2026.',
 '[Projected exception rate]':'The ≤10% invoice-exception figure is a proposed pilot hypothesis introduced for this deck, not a measured papr outcome, published study, or model prediction. Validate with a matched cohort of invoices linked to papr-issued POs. Vendor invoice quality and receiving processes also affect exceptions. Source: illustrative pilot hypothesis developed for this deck, October 18, 2026.'
};
pilotTargets.items = pilotTargets.items.filter(item => !['[APQC] baseline','[Ardent Partners, 2025] baseline'].includes(item[0]));
pilotTargets.items.push(['Projected figures based on preliminary estimates',82,677,1120,27,18,'Bahnschrift',B]);
pilotTargets.metricFrom['Projected figures based on preliminary estimates'] = ['',18];
pilotTargets.plainMetrics = ['Projected figures based on preliminary estimates'];
pilotTargets.notes += ' Citation provenance: ' + Object.entries(pilotTargets.citationNotes).map(([label,note])=>label+' '+note).join(' ');
const systemFlow = {
 bg:W, title:'How papr works',
 items:[
  ['How papr works',76,63,1030,90,64],
  ['rect',76,205,1124,48,N],
  ['Company + user rules guide authorization and verification',100,217,1076,28,21,'Bahnschrift',W],
  ['rect',76,292,248,232,B],
  ['1 / Request',96,315,208,40,28],
  ['Natural language:\n“Laptop under $1,200,\n16 GB, ideally light.”',96,383,208,105,21,'Bahnschrift'],
  ['→',330,382,38,55,36],
  ['rect',368,292,248,232,B],
  ['2 / Encode specs',388,315,208,40,28],
  ['Must: ≤ $1,200\nRAM ≥ 16 GB\nPrefer: low weight',388,383,208,105,21,'Bahnschrift'],
  ['→',622,382,38,55,36],
  ['rect',660,292,248,232,B],
  ['3 / Find + verify',680,315,208,40,28],
  ['Search products.\nVerify requirements.\nRank preferences.',680,383,208,105,21,'Bahnschrift'],
  ['→',914,382,38,55,36],
  ['rect',952,292,248,232,B],
  ['4 / Decide + log',972,315,208,40,28],
  ['Approve or deny.\nSave the request,\nsubmitter and reason.',972,383,208,105,21,'Bahnschrift'],
  ['Required specs determine eligibility. Preferences rank the eligible matches.',82,581,1118,40,25]
 ],
 notes:'Simplified overview with an illustrative laptop request: the user submits natural language plus company and user configuration. Authorization is checked before product search. papr translates the request into explicit required specifications and preferences: the example requires a price at most USD 1,200 and at least 16 GB RAM, while low weight is a preference. The agent searches for candidates and verifies encoded requirements against supplied evidence, ranking eligible discovered candidates by preferences. A formal check establishes consistency with the encoded conditions, not independent truth of vendor claims. Ambiguous specs require clarification. Failed authorization or unmet requirements can yield a denial without completing every stage shown. Both approvals and denials retain the request, submitter and proof-based reason. This diagram groups internal operations for presentation and does not claim a literal production trace.'
};
const repeatedPaperwork = {...slides[1],items:slides[1].items.map(item=>[...item])};
slides.splice(2,0,systemFlow,repeatedPaperwork,pilotTargets);

for (const slide of slides) {
 if (!slide.items.some(item => item[0] === 'image' && /papr-mark/.test(item[1]))) {
  slide.items.push(['image', slide.bg === N ? 'assets/papr-mark-white.svg' : 'assets/papr-mark.svg', 1120, 48, 84, 58.67]);
 }
}

export async function reviseBatch({presentation,input}){
 for(let i=input.start;i<input.end;i++){
  const d=slides[i],s=presentation.slides.getItem(i);
  s.shapes.deleteAll();for(const img of [...s.images.items])img.delete();s.background.fill=d.bg;
  for(let j=0;j<d.items.length;j++){
   const a=d.items[j],name='s'+(i+1)+'-'+j;
   if(a[0]==='image'){
    s.images.add({svg:await fs.readFile('C:/Users/willa/pbapo-uw/papr-pitch/'+a[1],'utf8'),name,position:{left:a[2],top:a[3],width:a[4],height:a[5]},fit:'contain',alt:'Original ITC Benguiat papr logo, vector outlines'});continue;
   }
   if(['rect','ellipse'].includes(a[0])){
    s.shapes.add({name,geometry:a[0],position:{left:a[1],top:a[2],width:a[3],height:a[4]},fill:a[5],line:{fill:'none',width:0}});continue;
   }
   const [text,x,y,w,h,size,font='Times New Roman',color=d.bg===N?W:N]=a;
   if(d.highlightWidths?.[text]) {
    const pad=text==='d'?4:8;
    s.shapes.add({name:name+'-highlight',geometry:'rect',position:{left:x-pad,top:y,width:d.highlightWidths[text]+pad*2,height:size*1.17},fill:B,line:{fill:'none',width:0}});
   }
   const q=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
   q.text=text;q.text.style={fontSize:size,typeface:font,color:d.highlightWidths?.[text]?N:color,autoFit:'none',insets:0};
  }
  s.speakerNotes.text=d.notes;
 }
 return {slides:presentation.slides.items.length};
}
