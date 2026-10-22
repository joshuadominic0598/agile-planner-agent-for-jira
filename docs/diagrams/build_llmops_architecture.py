"""Generate the second, service-and-arrow architecture view without changing the lifecycle diagram."""
from pathlib import Path
import base64
import html
from urllib.parse import quote
import xml.etree.ElementTree as ET

ET.register_namespace('', 'http://www.w3.org/2000/svg')

ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / 'resources/images/icons'
W, H = 3000, 2020
BG, GROUP, BOX = '#080F1F', '#0C1729', '#122038'
WHITE, TEXT, MUTED = '#F2F7FF', '#C2D0E4', '#859CBC'
BLUE, GREEN, PURPLE, AMBER = '#62CFFF', '#69DDC1', '#B5A0FF', '#F3BB6A'
parts, text_bounds = [], []
mx = ET.Element('mxfile', host='app.diagrams.net', version='24.7.17')
diagram = ET.SubElement(mx, 'diagram', name='Services and LLMOps', id='services-and-llmops')
model = ET.SubElement(diagram, 'mxGraphModel', page='1', pageScale='1',
                      pageWidth=str(W), pageHeight=str(H), background=BG, grid='1', gridSize='10')
root = ET.SubElement(model, 'root')
ET.SubElement(root, 'mxCell', id='0')
ET.SubElement(root, 'mxCell', id='1', parent='0')
seq = 1


def vertex(x,y,w,h,style,value=''):
    global seq
    seq += 1
    c = ET.SubElement(root,'mxCell',id=str(seq),parent='1',vertex='1',style=style,value=value)
    ET.SubElement(c,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),**{'as':'geometry'})


def box(x,y,w,h,stroke='#2C4464',fill=BOX,r=12,dash=False,sw=1.8):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"' + (' stroke-dasharray="9 7"' if dash else '') + '/>')
    vertex(x,y,w,h,f'rounded={int(r>0)};absoluteArcSize=1;arcSize={r};fillColor={fill};strokeColor={stroke};strokeWidth={sw};dashed={int(dash)};')


def txt(x,y,value,size=22,color=TEXT,bold=False,anchor='start',max_width=None):
    index=len(text_bounds)
    parts.append(f'<text data-check="{index}" x="{x}" y="{y}" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{anchor}">{html.escape(value)}</text>')
    text_bounds.append({'text':value,'maxWidth':max_width})
    width=max(80,len(value)*size*.65)
    pos=x if anchor=='start' else x-width if anchor=='end' else x-width/2
    align={'start':'left','end':'right','middle':'center'}[anchor]
    vertex(pos,y-size*.94,width,size*1.35,f'text;html=0;strokeColor=none;fillColor=none;whiteSpace=nowrap;overflow=visible;spacing=0;fontFamily=Arial;fontSize={size};fontColor={color};fontStyle={int(bold)};align={align};verticalAlign=top;',value)


