"""Bundles src/ into dist/placelab.html (a single file, ready to publish as an artifact).
The single file has no server, so its agents use template conversations; the final report's chart
(visual-summary/narrative-arcs.html) travels inside it as ARCS_HTML."""
import json, pathlib
G=pathlib.Path(__file__).parent
S=G/'src'
html=(S/'index.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="styles.css">','<style>\n'+(S/'styles.css').read_text(encoding='utf-8')+'</style>')
order=['data/plan.js','profiles.js','scene.js','memory.js','agents.js','i18n.js','strings.js','talk.js','camera.js','report.js','sim.js']
arcs=(G/'visual-summary'/'narrative-arcs.html').read_text(encoding='utf-8').replace('<script src="narrative-data.js"></script>\n','')
js='const ARCS_HTML='+json.dumps(arcs).replace('</','<\\/')+';\n'+'\n'.join((S/f).read_text(encoding='utf-8') for f in order)
for f in order: html=html.replace(f'<script src="{f}"></script>\n','')
html=html.rstrip()+'\n<script>\n'+js+'\n</script>\n'
out=G/'dist'/'placelab.html'
out.parent.mkdir(exist_ok=True);out.write_text(html,encoding='utf-8');print('->',out,len(html),'bytes')
