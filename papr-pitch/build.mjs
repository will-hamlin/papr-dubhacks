export const slides = [
{bg:'#FFFFFF', title:'papr', items:[
['image','assets/papr-logo.png',72,140,646.2,203.4],
['agentic efficiency,\nacademic accuracy',84,376,700,115,46],
["Terrence Tao's weapon of choice,\nnow aimed at corporate finance.",84,535,1000,92,30],
['Max  /  Derek  /  Will',88,659,600,30,18,'Arial']],
notes:'Opening story: Max spent his summer doing AI alignment research at MIT. Derek spent his waiting on PO paperwork before he could continue his intern project. Will likes to pretend he is good at abstract math. We combined the domain experience with the technical experience. The tagline is humorous, not an endorsement.'},
{bg:'#BEDDFF',title:'The cost of waiting',items:[
['The cost of waiting',72,62,1120,80,62],
['2 days',72,196,590,160,134],
['Median time to issue a purchase order',80,372,550,72,28,'Arial'],
['Derek had a project to build.\nFirst, he had to wait on paperwork.',712,221,470,130,34],
['Requests sit in inboxes.\nMissing details trigger another round.\nThe reason for a decision gets buried.',712,402,475,150,26,'Arial'],
['Source: APQC, Open Standards Benchmarking, measure 110916 (accessed Oct. 2026).',80,624,1120,25,17,'Arial'],
['Cross-industry median, requisition received to PO released. Includes waiting time; not a manual-only benchmark.',80,654,1120,25,16,'Arial']],
notes:'The two-day median is independently verified at https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/average-days-issue-purchase-order . Sample: 1,250 companies. This is an industry PO cycle-time benchmark, not an estimate of papr speed, not a manual versus automated experiment. Inspiration and anecdote supplied by the team.'},
{bg:'#111F31',title:'Purchase orders, with a proof trail',items:[
['Purchase orders,\nwith a proof trail',72,60,1100,150,62],
['01',76,270,75,60,35,'Times New Roman','#BEDDFF'],['Ask naturally',170,268,440,45,32],['A request, company policy, and user context.',170,321,650,42,23,'Arial'],
['02',76,392,75,60,35,'Times New Roman','#BEDDFF'],['Authorize and formalize',170,389,680,45,32],['Turn requirements into explicit conditions.',170,443,650,42,23,'Arial'],
['03',76,514,75,60,35,'Times New Roman','#BEDDFF'],['Find the fit. Keep the reason.',170,511,720,45,32],['Search for products and record each decision.',170,565,760,42,23,'Arial'],
['Request\n+ policy\n+ evidence',930,274,290,160,35,'Times New Roman','#BEDDFF'],
['Decision\n+ proof trail',930,486,290,110,35,'Times New Roman','#BEDDFF']],
notes:'papr accepts natural-language purchase requests and configuration, authorizes the request, converts it into proof-compatible requirements and preferences, and sends a search agent to find suitable products. It records the requester and the reason for approval or denial. The current repo describes dashboard, company proxy, and an external SMT verifier/search service with human review modes. Do not claim that formal verification guarantees the truth of scraped product information.'},
{bg:'#FFFFFF',title:'One request, checked end to end',items:[
['One request, checked end to end',72,58,1140,80,57],
['“Find a laptop for at most $1,200 with at least 16 GB RAM.\nI’d prefer something lightweight.”',76,178,1130,108,34],
['REQUIREMENTS',80,338,480,30,18,'Arial'],
['Price ≤ $1,200\nRAM ≥ 16 GB\nVendor meets company policy',80,389,530,144,30],
['PREFERENCE',80,561,460,30,18,'Arial'],
['Lower weight ranks eligible options.',80,604,560,38,25,'Arial'],
['ILLUSTRATIVE DECISION',736,338,460,30,18,'Arial'],
['Candidate A qualifies',736,389,470,55,34],
['$1,149   /   16 GB   /   approved vendor',736,454,475,44,24,'Arial'],
['Record the requester, policy checks,\nand evidence behind the decision.',736,518,475,82,26,'Arial'],
['The proof depends on the encoded rules and evidence. Ambiguous criteria need clarification.',80,670,1120,26,17,'Arial']],
notes:'Illustrative request and candidate, not a measured product demo or real vendor offer. Explain the boundary: hard requirements gate eligibility; subjective preferences guide ranking. Formal verification checks encoded statements against supplied evidence. Uncertain product facts and ambiguous natural language need clarification or human review. The audit record makes the decision inspectable.'},
{bg:'#BEDDFF',title:'The same checks, beyond POs',items:[
['The same checks, beyond POs',72,58,1130,80,59],
['Potential applications',76,157,1100,42,25,'Arial'],
['Expenses & reimbursements',80,277,520,57,36],
['Check receipts against policy.\nExplain exceptions before payout.',80,350,520,90,27,'Arial'],
['Software renewals',720,277,490,57,36],
['Check budget, approved vendors,\nand renewal conditions.',720,350,490,90,27,'Arial'],
['Vendor onboarding',80,491,520,57,36],
['Track required documents and\nshow which checks remain open.',80,563,520,90,27,'Arial'],
['Regulated purchasing',720,491,490,57,36],
['Apply explicit controls and retain\nevidence for each approval.',720,563,490,90,27,'Arial']],
notes:'These are proposed extensions, not implemented capabilities or validated markets. Start wherever policy can be expressed explicitly and reliable evidence can be gathered. Keep human review for exceptions and uncertain interpretations. The shared mechanism is natural-language intake, policy checks, and an inspectable record.'},
{bg:'#FFFFFF',title:'A focused path to a business',items:[
['A focused path to a business',72,58,1130,80,60],
['Proposed go-to-market',76,153,1100,40,25,'Arial'],
['First customer',80,265,340,50,35],
['Finance teams with\nrepeat equipment requests\nand explicit buying policies.',80,340,350,140,27,'Arial'],
['First pilot',485,265,340,50,35],
['One department.\nOne purchase category.\nHuman review for exceptions.',485,340,340,140,27,'Arial'],
['Revenue model',892,265,330,50,35],
['Annual platform fee\nplus request volume.\nPaid setup for integrations.',892,340,325,140,27,'Arial'],
['Pilot scorecard',80,550,340,45,32],
['Approval time, reviewer minutes, exception rate, and audit completeness.',80,611,1120,50,27,'Arial']],
notes:'Business hypothesis: sell to finance and procurement leaders who own approval friction and audit preparation. Begin with a narrow, supervised workflow alongside existing purchasing systems. Recruit design partners, measure a baseline, and expand only after the pilot demonstrates value. Proposed differentiation is explicit policy checking plus decision evidence. No pricing, savings, revenue, traction, or market-size claims are asserted.'},
{bg:'#FFFFFF',title:'Thank you',items:[
['Thank you',76,62,1000,100,78],
['image','assets/papr-mark.png',942,70,220,154.1],
['image','assets/papr-logo.png',72,220,538.5,169.5],
['agentic efficiency,\nacademic accuracy',84,423,790,110,43],
['Max  /  Derek  /  Will',88,590,800,40,27,'Arial'],
['Looking for a finance team to pilot papr.',88,649,1080,38,27,'Arial']],
notes:'Close with the team story and invite a pilot partner. Built in less than 24 hours according to the team. Do not describe the prototype as proven at enterprise scale or claim that no competing solution exists. Thank the judges and open for questions.'}
];

export async function addBatch({presentation,input}) {
 for(let i=input.start;i<input.end;i++) {
  const d=slides[i],s=presentation.slides.add({width:1280,height:720});s.background.fill=d.bg;
  for(const a of d.items){
   if(a[0]==='image'){s.images.add({path:'C:/Users/willa/pbapo-uw/papr-pitch/'+a[1],position:{left:a[2],top:a[3],width:a[4],height:a[5]},fit:'contain',alt:'Original papr brand artwork'});continue;}
   const [text,x,y,w,h,size,font='Times New Roman',color=d.bg==='#111F31'?'#FFFFFF':'#111F31']=a;
   const q=s.shapes.add({name:'s'+(i+1)+'-'+d.items.indexOf(a),geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
   q.text=text;q.text.style={fontSize:size,typeface:font,color,autoFit:'none'};q.text.insets=0;
  }
  s.speakerNotes.text=d.notes;
 }
 return {count:presentation.slides.items.length};
}
