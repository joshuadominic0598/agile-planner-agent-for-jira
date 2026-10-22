"""Build the editable AgilePlanner lifecycle diagram and its SVG export.

Run with Python 3. PNG rendering uses render_llmops_lifecycle.mjs.
No private export, runtime prompt, or measured score is included.
"""

from pathlib import Path
import html
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
W, H = 2600, 1640
BG, PANEL, CARD = '#080F1F', '#0E192C', '#111E33'
WHITE, MUTED, DIM = '#F2F6FF', '#B8C8DF', '#8298B6'
COLORS = ['#51CFFF', '#A99AFF', '#F7BB68', '#FB91B2', '#6BDDC4', '#8FB4FF']
svg = []
mx = ET.Element('mxfile', host='app.diagrams.net', version='24.7.17')
dia = ET.SubElement(mx, 'diagram', name='AgilePlanner LLMOps', id='agileplanner-llmops')
model = ET.SubElement(dia, 'mxGraphModel', dx=str(W), dy=str(H), grid='1', gridSize='10',
                      page='1', pageScale='1', pageWidth=str(W), pageHeight=str(H),
                      background=BG, math='0', shadow='0')
root = ET.SubElement(model, 'root')
ET.SubElement(root, 'mxCell', id='0')
ET.SubElement(root, 'mxCell', id='1', parent='0')
counter = 1


def cell(x, y, w, h, style, value=''):
    global counter
    counter += 1
    c = ET.SubElement(root, 'mxCell', id=str(counter), value=value, style=style,
                      vertex='1', parent='1')
    ET.SubElement(c, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), **{'as': 'geometry'})


def rect(x, y, w, h, fill=CARD, stroke='#293B56', r=20, sw=1.5):
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    cell(x, y, w, h, f'rounded={int(bool(r))};arcSize=10;absoluteArcSize=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};')


def text(x, y, value, size=20, color=MUTED, weight=400, anchor='start', spacing=None):
    attrs = f' letter-spacing="{spacing}"' if spacing is not None else ''
    svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}"{attrs}>{html.escape(value)}</text>')
    # Every label is a separate native draw.io text object.
    width = max(60, len(value) * size * .61 + 12)
    xx = x if anchor == 'start' else x - width / (2 if anchor == 'middle' else 1)
    cell(xx, y-size*.94, width, size*1.35,
         f'text;html=0;strokeColor=none;fillColor=none;align={"left" if anchor == "start" else "right" if anchor == "end" else "center"};verticalAlign=top;whiteSpace=nowrap;overflow=visible;spacing=0;fontFamily=Arial;fontSize={size};fontColor={color};fontStyle={1 if weight >= 600 else 0};', value)


def line(points, color=DIM, width=2, dash=False, arrow=False):
    coords = ' '.join(f'{x},{y}' for x, y in points)
    svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"' + (' stroke-dasharray="8 8"' if dash else '') + (f' marker-end="url(#arrow-{color[1:]})"' if arrow else '') + '/>')
    global counter
    counter += 1
    c = ET.SubElement(root, 'mxCell', id=str(counter), edge='1', parent='1',
        style=f'edgeStyle=none;rounded=1;html=0;strokeColor={color};strokeWidth={width};dashed={int(dash)};endArrow={"block" if arrow else "none"};endFill=1;')
    g = ET.SubElement(c, 'mxGeometry', relative='1', **{'as': 'geometry'})
    ET.SubElement(g, 'mxPoint', x=str(points[0][0]), y=str(points[0][1]), **{'as': 'sourcePoint'})
    ET.SubElement(g, 'mxPoint', x=str(points[-1][0]), y=str(points[-1][1]), **{'as': 'targetPoint'})
    if len(points) > 2:
        arr = ET.SubElement(g, 'Array', **{'as': 'points'})
        for x, y in points[1:-1]:
            ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))


