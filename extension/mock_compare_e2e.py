"""Mocked Chromium UI interaction; NOT an installed Chrome extension or real model."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).parent/'companion'
html = (root/'panel.html').read_text()
for item in ('<link rel="stylesheet" href="panel.css">',
             '<script src="reader.js" defer></script>',
             '<script src="page-tools.js" defer></script>',
             '<script src="browser-ai.js" defer></script>',
             '<script src="panel.js" defer></script>'):
    html = html.replace(item,'')
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':390,'height':780})
    errors=[]; network=[]
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.on('request',lambda req: network.append(req.url))
    page.set_content(html,timeout=6000)
    page.evaluate('''
    window.__pageNumber=0;window.__sent=null;window.__modelCalls=0;
    window.__pages=[
      {title:'Report A',page_label:'https://example.test/first',total_characters:100,
       blocks:[{id:'B1',text:'The experimental results showed no improvement in performance.'},
               {id:'B2',text:'The control group used a smaller sample.'}]},
      {title:'Report B',page_label:'https://example.test/second',total_characters:99,
       blocks:[{id:'B1',text:'Experimental results showed improvement in performance.'},
               {id:'B2',text:'The second report mentions an entirely new metric.'}]}
    ];
    window.chrome={runtime:{id:'abcdefghijklmnopabcdefghijklmnop'},
      tabs:{query:async()=>[{id:window.__pageNumber+1,url:window.__pages[window.__pageNumber].page_label}],
        get:async()=>({url:window.__pages[window.__pageNumber].page_label})},
      scripting:{executeScript:async()=>[{result:window.__pages[window.__pageNumber]}]},
      permissions:{request:async()=>true,remove:async()=>true},
      storage:{session:{get:async()=>({}),set:async()=>{},remove:async()=>{}}}
    };''')
    page.add_style_tag(content=(root/'panel.css').read_text())
    for file in ('reader.js','page-tools.js','browser-ai.js','panel.js'):
        page.add_script_tag(content=(root/file).read_text())
    page.locator('#capture').click()
    assert page.locator('#page-preview').is_visible()
    assert not page.locator('#compare-online').is_enabled()
    page.evaluate('window.__pageNumber=1')
    page.locator('#capture-compare').click()
    assert page.locator('#compare-preview').is_visible()
    assert page.locator('#compare-offline').is_enabled()
    page.locator('#compare-offline').click()
    assert page.locator('#source-items .source-item').count() == 2
    assert 'No AI or network used' in page.locator('#answer').inner_text()
    assert 'Page A' in page.locator('#source-items .source-item').first.inner_text()
    assert 'Page B' in page.locator('#source-items .source-item').last.inner_text()
    assert network==[],network
    page.evaluate('''
      window.fetch=async (url,req={})=>{
        if(url.endsWith('/status'))return {ok:true,json:async()=>({connected:true,inference:{status:'model_listed'}})};
        if(url.endsWith('/compare')){
          window.__modelCalls++;window.__sent=JSON.parse(req.body);
          return {ok:true,json:async()=>({answer:'Comparing [source 1] and [source 3].',backend:'ollama',references:[
            {block_id:'B1',page_block_number:1,page:'A',text:'The experimental results showed no improvement in performance.'},
            {block_id:'B1',page_block_number:1,page:'B',text:'Experimental results showed improvement in performance.'}]})};
        }
        throw new Error('Unexpected network target');
      }; void 0;''')
    page.locator('#pairing').evaluate('(el)=>el.open=true')
    page.locator('#token').fill('synthetic-pairing-token')
    page.locator('#connect').click()
    page.wait_for_function("document.querySelector('#compare-online').disabled === false")
    page.locator('#question').fill('Compare experimental results.')
    page.locator('#compare-online').click()
    page.wait_for_function('window.__modelCalls===1')
    page.wait_for_function("document.querySelector('#answer').textContent.includes('Comparing')")
    sent=page.evaluate('window.__sent')
    assert sent['question']=='Compare experimental results.'
    assert len(sent['pages'])==2
    assert sent['pages'][0]['title']=='Report A'
    assert sent['pages'][1]['title']=='Report B'
    assert 'page_label' not in str(sent)
    assert page.locator('#source-items .source-item').count()==2
    page.locator('#clear').click()
    assert not page.locator('#compare-preview').is_visible()
    assert not page.locator('#page-preview').is_visible()
    assert page.locator('#compare-online').is_disabled()
    for width in (360, 390, 768):
        page.set_viewport_size({'width':width, 'height':780})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), width
    assert not errors,errors
    print('PASS: mock Chrome two user-selected captures -> offline crosscheck -> paired model comparison -> clear; no real extension/model')
    browser.close()
