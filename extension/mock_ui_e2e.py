"""Optional Chromium DOM smoke test. Mocked extension APIs; NOT a real installed extension."""
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).parent/'companion'
html=(root/'panel.html').read_text()
# Block remote assets: replace references with injected local script/style assets.
html=html.replace('<link rel="stylesheet" href="panel.css">','').replace('<script src="reader.js" defer></script>','').replace('<script src="page-tools.js" defer></script>','').replace('<script src="panel.js" defer></script>','')
with sync_playwright() as p:
  ctx=p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
  page=ctx.new_page(viewport={'width':390,'height':800})
  errors=[]; requests=[]
  page.on('pageerror', lambda e: errors.append(str(e)))
  page.on('request',lambda req: requests.append(req.url))
  page.set_content(html,timeout=4000)
  page.evaluate('''
    window.chrome = {
      runtime: {id:'abcdefghijklmnopabcdefghijklmnop'},
      tabs: {query:async()=>[{id:1,url:'http://sample.local/article'}], get:async()=>({id:1,url:'http://sample.local/article'})},
      scripting: {executeScript:async()=>[{result:{title:'The test paper', page_label:'http://sample.local/article',total_characters:128,blocks:[
        {id:'B1',text:'Our test showed that the experimental results were inconclusive.'},
        {id:'B2',text:'The experimental methods relied on a small sample.'},
        {id:'B3',text:'A private email password should never be captured in a form field.'}
      ]}}]},
      permissions: {request:async()=>true, remove:async()=>true},
      storage: {session:{get:async()=>({}),set:async()=>{},remove:async()=>{window.__removed=true;}}}
    };''')
  page.add_style_tag(content=(root/'panel.css').read_text())
  for script in ['reader.js','page-tools.js','panel.js']:
    page.add_script_tag(content=(root/script).read_text())
  page.locator('#capture').click(timeout=5000)
  assert page.locator('#page-preview').is_visible(), (page.locator('#page-status').inner_text(), errors)
  assert page.locator('#find').is_enabled()
  assert page.locator('#ask').is_disabled()
  page.locator('#question').fill('experimental results',timeout=3000)
  page.locator('#find').click(timeout=3000)
  assert 'No AI or network was used' in page.locator('#answer').inner_text()
  assert page.locator('#source-items .source-item').count()==2
  assert page.locator('#source-items .source-item').first.inner_text().find('inconclusive')>=0
  assert requests==[], requests
  page.locator('#pairing').evaluate('(el) => el.open = true')
  page.locator('#disconnect').click(timeout=3000)
  page.wait_for_function('window.__removed === true', timeout=3000)
  assert 'Disconnected' in page.locator('#analysis-status').inner_text()
  assert page.locator('#find').is_enabled()
  assert not errors,errors
  print('PASS: Chromium mock UI capture -> offline evidence -> no network -> disconnect')
  ctx.close()