def arrow(points,color=BLUE,label=None,label_at=None,dashed=False):
    coords=' '.join(f'{x},{y}' for x,y in points)
    parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round" marker-end="url(#a{color[1:]})"' + (' stroke-dasharray="10 8"' if dashed else '') + '/>')
    global seq
    seq+=1
    c=ET.SubElement(root,'mxCell',id=str(seq),edge='1',parent='1',style=f'edgeStyle=none;rounded=1;strokeColor={color};strokeWidth=2.6;endArrow=block;endFill=1;dashed={int(dashed)};')
    geo=ET.SubElement(c,'mxGeometry',relative='1',**{'as':'geometry'})
    for at,p in [('sourcePoint',points[0]),('targetPoint',points[-1])]:
        ET.SubElement(geo,'mxPoint',x=str(p[0]),y=str(p[1]),**{'as':at})
    if len(points)>2:
        arr=ET.SubElement(geo,'Array',**{'as':'points'})
        for x,y in points[1:-1]:ET.SubElement(arr,'mxPoint',x=str(x),y=str(y))
    if label:
        txt(*label_at,label,17,color,anchor='middle')


def logo(name,x,y,size=56,color=None):
    path=ICONS/f'{name}.svg'
    if not path.exists():
        raise FileNotFoundError(f'Missing technology icon: {path}')
    data=path.read_text()
    svg=ET.fromstring(data)
    # Monochrome logos need a light foreground on the dark canvas.
    if color:
        svg.set('fill',color)
        for node in svg.iter():
            if node.tag.endswith('path') and node.get('fill')!='none':node.set('fill',color)
    svg.set('x',str(x));svg.set('y',str(y));svg.set('width',str(size));svg.set('height',str(size))
    inline=ET.tostring(svg,encoding='unicode')
    parts.append(inline)
    svg.attrib.pop('x',None);svg.attrib.pop('y',None)
    image=quote(ET.tostring(svg,encoding='unicode'),safe='')
    vertex(x,y,size,size,f'shape=image;imageAspect=1;aspect=fixed;image=data:image/svg+xml,{image};strokeColor=none;fillColor=none;')


def symbol(kind,x,y,size=52,color=BLUE):
    # Generic service icons, intentionally distinct from the technology logos.
    paths={
        'user':'M12 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M3 22v-4c0-4 18-4 18 0v4 M3 22h18',
        'prompt':'M4 2h12l4 4v16H4Z M8 8h4 M8 12h8 M8 16h8',
        'golden':'M3 3h18v18H3Z M7 8h10 M7 12h6 M7 16h10',
        'test':'M8 2h8 M10 2v7L3 20q0 2 2 2h14q2 0 2-2L14 9V2 M7 15h10',
        'review':'M5 3h14v18H5Z M8 12l3 3 6-7',
        'chart':'M3 2v19h19 M6 15l5-6 4 3 6-9',
        'calculator':'M5 2h14v20H5Z M8 6h8 M8 11h1 M15 11h1 M8 15h1 M15 15h1 M8 19h1 M15 19h1',
        'network':'M8 5h8v14H8Z M2 5h3 M2 12h3 M2 19h3 M19 5h3 M19 12h3 M19 19h3 M11 8h2 M11 12h2 M11 16h2',
    }
    markup=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{paths[kind]}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    encoded=base64.b64encode(markup.encode()).decode()
    parts.append(f'<image href="data:image/svg+xml;base64,{encoded}" x="{x}" y="{y}" width="{size}" height="{size}"/>')
    vertex(x,y,size,size,f'shape=image;imageAspect=1;aspect=fixed;image=data:image/svg+xml,{quote(markup,safe="")};strokeColor=none;fillColor=none;')


def node(x,y,w,h,title,lines,brand=None,kind=None,color=BLUE,title_size=30):
    box(x,y,w,h,stroke='#34516F')
    if brand:logo(brand,x+25,y+26,58,color=WHITE if brand in {'ollama','openai','langfuse'} else None)
    elif kind:symbol(kind,x+25,y+27,52,color)
    txt(x+102,y+66,title,title_size,WHITE,True,max_width=w-127)
    for i,line in enumerate(lines):txt(x+26,y+124+i*35,line,22,TEXT,max_width=w-52)


box(0,0,W,H,fill=BG,stroke=BG,r=0,sw=0)
txt(80,62,'SERVICES  /  MODELS  /  TOOL CALLS  /  FEEDBACK',17,MUTED,True)
txt(80,143,'Agile Planner - LLMOps Architecture',63,WHITE,True)
box(2400,85,500,81,fill=GROUP)
logo('docker',2421,98,56)
txt(2493,132,'Docker Compose · local workspace',22,TEXT,True,max_width=380)

box(70,215,2860,340,stroke='#203A54',fill=GROUP,r=16)
txt(100,251,'01  DATA INGESTION & RETRIEVAL',18,BLUE,True)
node(100,295,400,205,'Jira export',['Ticket CSV snapshot','Issues · comments · references'],brand='jira')
node(640,295,420,205,'CSV ingestion',['Validate + normalize','Preserve original field values'],brand='python')
node(1200,295,440,205,'MongoDB',['Tickets + structured metadata','Persistent snapshot storage'],brand='mongodb')
node(1790,295,460,205,'SQLite index',['FTS5 / BM25 + vectors','Issue relationship graph'],brand='sqlite')
node(2400,295,500,205,'Embeddings',['EmbeddingGemma via Ollama','Local TF-IDF alternative'],brand='ollama')
arrow([(500,396),(640,396)],BLUE,'upload',(570,371))
arrow([(1060,396),(1200,396)],BLUE,'persist',(1130,371))
arrow([(1640,396),(1790,396)],BLUE,'build index',(1715,371))
arrow([(2250,377),(2400,377)],BLUE,'embed',(2325,352))
arrow([(2400,430),(2250,430)],BLUE,'vectors',(2325,460))

txt(100,667,'02  LIVE AGENT & MODEL CALLS',18,GREEN,True)
arrow([(1420,500),(1420,735)],BLUE,'metadata',(1494,605))
arrow([(2020,500),(2020,735)],BLUE,'retrieve',(2086,605))

box(100,810,260,210,stroke='#34516F')
symbol('user',198,835,62,BLUE)
txt(230,935,'User',30,WHITE,True,'middle')
txt(230,980,'Project / sprint questions',17,TEXT,anchor='middle',max_width=228)
node(490,775,480,290,'React workspace',['Analytics + Sprint Agent chat','React + TypeScript','Tickets · people · backlog'],brand='react',color=GREEN)
logo('typescript',887,797,38)
arrow([(360,884),(490,884)],GREEN,'ask',(425,858))
arrow([(490,965),(360,965)],GREEN,'view',(425,997))
arrow([(970,865),(1140,865)],GREEN,'question',(1055,838))
arrow([(1140,985),(970,985)],GREEN,'stream + sources',(1055,1017))

box(1140,735,1060,380,stroke=GREEN,sw=2.2)
logo('fastapi',1168,764,55)
logo('python',1239,764,55)
txt(1320,795,'Sprint Agent',37,WHITE,True)
txt(1320,833,'FastAPI / Python · read-only orchestration',21,TEXT)
txt(1168,883,'Scope + prompt → plan → tools → verified synthesis',25,TEXT,max_width=1004)
for x,w,title,line1,line2,brand,kind in [
    (1168,308,'Metadata tools','Tickets + people','Counts + filters','mongodb',None),
    (1500,308,'Retrieval tools','Keywords + vectors','Links + reranking','sqlite',None),
    (1832,340,'Analysis tools','Calculator + planning','Bounded memory / effort',None,'calculator'),
]:
    box(x,917,w,154,fill=GROUP,stroke='#304A64',r=8)
    if brand:logo(brand,x+16,933,34)
    else:symbol(kind,x+16,934,32,GREEN)
    txt(x+62,959,title,22,WHITE,True,max_width=w-80)
    txt(x+17,1004,line1,20,TEXT,max_width=w-34)
    txt(x+17,1039,line2,19,MUTED,max_width=w-34)

box(2400,735,500,380,stroke='#647092')
txt(2425,779,'Model connections',27,WHITE,True)
logo('ollama',2425,805,37,WHITE)
txt(2479,832,'Qwen3 / Nemotron',23,WHITE,True,max_width=390)
txt(2479,859,'Ollama · optional local presets',17,MUTED,max_width=390)
for name,yy,label in [('openai',883,'OpenAI Platform'),('azure',943,'Azure OpenAI'),('gemini',1001,'Google Gemini')]:
    logo(name,2426,yy,36,WHITE if name=='openai' else '#94A5FF' if name=='gemini' else None)
    txt(2479,yy+28,label,23,TEXT,max_width=390)
txt(2425,1091,'Choose one configured connection per run',17,MUTED,max_width=450)
arrow([(2200,862),(2400,862)],GREEN,'request',(2300,837))
arrow([(2400,991),(2200,991)],GREEN,'tool call / text',(2300,1023))

box(70,1290,2860,575,stroke='#302F50',fill=GROUP,r=16)
txt(100,1267,'03  EVALUATION, MONITORING & ITERATION',18,PURPLE,True)
node(100,1360,450,215,'Prompt catalog',['Guidance + working agreements','Immutable prompt revisions'],kind='prompt',color=PURPLE)
node(100,1640,450,180,'Golden datasets',['Questions + answers + evidence'],kind='golden',color=PURPLE,title_size=29)
node(740,1360,600,280,'Evaluation workbench',[
    'Pin prompt + golden-data versions',
    'Replay agent · compare one or two models',
    'Ragas judge · BLEU / ROUGE',
    'Quality + latency + resource use',
],kind='test',color=PURPLE,title_size=29)
node(1530,1360,530,280,'Human review',[
    'Answers + sources + ratings',
    'Choose “Use for chat”',
    'Activate a saved prompt revision',
],kind='review',color=PURPLE)
node(2400,1360,500,230,'Monitoring',[
    'MongoDB traces + user feedback',
    'Latency · tokens · estimated cost',
    'Tool calls · context · errors',
],kind='chart',color=AMBER)
node(2400,1690,500,130,'Langfuse',[],brand='langfuse',color=AMBER)
txt(2502,1783,'Optional traces + scores export',20,TEXT,max_width=370)

arrow([(550,1450),(740,1450)],PURPLE,'pin prompt',(645,1424))
arrow([(550,1730),(640,1730),(640,1550),(740,1550)],PURPLE)
txt(655,1688,'pin data',17,PURPLE)
arrow([(1340,1490),(1530,1490)],PURPLE,'compare',(1435,1463))
arrow([(1260,1360),(1260,1115)],PURPLE)
txt(1281,1212,'replay tests',18,PURPLE)
arrow([(1175,1115),(1175,1360)],PURPLE)
txt(1153,1242,'results',17,PURPLE,anchor='end')
arrow([(1800,1360),(1800,1115)],PURPLE)
txt(1821,1212,'activate prompt',18,PURPLE)
arrow([(2160,1115),(2160,1232),(2650,1232),(2650,1360)],AMBER,'traces + feedback',(2480,1207))
arrow([(2650,1590),(2650,1690)],AMBER,'export',(2702,1645),dashed=True)

# A feedback loop reaches both versioned asset catalogs, without crossing nodes.
arrow([(2400,1490),(2250,1490),(2250,1930),(70,1930),(70,1470),(100,1470)],PURPLE,dashed=True)
arrow([(70,1730),(100,1730)],PURPLE,dashed=True)
box(768,1901,1450,56,stroke=BG,fill=BG,r=0,sw=0)
txt(1493,1938,'Human feedback → revise prompts / golden data → evaluate again',25,PURPLE,True,'middle')

# A compact key replaces explanatory paragraphs inside the service boxes.
txt(740,1739,'FLOW KEY',16,MUTED,True)
for x,color,label in [(740,BLUE,'Data'),(1010,GREEN,'Agent calls'),(1330,PURPLE,'Evaluation'),(1670,AMBER,'Telemetry')]:
    arrow([(x,1770),(x+58,1770)],color)
    txt(x+76,1777,label,19,TEXT)
txt(740,1820,'Dashed arrows: optional export / human feedback. Models and embeddings are configured independently.',18,MUTED)
txt(80,1986,'Read-only Jira snapshot  ·  Attachment references only  ·  Human-controlled prompt activation',19,MUTED)
txt(2900,1986,'AGILE PLANNER / TECHNOLOGY FLOW',16,MUTED,True,'end')

defs=['<defs>']
for color in (BLUE,GREEN,PURPLE,AMBER):
    defs.append(f'<marker id="a{color[1:]}" markerWidth="11" markerHeight="11" refX="10" refY="5.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L11,5.5 L0,11 Z" fill="{color}"/></marker>')
defs.append('</defs>')
svg=ROOT/'resources/images/agileplanner_llmops_architecture.svg'
svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc"><title id="title">Agile Planner - LLMOps Architecture</title><desc id="desc">Technology and signal flow: Jira CSV to Python ingestion, MongoDB and SQLite; Ollama embeddings; React and TypeScript user interface; FastAPI Sprint Agent with metadata, retrieval and analysis tools; configurable Ollama, OpenAI, Azure OpenAI and Gemini connections; versioned prompt and golden dataset catalogs, Ragas evaluation, human activation, monitoring and optional Langfuse export.</desc>{"".join(defs)}<g font-family="Arial, Helvetica, sans-serif">{"".join(parts)}</g></svg>',encoding='utf-8')
ET.indent(mx)
drawio=ROOT/'docs/diagrams/agileplanner_llmops_architecture.drawio'
ET.ElementTree(mx).write(drawio,encoding='utf-8',xml_declaration=True)
import json
(ROOT/'docs/diagrams/agileplanner_llmops_architecture.bounds.json').write_text(json.dumps(text_bounds,indent=2)+'\n')
print(svg)
print(drawio)