def icon(x, y, kind, color):
    # Small geometric line icons; also editable as draw.io primitives.
    if kind == 'data':
        for dy in (0, 12, 24):
            rect(x, y+dy, 40, 10, fill=PANEL, stroke=color, r=5, sw=2)
    elif kind == 'versions':
        for dx, dy in ((0, 0), (9, 9), (18, 18)):
            rect(x+dx, y+dy, 24, 24, fill=CARD, stroke=color, r=4, sw=2)
    elif kind == 'test':
        line([(x+7,y), (x+30,y)], color, 2)
        line([(x+12,y), (x+12,y+12), (x,y+33), (x+4,y+38), (x+34,y+38), (x+38,y+33), (x+25,y+12), (x+25,y)], color, 2)
        line([(x+9,y+25),(x+29,y+25)],color,2)
    elif kind == 'review':
        rect(x+2,y,34,40,fill=CARD,stroke=color,r=5,sw=2)
        line([(x+10,y+21),(x+17,y+28),(x+29,y+13)],color,3)
    elif kind == 'agent':
        rect(x,y+7,40,29,fill=CARD,stroke=color,r=8,sw=2)
        line([(x+20,y),(x+20,y+7)],color,2)
        for dx in (11,28):
            rect(x+dx,y+17,3,4,fill=color,stroke=color,r=1,sw=1)
        line([(x+12,y+28),(x+28,y+28)],color,2)
    else:
        line([(x,y+2),(x,y+37),(x+40,y+37)],color,2)
        line([(x+6,y+27),(x+15,y+17),(x+24,y+23),(x+37,y+5)],color,3)


def pill(x, y, w, label, color, fill=PANEL, size=16):
    rect(x,y,w,34,fill=fill,stroke='#2B3C55',r=16,sw=1)
    text(x+w/2,y+23,label,size,color,600,'middle')


rect(0,0,W,H,BG,BG,0,0)
rect(80,55,8,22,COLORS[0],COLORS[0],3,0)
text(104,73,'PROJECT ARCHITECTURE  /  JIRA ANALYTICS + AI AGENT',17,DIM,600,spacing=1.8)
text(80,195,'Agile Planner - LLMOps Lifecycle',68,WHITE,700)

rect(1920,97,580,145,PANEL,'#263953',18)
text(1952,134,'AN EVIDENCE-DRIVEN IMPROVEMENT LOOP',16,COLORS[0],600,spacing=1)
text(1952,171,'Versioned guidance  →  evaluated behavior',23,WHITE,600)
text(1952,208,'Human decisions  →  monitored feedback',23,MUTED)

stages = [
    ('Prepare Jira data','data','BUILD THE KNOWLEDGE FOUNDATION',[
        ('IMPORT & VALIDATE',['Jira CSV → normalized tickets','Preserve custom / repeated fields']),
        ('STORE & INDEX',['MongoDB snapshot + metadata','SQLite keyword / vector + graph']),
    ],'Snapshot-scoped evidence'),
    ('Version the assets','versions','MAKE EACH CHANGE TRACEABLE',[
        ('PROMPT CATALOG',['Project guidance + working rules','Immutable guidance revisions']),
        ('GOLDEN DATASETS',['Questions, answers + evidence','Separate test-data revisions']),
    ],'Independent prompt + data history'),
    ('Evaluate candidates','test','REPLAY A CONTROLLED EXPERIMENT',[
        ('PIN THE TEST INPUTS',['Prompt + golden-data revisions','Same export, effort + judge']),
        ('COMPARE MODEL BEHAVIOR',['One model or two; fresh memory','Evidence, scores + resource use']),
    ],'Ragas* · BLEU / ROUGE · human review'),
    ('Review & activate','review','CHOOSE THE GUIDANCE FOR CHAT',[
        ('REVIEW THE EVIDENCE',['Inspect answers + source coverage','Rate quality; record feedback']),
        ('ACTIVATE EXPLICITLY',['Choose “Use for chat”','Revisit earlier prompt revisions']),
    ],'Human-controlled activation'),
    ('Serve Sprint Agent','agent','ANSWER FROM PROJECT EVIDENCE',[
        ('INVESTIGATE THE QUESTION',['Selected model + pinned prompt','Read-only retrieval + analysis']),
        ('DELIVER A GROUNDED ANSWER',['Bound context, memory + effort','Stream text with ticket sources']),
    ],'Detailed runtime flow below'),
    ('Observe & improve','observe','TURN REAL USAGE INTO NEW TESTS',[
        ('INSPECT LOCAL TRACES',['Latency, tokens + estimated cost','Tool calls, errors + user feedback']),
        ('CLOSE THE LOOP',['Review weak or costly answers','Revise guidance / golden cases']),
    ],'MongoDB · optional Langfuse export'),
]

