"""Bundles src/ into dist/placelab.html (a single file, ready to publish as an artifact)."""
import pathlib
S=pathlib.Path(__file__).parent/'src'
html=(S/'index.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="styles.css">','<style>\n'+(S/'styles.css').read_text(encoding='utf-8')+'</style>')
order=['data/plan.js','profiles.js','scene.js','memory.js','agents.js','i18n.js','sim.js']
js='\n'.join((S/f).read_text(encoding='utf-8') for f in order)
for f in order: html=html.replace(f'<script src="{f}"></script>\n','')
html=html.rstrip()+'\n<script>\n'+js+'\n</script>\n'
out=pathlib.Path(__file__).parent/'dist'/'placelab.html'
out.parent.mkdir(exist_ok=True);out.write_text(html,encoding='utf-8');print('->',out,len(html),'bytes')
