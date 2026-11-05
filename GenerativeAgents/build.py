"""Bundles src/ into dist/placelab.html (a single file, ready to publish as an artifact)."""
import pathlib
S=pathlib.Path(__file__).parent/'src'
html=(S/'index.html').read_text()
html=html.replace('<link rel="stylesheet" href="styles.css">','<style>\n'+(S/'styles.css').read_text()+'</style>')
order=['data/plan.js','profiles.js','scene.js','memory.js','agents.js','i18n.js','sim.js']
js='\n'.join((S/f).read_text() for f in order)
for f in order: html=html.replace(f'<script src="{f}"></script>\n','')
html=html.rstrip()+'\n<script>\n'+js+'\n</script>\n'
out=pathlib.Path(__file__).parent/'dist'/'placelab.html'
out.write_text(html);print('->',out,len(html),'bytes')