text(80,323,'LIFECYCLE',16,DIM,600,spacing=2)
line([(206,317),(2500,317)],'#263750',1)

for i,(title,kind,kicker,sections,badge) in enumerate(stages):
    x,y=80+i*410,350
    c=COLORS[i]
    rect(x,y,370,450,CARD,'#293C57',20)
    rect(x+1,y+1,368,4,c,c,2,0)
    text(x+26,y+69,f'{i+1:02}',47,c,600)
    icon(x+302,y+30,kind,c)
    text(x+26,y+117,title,28,WHITE,600)
    text(x+26,y+151,kicker,12.7,c,600,spacing=.45)
    line([(x+26,y+173),(x+344,y+173)],'#2A3B53',1)
    for j,(label,lines) in enumerate(sections):
        yy=y+206+j*108
        text(x+26,yy,label,13,DIM,600,spacing=.7)
        for k,label_line in enumerate(lines):
            text(x+26,yy+30+k*28,label_line,19.3,MUTED)
    pill(x+20,y+395,330,badge,c,size=13.8)
    if i<5:
        line([(x+377,y+224),(x+401,y+224)],'#6D85A9',2.4,arrow=True)

# This bus is deliberately manual: feedback drives revision, not model training.
line([(2315,802),(2315,861),(675,861),(675,805)],COLORS[1],2.5,dash=True,arrow=True)
rect(917,836,1160,48,BG,BG,10,0)
text(1497,867,'HUMAN FEEDBACK  →  REVISE PROMPTS / TESTS  →  RE-EVALUATE',18,COLORS[1],600,'middle',1)
text(80,904,'* Ragas uses a configured judge; scores apply where evidence and references support them.',17,DIM)

# Expanded, nested runtime view: model chooses tools, then synthesizes its answer.
rect(80,955,2420,515,PANEL,'#2A405E',24)
pill(112,981,145,'STAGE 05',COLORS[4],size=16)
text(279,1007,'Inside the Sprint Agent',30,WHITE,600)
text(2464,1006,'React workspace  /  FastAPI orchestration',18,DIM,400,'end')

rect(112,1055,445,300,CARD,'#324662',16)
text(140,1099,'QUESTION + CONVERSATION',18,COLORS[0],600,spacing=.8)
text(140,1142,'Ask about tickets, sprints,',23,WHITE,600)
text(140,1174,'people or backlog decisions.',23,WHITE,600)
line([(140,1198),(528,1198)],'#2B3E59',1)
text(140,1235,'Input screening + intent analysis',20,MUTED)
text(140,1267,'Resolve scope; clarify ambiguity',20,MUTED)
text(140,1316,'Page hints + budgeted chat memory',18,DIM)

