const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const { FaBrain, FaDatabase, FaFileContract, FaCheck, FaClock, FaWrench } = require("react-icons/fa");
const CFG = require("./config.js");
const MAN = require("./deck_manifest.json");

const C = {
  navy:"1A2332",darkNavy:"111A24",accent:"2E86AB",gold:"D4A843",
  white:"FFFFFF",offWhite:"F4F6F8",lightGrey:"E2E6EB",
  midGrey:"8A95A5",darkText:"1A2332",bodyText:"3D4A5C",
  cardBg:"FFFFFF",green:"2D8F4E",amber:"D4943A",red:"C0392B",
};
const F={head:"Georgia",body:"Calibri"};

async function iconPng(Ic,color){
  const svg=ReactDOMServer.renderToStaticMarkup(React.createElement(Ic,{color,size:"256"}));
  return "image/png;base64,"+(await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
const cSh=()=>({type:"outer",blur:6,offset:2,angle:135,color:"000000",opacity:0.08});
function card(s,p,x,y,w,h,fill){s.addShape(p.shapes.RECTANGLE,{x,y,w,h,fill:{color:fill||C.cardBg},shadow:cSh()});}
function foot(s,n){
  s.addText("STRATEGIES IN CREDIT  |  CONFIDENTIAL",{x:0.5,y:5.2,w:7,h:0.3,fontSize:8,fontFace:F.body,color:C.midGrey});
  s.addText(`${n}`,{x:9,y:5.2,w:0.5,h:0.3,fontSize:8,fontFace:F.body,color:C.midGrey,align:"right"});
}
function divSlide(p,title,sub){
  let s=p.addSlide();s.background={color:C.navy};
  s.addShape(p.shapes.RECTANGLE,{x:0.8,y:1.8,w:0.06,h:1.8,fill:{color:C.gold}});
  s.addText(title.toUpperCase(),{x:1.1,y:1.8,w:8,h:0.8,fontSize:32,fontFace:F.head,color:C.white,bold:true,charSpacing:3,margin:0});
  s.addText(sub,{x:1.1,y:2.6,w:7,h:0.8,fontSize:16,fontFace:F.body,color:C.midGrey,margin:0});
}

async function build(){
  let p=new pptxgen();p.layout="LAYOUT_16x9";p.author=CFG.contact.name;p.title="Strategies in Credit";
  const ico={db:await iconPng(FaDatabase,`#${C.accent}`),doc:await iconPng(FaFileContract,`#${C.accent}`),brain:await iconPng(FaBrain,`#${C.accent}`),
    check:await iconPng(FaCheck,`#${C.green}`),clock:await iconPng(FaClock,`#${C.amber}`),wrench:await iconPng(FaWrench,`#${C.midGrey}`)};
  const SP = MAN.spread_snapshot;

  // ═══════ S1: TITLE ═══════
  {let s=p.addSlide();s.background={color:C.darkNavy};
    s.addShape(p.shapes.RECTANGLE,{x:0,y:0,w:10,h:0.04,fill:{color:C.gold}});
    s.addText([
      {text:"OPPORTUNITIES IN",options:{breakLine:true,fontSize:32,fontFace:F.head,color:C.white,bold:true,charSpacing:4}},
      {text:"EUROPEAN MACRO CREDIT",options:{fontSize:32,fontFace:F.head,color:C.white,bold:true,charSpacing:4}},
    ],{x:0.8,y:1.1,w:8.4,h:1.3,margin:0});
    s.addText("European Credit & Correlation Trading",{x:0.8,y:2.5,w:8.4,h:0.5,fontSize:18,fontFace:F.body,color:C.midGrey,margin:0});
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:3.2,w:1.2,h:0.03,fill:{color:C.gold}});
    s.addText(CFG.contact.name,{x:0.8,y:3.5,w:8.4,h:0.45,fontSize:20,fontFace:F.head,color:C.white,margin:0});
    s.addText("28 Years  |  Bear Stearns · Barclays Capital · Bank of America",{x:0.8,y:3.95,w:8.4,h:0.35,fontSize:12,fontFace:F.body,color:C.midGrey,margin:0});
    const cl=CFG.client.name!=="Generic"?`Prepared for ${CFG.client.name}  |  CONFIDENTIAL`:"CONFIDENTIAL";
    s.addText(cl,{x:0.8,y:4.8,w:5,h:0.3,fontSize:9,fontFace:F.body,color:C.midGrey,charSpacing:2,margin:0});
    s.addText(MAN._LAST_UPDATED,{x:7,y:4.8,w:2.5,h:0.3,fontSize:9,fontFace:F.body,color:C.midGrey,align:"right",margin:0});
  }

  // ═══════ S2: HEADLINE ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,2);
    s.addText("THE OPPORTUNITY",{x:0.8,y:0.4,w:8,h:0.5,fontSize:12,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText(CFG.trackRecord.headline,{x:0.8,y:1.0,w:8.4,h:0.9,fontSize:18,fontFace:F.head,color:C.darkText,margin:0});
    const stats=[
      {n:CFG.trackRecord.avgAnnualPL,l:CFG.trackRecord.avgLabel,s:CFG.trackRecord.avgSub},
      {n:CFG.trackRecord.peakYearPL,l:CFG.trackRecord.peakLabel,s:CFG.trackRecord.peakSub},
      {n:CFG.trackRecord.sharpe,l:CFG.trackRecord.sharpeLabel,s:CFG.trackRecord.sharpeSub},
      {n:CFG.trackRecord.bookManaged,l:CFG.trackRecord.bookLabel,s:CFG.trackRecord.bookSub},
    ];
    stats.forEach((st,i)=>{const cx=0.8+i*2.27;
      card(s,p,cx,2.2,2.0,1.6,C.cardBg);
      s.addText(st.n,{x:cx+0.15,y:2.35,w:1.7,h:0.55,fontSize:28,fontFace:F.head,color:C.accent,bold:true,margin:0});
      s.addText(st.l,{x:cx+0.15,y:2.9,w:1.7,h:0.35,fontSize:11,fontFace:F.body,color:C.darkText,bold:true,margin:0});
      s.addText(st.s,{x:cx+0.15,y:3.2,w:1.7,h:0.3,fontSize:9,fontFace:F.body,color:C.midGrey,margin:0});
    });
    s.addText(CFG.trackRecord.bio,{x:0.8,y:4.1,w:8.4,h:0.8,fontSize:12,fontFace:F.body,color:C.bodyText,margin:0});
  }

  // ═══════ S3: MARKET SNAPSHOT — iTraxx SPREADS ═══════
  if(SP){
    let s=p.addSlide();s.background={color:C.offWhite};foot(s,3);
    s.addText("THE UNIVERSE WE MONITOR",{x:0.8,y:0.25,w:8,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText(`iTraxx Europe S44 — ${SP.main.count + SP.xover.count} names  |  Spreads as of ${SP.date}`,{x:0.8,y:0.55,w:8.4,h:0.35,fontSize:16,fontFace:F.head,color:C.darkText,bold:true,margin:0});

    // MAIN card
    card(s,p,0.8,1.1,4.0,2.0,C.cardBg);
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:1.1,w:4.0,h:0.4,fill:{color:C.accent}});
    s.addText(`iTraxx MAIN  —  ${SP.main.count} names`,{x:0.95,y:1.1,w:3.7,h:0.4,fontSize:11,fontFace:F.body,color:C.white,bold:true,valign:"middle",margin:0});

    // Main stats row
    const mStats=[{n:`${SP.main.avg_spread_bp}bp`,l:"Average"},{n:`${SP.main.median_spread_bp}bp`,l:"Median"},{n:`${SP.main.min_spread_bp}-${SP.main.max_spread_bp}bp`,l:"Range"}];
    mStats.forEach((ms,i)=>{
      s.addText(ms.n,{x:0.95+i*1.25,y:1.6,w:1.15,h:0.35,fontSize:16,fontFace:F.head,color:C.accent,bold:true,margin:0});
      s.addText(ms.l,{x:0.95+i*1.25,y:1.95,w:1.15,h:0.2,fontSize:9,fontFace:F.body,color:C.midGrey,margin:0});
    });

    // Main distribution bar
    const mDist=SP.main.distribution;
    const mTotal=SP.main.count;
    const mBuckets=[
      {label:"<30",count:mDist.under_30bp,color:"1B7A3D"},
      {label:"30-50",count:mDist["30_50bp"],color:"2D8F4E"},
      {label:"50-75",count:mDist["50_75bp"],color:C.accent},
      {label:"75-100",count:mDist["75_100bp"],color:C.amber},
      {label:"100-150",count:mDist["100_150bp"],color:"C0392B"},
      {label:">150",count:mDist.over_150bp,color:"8B1A1A"},
    ];
    let mBarX=0.95;
    const mBarW=3.7,mBarY=2.25,mBarH=0.25;
    mBuckets.forEach(b=>{
      const w=mBarW*(b.count/mTotal);
      if(w>0.01){
        s.addShape(p.shapes.RECTANGLE,{x:mBarX,y:mBarY,w:w,h:mBarH,fill:{color:b.color}});
        if(w>0.3) s.addText(`${b.count}`,{x:mBarX,y:mBarY,w:w,h:mBarH,fontSize:8,fontFace:F.body,color:C.white,align:"center",valign:"middle",margin:0});
      }
      mBarX+=w;
    });
    // Legend
    s.addText("← tighter                spread distribution (bp)                wider →",{x:0.95,y:2.55,w:3.7,h:0.2,fontSize:7,fontFace:F.body,color:C.midGrey,align:"center",margin:0});

    // Widest 5 main
    s.addText("Widest spreads:",{x:0.95,y:2.75,w:3.7,h:0.2,fontSize:9,fontFace:F.body,color:C.darkText,bold:true,margin:0});
    SP.main.widest_5.forEach((w,i)=>{
      s.addText(`${w.name}`,{x:0.95,y:2.95+i*0.18,w:2.5,h:0.18,fontSize:8,fontFace:F.body,color:C.bodyText,margin:0});
      s.addText(`${w.spread}bp`,{x:3.65,y:2.95+i*0.18,w:0.9,h:0.18,fontSize:8,fontFace:F.body,color:C.red,bold:true,align:"right",margin:0});
    });

    // XOVER card
    card(s,p,5.2,1.1,4.0,2.0,C.cardBg);
    s.addShape(p.shapes.RECTANGLE,{x:5.2,y:1.1,w:4.0,h:0.4,fill:{color:C.navy}});
    s.addText(`iTraxx CROSSOVER  —  ${SP.xover.count} names`,{x:5.35,y:1.1,w:3.7,h:0.4,fontSize:11,fontFace:F.body,color:C.gold,bold:true,valign:"middle",margin:0});

    const xStats=[{n:`${SP.xover.avg_spread_bp}bp`,l:"Average"},{n:`${SP.xover.median_spread_bp}bp`,l:"Median"},{n:`${SP.xover.min_spread_bp}-${SP.xover.max_spread_bp}bp`,l:"Range"}];
    xStats.forEach((xs,i)=>{
      s.addText(xs.n,{x:5.35+i*1.25,y:1.6,w:1.15,h:0.35,fontSize:16,fontFace:F.head,color:C.gold,bold:true,margin:0});
      s.addText(xs.l,{x:5.35+i*1.25,y:1.95,w:1.15,h:0.2,fontSize:9,fontFace:F.body,color:C.midGrey,margin:0});
    });

    // Xover distribution bar
    const xDist=SP.xover.distribution;
    const xTotal=SP.xover.count;
    const xBuckets=[
      {label:"<150",count:xDist.under_150bp,color:"2D8F4E"},
      {label:"150-250",count:xDist["150_250bp"],color:C.accent},
      {label:"250-400",count:xDist["250_400bp"],color:C.amber},
      {label:"400-600",count:xDist["400_600bp"],color:"C0392B"},
      {label:">600",count:xDist.over_600bp,color:"8B1A1A"},
    ];
    let xBarX=5.35;
    xBuckets.forEach(b=>{
      const w=3.7*(b.count/xTotal);
      if(w>0.01){
        s.addShape(p.shapes.RECTANGLE,{x:xBarX,y:2.25,w:w,h:0.25,fill:{color:b.color}});
        if(w>0.3) s.addText(`${b.count}`,{x:xBarX,y:2.25,w:w,h:0.25,fontSize:8,fontFace:F.body,color:C.white,align:"center",valign:"middle",margin:0});
      }
      xBarX+=w;
    });
    s.addText("← tighter                spread distribution (bp)                wider →",{x:5.35,y:2.55,w:3.7,h:0.2,fontSize:7,fontFace:F.body,color:C.midGrey,align:"center",margin:0});

    // Widest 5 xover
    s.addText("Widest spreads:",{x:5.35,y:2.75,w:3.7,h:0.2,fontSize:9,fontFace:F.body,color:C.darkText,bold:true,margin:0});
    SP.xover.widest_5.forEach((w,i)=>{
      const puf=w.pts_upfront?` (${w.pts_upfront}pts)`:"";
      s.addText(`${w.name}`,{x:5.35,y:2.95+i*0.18,w:2.5,h:0.18,fontSize:8,fontFace:F.body,color:C.bodyText,margin:0});
      s.addText(`${w.spread}bp${puf}`,{x:7.85,y:2.95+i*0.18,w:1.2,h:0.18,fontSize:8,fontFace:F.body,color:C.red,bold:true,align:"right",margin:0});
    });

    // Bottom insight
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:4.1,w:8.4,h:0.7,fill:{color:C.navy}});
    s.addText([
      {text:"Key observation: ",options:{color:C.gold,bold:true,breakLine:false}},
      {text:`Main average at ${SP.main.avg_spread_bp}bp with ${SP.main.distribution.over_150bp} names above 150bp — tight market with pockets of stress. Crossover has ${SP.xover.names_trading_upfront} names trading points upfront, indicating distressed pricing. These are the opportunities our monitoring system is designed to catch early.`,options:{color:C.offWhite}},
    ],{x:0.95,y:4.15,w:8.1,h:0.6,fontSize:9.5,fontFace:F.body,margin:0,lineSpacingMultiple:1.2});
  }

  // ═══════ S4: DIVIDER — PROCESS ═══════
  divSlide(p,"This Is My Process","Signal → Filter → Size → Execute → Manage → Exit");

  // ═══════ S5: PROCESS ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,5);
    s.addText("THE DAILY WORKFLOW",{x:0.8,y:0.35,w:8,h:0.4,fontSize:12,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText("Six steps, every day, no exceptions",{x:0.8,y:0.75,w:8,h:0.4,fontSize:22,fontFace:F.head,color:C.darkText,bold:true,margin:0});
    CFG.process.steps.forEach((st,i)=>{
      const r=Math.floor(i/3),c=i%3,cx=0.8+c*3,cy=1.35+r*1.95;
      card(s,p,cx,cy,2.75,1.7,C.cardBg);
      s.addShape(p.shapes.OVAL,{x:cx+0.15,y:cy+0.15,w:0.35,h:0.35,fill:{color:C.accent}});
      s.addText(`${i+1}`,{x:cx+0.15,y:cy+0.15,w:0.35,h:0.35,fontSize:12,fontFace:F.body,color:C.white,bold:true,align:"center",valign:"middle",margin:0});
      s.addText(st.title,{x:cx+0.6,y:cy+0.15,w:2,h:0.35,fontSize:12,fontFace:F.body,color:C.accent,bold:true,valign:"middle",margin:0,charSpacing:2});
      s.addText(st.desc,{x:cx+0.15,y:cy+0.6,w:2.45,h:0.95,fontSize:9.5,fontFace:F.body,color:C.bodyText,margin:0,lineSpacingMultiple:1.15});
    });
  }

  // ═══════ S6: TECH LIVE ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,6);
    s.addText("TECHNOLOGY — WHAT'S LIVE TODAY",{x:0.8,y:0.25,w:8,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText(`Monitoring ${MAN.system_status.companies_monitored} companies across ${MAN.system_status.index}`,{x:0.8,y:0.55,w:8,h:0.35,fontSize:18,fontFace:F.head,color:C.darkText,bold:true,margin:0});
    MAN.capabilities.live.forEach((cap,i)=>{
      const r=Math.floor(i/2),c=i%2,cx=0.8+c*4.4,cy=1.1+r*1.2;
      card(s,p,cx,cy,4.0,1.05,C.cardBg);
      s.addImage({data:ico.check,x:cx+0.12,y:cy+0.12,w:0.25,h:0.25});
      s.addText("LIVE",{x:cx+0.42,y:cy+0.12,w:0.5,h:0.25,fontSize:8,fontFace:F.body,color:C.green,bold:true,valign:"middle",margin:0});
      s.addText(`Since ${cap.since}`,{x:cx+2.5,y:cy+0.12,w:1.3,h:0.25,fontSize:8,fontFace:F.body,color:C.midGrey,align:"right",valign:"middle",margin:0});
      s.addText(cap.name,{x:cx+0.12,y:cy+0.4,w:3.76,h:0.25,fontSize:11,fontFace:F.body,color:C.darkText,bold:true,margin:0});
      s.addText(cap.detail||cap.description,{x:cx+0.12,y:cy+0.65,w:3.76,h:0.3,fontSize:9,fontFace:F.body,color:C.bodyText,margin:0});
    });
    const liveN=MAN.capabilities.live.length,ipN=MAN.capabilities.in_progress.length,totN=liveN+ipN+MAN.capabilities.future.length;
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:3.6,w:8.4,h:0.5,fill:{color:C.navy}});
    s.addText([{text:`${liveN} live`,options:{color:C.green,bold:true,breakLine:false}},{text:`  |  ${ipN} in development  |  ${totN} total planned`,options:{color:C.midGrey}}],
      {x:0.95,y:3.6,w:8.1,h:0.5,fontSize:11,fontFace:F.body,valign:"middle",margin:0});
    s.addText(`System state as of ${MAN._LAST_UPDATED}`,{x:0.8,y:4.2,w:8.4,h:0.3,fontSize:8,fontFace:F.body,color:C.midGrey,italic:true,margin:0});
  }

  // ═══════ S7: TECH PIPELINE ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,7);
    s.addText("TECHNOLOGY — BUILD PIPELINE",{x:0.8,y:0.25,w:8,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText("What's coming next — and the long-term vision",{x:0.8,y:0.55,w:8,h:0.35,fontSize:18,fontFace:F.head,color:C.darkText,bold:true,margin:0});

    // In development - left column
    s.addText("IN DEVELOPMENT",{x:0.8,y:1.0,w:4,h:0.25,fontSize:10,fontFace:F.body,color:C.amber,bold:true,charSpacing:2,margin:0});
    MAN.capabilities.in_progress.forEach((cap,i)=>{
      const cy=1.28+i*0.62;
      card(s,p,0.8,cy,5.5,0.52,C.cardBg);
      s.addImage({data:ico.clock,x:0.92,y:cy+0.1,w:0.2,h:0.2});
      s.addText(cap.name,{x:1.2,y:cy+0.02,w:2.2,h:0.25,fontSize:10,fontFace:F.body,color:C.darkText,bold:true,valign:"middle",margin:0});
      s.addText(cap.status,{x:3.4,y:cy+0.02,w:0.8,h:0.25,fontSize:8,fontFace:F.body,color:C.midGrey,italic:true,valign:"middle",margin:0});
      s.addText(cap.description,{x:1.2,y:cy+0.27,w:4.9,h:0.22,fontSize:8.5,fontFace:F.body,color:C.bodyText,valign:"middle",margin:0});
    });

    // Future roadmap - right column
    s.addText("FUTURE ROADMAP",{x:6.6,y:1.0,w:3,h:0.25,fontSize:10,fontFace:F.body,color:C.midGrey,bold:true,charSpacing:2,margin:0});
    MAN.capabilities.future.forEach((cap,i)=>{
      const cy=1.28+i*0.85;
      card(s,p,6.6,cy,2.6,0.72,C.cardBg);
      s.addImage({data:ico.wrench,x:6.72,y:cy+0.1,w:0.18,h:0.18});
      s.addText(cap.name,{x:6.98,y:cy+0.05,w:2.1,h:0.25,fontSize:10,fontFace:F.body,color:C.midGrey,bold:true,valign:"middle",margin:0});
      s.addText(cap.description,{x:6.72,y:cy+0.35,w:2.35,h:0.3,fontSize:8.5,fontFace:F.body,color:C.midGrey,valign:"top",margin:0});
    });
  }

  // ═══════ S8: DIVIDER — REPEATABLE ═══════
  divSlide(p,"Why It's Repeatable","Structural edges that persist across market cycles");

  // ═══════ S9: EDGES ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,9);
    s.addText("THREE STRUCTURAL EDGES",{x:0.8,y:0.35,w:8,h:0.4,fontSize:12,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText("Why this works — and keeps working",{x:0.8,y:0.75,w:8,h:0.4,fontSize:22,fontFace:F.head,color:C.darkText,bold:true,margin:0});
    CFG.edges.forEach((e,i)=>{const ey=1.35+i*1.35;
      card(s,p,0.8,ey,8.4,1.15,C.cardBg);
      s.addShape(p.shapes.RECTANGLE,{x:0.8,y:ey,w:0.6,h:1.15,fill:{color:C.navy}});
      s.addText(`0${i+1}`,{x:0.8,y:ey,w:0.6,h:1.15,fontSize:18,fontFace:F.head,color:C.gold,bold:true,align:"center",valign:"middle",margin:0});
      s.addText(e.title,{x:1.6,y:ey+0.08,w:7.4,h:0.3,fontSize:13,fontFace:F.body,color:C.darkText,bold:true,margin:0});
      s.addText(e.body,{x:1.6,y:ey+0.38,w:7.4,h:0.7,fontSize:9.5,fontFace:F.body,color:C.bodyText,margin:0,lineSpacingMultiple:1.15});
    });
  }

  // ═══════ S10: DIVIDER — ALPHA ═══════
  divSlide(p,"Why It Generates Alpha","Decomposing the edge: what's portable from sell-side to pod");

  // ═══════ S11: ALPHA ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,11);
    s.addText("ALPHA ATTRIBUTION",{x:0.8,y:0.35,w:8,h:0.4,fontSize:12,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText("What transfers to a pod — and what doesn't",{x:0.8,y:0.75,w:8,h:0.4,fontSize:22,fontFace:F.head,color:C.darkText,bold:true,margin:0});
    card(s,p,0.8,1.35,4.0,3.4,C.cardBg);
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:1.35,w:4.0,h:0.45,fill:{color:C.accent}});
    s.addText("PORTABLE ALPHA — What I Bring",{x:0.95,y:1.35,w:3.7,h:0.45,fontSize:11,fontFace:F.body,color:C.white,bold:true,valign:"middle",margin:0});
    s.addText(CFG.alpha.portable.map((t,i)=>[{text:`${i+1}. `,options:{bold:true,color:C.accent,breakLine:false}},{text:t,options:{breakLine:true}}]).flat(),
      {x:0.95,y:1.95,w:3.7,h:2.65,fontSize:9.5,fontFace:F.body,color:C.bodyText,margin:0,lineSpacingMultiple:1.2,paraSpaceAfter:4});
    card(s,p,5.1,1.35,4.1,3.4,C.cardBg);
    s.addShape(p.shapes.RECTANGLE,{x:5.1,y:1.35,w:4.1,h:0.45,fill:{color:C.navy}});
    s.addText("HONEST ABOUT — What Doesn't Transfer",{x:5.25,y:1.35,w:3.8,h:0.45,fontSize:11,fontFace:F.body,color:C.gold,bold:true,valign:"middle",margin:0});
    s.addText(CFG.alpha.notPortable.map((t,i)=>[{text:`${i+1}. `,options:{bold:true,color:C.gold,breakLine:false}},{text:t,options:{breakLine:true}}]).flat(),
      {x:5.25,y:1.95,w:3.8,h:2.65,fontSize:9.5,fontFace:F.body,color:C.bodyText,margin:0,lineSpacingMultiple:1.2,paraSpaceAfter:4});
    s.addText(CFG.alpha.portableEstimate,{x:0.8,y:4.85,w:8.4,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,italic:true,margin:0});
  }

  // ═══════ S12: TRADE EXAMPLE ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,12);
    s.addText("PROCESS IN ACTION",{x:0.8,y:0.35,w:8,h:0.4,fontSize:12,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText(CFG.tradeExample.title,{x:0.8,y:0.75,w:8,h:0.4,fontSize:22,fontFace:F.head,color:C.darkText,bold:true,margin:0});
    CFG.tradeExample.steps.forEach((ts,i)=>{const ey=1.3+i*0.65;
      s.addShape(p.shapes.RECTANGLE,{x:0.8,y:ey,w:1.0,h:0.5,fill:{color:C.navy}});
      s.addText(ts.step,{x:0.8,y:ey,w:1.0,h:0.5,fontSize:8,fontFace:F.body,color:C.gold,bold:true,align:"center",valign:"middle",margin:0,charSpacing:1});
      s.addText(ts.detail,{x:2.0,y:ey,w:7.2,h:0.5,fontSize:9.5,fontFace:F.body,color:C.bodyText,valign:"middle",margin:0});
      if(i<CFG.tradeExample.steps.length-1) s.addShape(p.shapes.RECTANGLE,{x:1.28,y:ey+0.5,w:0.03,h:0.15,fill:{color:C.midGrey}});
    });
  }

  // ═══════ S13: DIVIDER — RISK ═══════
  divSlide(p,"Risk Framework","How I think about risk — and the tools that gate the worst case");

  // ═══════ S14: RISK ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,14);
    s.addText("RISK ARCHITECTURE",{x:0.8,y:0.25,w:8,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText("Hard limits, scenario tools, and worst-case gating",{x:0.8,y:0.55,w:8,h:0.35,fontSize:18,fontFace:F.head,color:C.darkText,bold:true,margin:0});
    const hdr=[[
      {text:"Parameter",options:{fill:{color:C.navy},color:C.white,bold:true,fontSize:10,fontFace:F.body,align:"left"}},
      {text:"Limit",options:{fill:{color:C.navy},color:C.white,bold:true,fontSize:10,fontFace:F.body,align:"center"}},
      {text:"Action",options:{fill:{color:C.navy},color:C.white,bold:true,fontSize:10,fontFace:F.body,align:"left"}},
    ]];
    const rows=CFG.risk.limits.map((r,i)=>{const bg=i%2===0?C.offWhite:C.white;return[
      {text:r.param,options:{fill:{color:bg},fontSize:9.5,fontFace:F.body,color:C.darkText}},
      {text:r.limit,options:{fill:{color:bg},fontSize:9.5,fontFace:F.body,color:C.accent,bold:true,align:"center"}},
      {text:r.action,options:{fill:{color:bg},fontSize:9.5,fontFace:F.body,color:C.bodyText}},
    ];});
    s.addTable([...hdr,...rows],{x:0.8,y:1.0,w:8.4,colW:[2.2,1.4,4.8],border:{pt:0.5,color:C.lightGrey},rowH:[0.35,0.35,0.35,0.35,0.35,0.35,0.35]});
    s.addText("SCENARIO TOOLS",{x:0.8,y:3.65,w:8,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,charSpacing:2,margin:0});
    CFG.risk.scenarios.forEach((sc,i)=>{const cx=0.8+i*2.87;
      card(s,p,cx,4.0,2.65,1.15,C.navy);
      s.addText(sc.title,{x:cx+0.15,y:4.05,w:2.35,h:0.3,fontSize:10,fontFace:F.body,color:C.gold,bold:true,margin:0});
      s.addText(sc.desc,{x:cx+0.15,y:4.35,w:2.35,h:0.7,fontSize:8.5,fontFace:F.body,color:C.offWhite,margin:0,lineSpacingMultiple:1.15});
    });
  }

  // ═══════ S15: 30/60/90 DAY PLAN ═══════
  {let s=p.addSlide();s.background={color:C.offWhite};foot(s,15);
    s.addText("ONBOARDING PLAN",{x:0.8,y:0.25,w:8,h:0.3,fontSize:11,fontFace:F.body,color:C.accent,bold:true,charSpacing:3,margin:0});
    s.addText("First 90 days — from allocation to full deployment",{x:0.8,y:0.55,w:8.4,h:0.35,fontSize:18,fontFace:F.head,color:C.darkText,bold:true,margin:0});

    // Three columns: 30 / 60 / 90
    const phases = [
      {
        label: "DAYS 1–30", subtitle: "Setup & Calibrate",
        color: C.accent,
        items: [
          "Connect to platform risk systems, reporting, and trade execution",
          "Deploy monitoring system on platform infrastructure",
          "Establish index tranche and single-name CDS trading lines",
          "Paper trade 5-10 positions to calibrate sizing to platform risk limits",
          "Daily risk reporting from day one — no exceptions",
          "Target: 20-30% of risk budget deployed by day 30",
        ]
      },
      {
        label: "DAYS 31–60", subtitle: "Build Positions",
        color: C.gold,
        items: [
          "Scale to 50-60% of risk budget based on opportunity set",
          "First live tranche trades — start with liquid on-the-run maturities",
          "Integrate documentation analysis into daily workflow",
          "Establish relationships with 3-5 dealer counterparts for pricing",
          "Weekly P&L review with risk committee",
          "Target: generating measurable alpha, Sharpe tracking >1.5",
        ]
      },
      {
        label: "DAYS 61–90", subtitle: "Full Deployment",
        color: C.navy,
        items: [
          "Full risk budget deployed across index, tranche, and single-name",
          "All three technology tools integrated and producing daily signals",
          "Established rhythm: morning briefing, intraday management, EOD attribution",
          "Cross-asset overlay active — equity options on credit catalyst names",
          "Full scenario analysis running daily against live portfolio",
          "Target: steady-state operation, Sharpe >2.0, max drawdown <2%",
        ]
      },
    ];

    const colW = 2.75, colGap = 0.22;
    phases.forEach((ph, i) => {
      const cx = 0.8 + i * (colW + colGap);

      // Header bar
      s.addShape(p.shapes.RECTANGLE, {x: cx, y: 1.1, w: colW, h: 0.45, fill: {color: ph.color}});
      s.addText(ph.label, {x: cx + 0.12, y: 1.1, w: colW - 0.24, h: 0.25, fontSize: 11, fontFace: F.body, color: C.white, bold: true, valign: "middle", margin: 0, charSpacing: 1});
      s.addText(ph.subtitle, {x: cx + 0.12, y: 1.32, w: colW - 0.24, h: 0.2, fontSize: 9, fontFace: F.body, color: C.white, italic: true, valign: "middle", margin: 0});

      // Content card
      card(s, p, cx, 1.6, colW, 3.3, C.cardBg);

      // Items
      const itemText = ph.items.map((item, j) => {
        const isTarget = item.startsWith("Target:");
        return [
          {text: isTarget ? "→ " : "• ", options: {bold: true, color: isTarget ? ph.color : C.midGrey, breakLine: false, fontSize: 9}},
          {text: item, options: {breakLine: true, fontSize: 9, bold: isTarget, color: isTarget ? ph.color : C.bodyText}},
        ];
      }).flat();

      s.addText(itemText, {x: cx + 0.12, y: 1.7, w: colW - 0.24, h: 3.1, fontFace: F.body, color: C.bodyText, margin: 0, lineSpacingMultiple: 1.15, paraSpaceAfter: 5});
    });
  }

  // ═══════ S16: THE ASK ═══════
  {let s=p.addSlide();s.background={color:C.navy};
    s.addShape(p.shapes.RECTANGLE,{x:0,y:0,w:10,h:0.04,fill:{color:C.gold}});
    s.addText("THE ASK",{x:0.8,y:0.5,w:8,h:0.4,fontSize:12,fontFace:F.body,color:C.gold,bold:true,charSpacing:3,margin:0});
    s.addText(`${CFG.client.capitalAsk} capital allocation`,{x:0.8,y:1.1,w:8.4,h:0.7,fontSize:32,fontFace:F.head,color:C.white,bold:true,margin:0});
    s.addText("Solo PM + proprietary technology stack",{x:0.8,y:1.8,w:8.4,h:0.4,fontSize:16,fontFace:F.body,color:C.midGrey,margin:0});
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:2.5,w:1.2,h:0.03,fill:{color:C.gold}});
    s.addText(CFG.client.platformFit.map(t=>[{text:"→  ",options:{color:C.gold,bold:true,breakLine:false}},{text:t,options:{color:C.white,breakLine:true}}]).flat(),
      {x:0.8,y:2.8,w:8.4,h:1.8,fontSize:13,fontFace:F.body,margin:0,paraSpaceAfter:6});
    s.addShape(p.shapes.RECTANGLE,{x:0.8,y:4.6,w:8.4,h:0.03,fill:{color:C.gold,transparency:50}});
    s.addText(`${CFG.contact.name}  |  ${CFG.contact.email}  |  ${CFG.contact.phone}`,{x:0.8,y:4.8,w:8.4,h:0.3,fontSize:11,fontFace:F.body,color:C.midGrey,margin:0});
  }

  await p.writeFile({fileName:"/home/claude/strategies_in_credit.pptx"});
  console.log(`Done: strategies_in_credit.pptx | ${MAN.capabilities.live.length} live, ${MAN.capabilities.in_progress.length} building | Spreads: Main avg ${SP.main.avg_spread_bp}bp, Xover avg ${SP.xover.avg_spread_bp}bp`);
}

build().catch(e=>{console.error(e);process.exit(1);});