rect(620,1055,1030,300,CARD,'#3E786F',16)
text(648,1099,'MODEL-LED INVESTIGATION',18,COLORS[4],600,spacing=.8)
text(648,1143,'Selected connection + pinned prompt revision',29,WHITE,600)
text(648,1181,'Plan  →  retrieve  →  verify evidence  →  synthesize',23,MUTED)
rect(648,1210,458,113,PANEL,'#314A60',12)
text(669,1243,'STRUCTURED TOOLS  /  MONGODB',15,COLORS[0],600)
text(669,1277,'Ticket metadata, people + aggregates',20,MUTED)
text(669,1306,'Planning rules + verified calculations',18,DIM)
rect(1130,1210,492,113,PANEL,'#314A60',12)
text(1151,1243,'HYBRID RETRIEVAL  /  SQLITE',15,COLORS[1],600)
text(1151,1277,'Keywords + vectors + exported links',20,MUTED)
text(1151,1306,'Reranking + bounded evidence packets',18,DIM)
line([(557,1190),(610,1190)],COLORS[0],2.5,arrow=True)
line([(1650,1190),(1710,1190)],COLORS[4],2.5,arrow=True)

rect(1720,1055,748,300,CARD,'#324662',16)
text(1748,1099,'GROUNDED ANSWER + OBSERVABILITY',18,COLORS[5],600,spacing=.8)
text(1748,1143,'Streamed response with inspectable ticket sources',26,WHITE,600)
text(1748,1181,'Thumbs feedback + comments; saved conversation history',21,MUTED)
line([(1748,1205),(2438,1205)],'#2B3E59',1)
text(1748,1242,'MongoDB records requests, tools, evidence, usage + errors',21,MUTED)
text(1748,1276,'Monitoring → inspect behavior     Evaluation → retest changes',20,MUTED)
text(1748,1317,'Optional Langfuse: native traces, observations + feedback',18,DIM)

text(112,1418,'MODEL CONNECTIONS',15,DIM,600,spacing=1.3)
for xx,ww,label in [(338,210,'Ollama / local'),(566,224,'OpenAI Platform'),(808,216,'Azure OpenAI'),(1042,175,'Gemini')]:
    pill(xx,1392,ww,label,MUTED,size=17)
text(2468,1418,'Tool, context and effort budgets apply throughout.',18,DIM,400,'end')

for x,label,c in [(80,'READ-ONLY JIRA SNAPSHOT',COLORS[0]),(770,'ATTACHMENTS: REFERENCES ONLY',COLORS[1]),(1610,'HUMAN-CONTROLLED PROMPT ACTIVATION',COLORS[4])]:
    rect(x,1516,6,19,c,c,2,0)
    text(x+20,1532,label,16,MUTED,600,spacing=1.1)
line([(80,1561),(2500,1561)],'#25354B',1)
text(80,1597,'RAG + prompt iteration  •  Model training and automatic promotion are outside this workflow.',17,DIM)
text(2500,1597,'AGILEPLANNER  /  LLMOPS',15,DIM,600,'end',1.4)

defs = ['<defs>']
for c in set(COLORS+[DIM,'#6D85A9']):
    defs.append(f'<marker id="arrow-{c[1:]}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 Z" fill="{c}"/></marker>')
defs.append('</defs>')
out = ROOT/'resources/images/agileplanner_llmops_lifecycle.svg'
out.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc"><title id="title">AgilePlanner — Jira agent LLMOps lifecycle</title><desc id="desc">Six connected stages: prepare Jira data, version prompts and golden data, evaluate candidates, review and activate, serve the Sprint Agent, observe and improve. Human feedback returns to versioning. An expanded runtime shows input screening, model-led read-only tools, MongoDB structured queries, SQLite hybrid retrieval, cited answers and traces.</desc>{"".join(defs)}<g font-family="Arial, Helvetica, sans-serif">{"".join(svg)}</g></svg>', encoding='utf-8')
ET.indent(mx)
editable=ROOT/'docs/diagrams/agileplanner_llmops_lifecycle.drawio'
ET.ElementTree(mx).write(editable, encoding='utf-8', xml_declaration=True)
print(out)
print(editable)
