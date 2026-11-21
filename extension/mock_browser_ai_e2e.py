"""Mocked Chrome Prompt API + UI only: does not load Gemini Nano or install MV3."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).parent/'companion'
html=(root/'panel.html').read_text()
for tag in ('<link rel="stylesheet" href="panel.css">',
            '<script src="reader.js" defer></script>',
            '<script src="page-tools.js" defer></script>',
            '<script src="browser-ai.js" defer></script>',
            '<script src="panel.js" defer></script>'):
    html=html.replace(tag, '')
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':390,'height':780})
    errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda req:requests.append(req.url))
    page.set_content(html,timeout=7000)
    page.evaluate('''
    window.__pageNumber=0;window.__availability='downloadable';window.__creates=0;
    window.__modelsDestroyed=0;window.__prompts=[];window.__failNext=false;
    window.__pages=[
      {title:'One',page_label:'https://example.com/one',total_characters:72,
       blocks:[{id:'B1',text:'A controlled trial showed improved recall after intervention.'},
               {id:'B2',text:'The effects require verification with more participants.'}]},
      {title:'Two',page_label:'https://example.com/two',total_characters:73,
       blocks:[{id:'B1',text:'A different controlled trial showed reduced recall after intervention.'},
               {id:'B2',text:'The observations have not been independently verified.'}]}
    ];
    window.chrome={runtime:{id:'abcdefghijklmnopabcdefghijklmnop'},
      tabs:{query:async()=>[{id:window.__pageNumber+1,url:window.__pages[window.__pageNumber].page_label}],
        get:async()=>({url:window.__pages[window.__pageNumber].page_label})},
      scripting:{executeScript:async()=>[{result:window.__pages[window.__pageNumber]}]},
      permissions:{request:async()=>true,remove:async()=>true},
      storage:{session:{get:async()=>({}),set:async()=>{},remove:async()=>{}}}
    };
    window.LanguageModel={
      availability:async()=>window.__availability,
      create:({monitor}={})=>{
        window.__creates++;
        window.__availability='available';
        if(monitor)monitor({addEventListener:(n,cb)=>cb({loaded:1})});
        return Promise.resolve({destroy:()=>{window.__modelsDestroyed++},
          async *promptStreaming(prompt){
            window.__prompts.push(prompt);
            yield 'Evidence on ';
            if(window.__failNext){window.__failNext=false;throw new Error('mock inference failure');}
            yield 'page [A:B1].';
          }
        });
      }
    };
    ''')
    page.add_style_tag(content=(root/'panel.css').read_text())
    for src in ('reader.js','page-tools.js','browser-ai.js','panel.js'):
        page.add_script_tag(content=(root/src).read_text())
    page.locator('#capture').click()
    assert page.locator('#page-preview').is_visible()
    assert page.locator('#browser-ai-ask').is_disabled()
    page.locator('#browser-ai-check').click()
    page.wait_for_function("document.querySelector('#browser-ai-status').textContent.includes('downloaded')")
    assert page.locator('#browser-ai-enable').is_enabled()
    assert page.evaluate('window.__creates')==0, 'checking availability unexpectedly downloaded model'
    page.locator('#browser-ai-enable').click()
    page.wait_for_function("document.querySelector('#browser-ai-status').textContent.includes('ready')")
    assert page.evaluate('window.__creates')==1
    assert page.evaluate('window.__modelsDestroyed')==1
    assert page.locator('#browser-ai-ask').is_enabled()
    page.locator('#question').fill('What do the trial results suggest?')
    page.locator('#browser-ai-ask').click()
    page.wait_for_function("document.querySelector('#answer').textContent.includes('page [A:B1]')")
    page.wait_for_function("document.querySelector('#browser-ai-ask').disabled===false")
    assert 'Gemini Nano' in page.locator('#backend').inner_text()
    assert page.locator('#source-items .source-item').count()>=1
    assert page.evaluate('window.__creates')==2
    assert page.evaluate('window.__modelsDestroyed')==2
    page.evaluate('window.__pageNumber=1')
    page.locator('#capture-compare').click()
    assert page.locator('#compare-preview').is_visible()
    page.locator('#browser-ai-compare').click()
    page.wait_for_function('window.__prompts.length===2')
    page.wait_for_function("document.querySelector('#browser-ai-compare').disabled===false")
    prompts=page.evaluate('window.__prompts')
    assert '[A:B1]' in prompts[1] and '[B:B1]' in prompts[1]
    assert 'https://example' not in str(prompts)
    assert page.locator('#source-items .source-item').count()>=2
    page.evaluate('window.__failNext=true')
    page.locator('#browser-ai-ask').click()
    page.wait_for_function("document.querySelector('#analysis-status').textContent.includes('mock inference failure')")
    assert not page.locator('#answer-card').is_visible(), 'partial output was displayed as complete'
    assert page.evaluate('window.__modelsDestroyed')==4, 'failed model session was not destroyed'
    page.locator('#clear').click()
    assert not page.locator('#page-preview').is_visible()
    assert not page.locator('#compare-preview').is_visible()
    assert page.locator('#browser-ai-ask').is_disabled()
    for w in (360,390,768):
        page.set_viewport_size({'width':w,'height':780})
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),w
    assert not requests,requests
    assert not errors,errors
    print('PASS: mock Chrome Prompt API enable consent, one-page and two-page streaming, exact sources, clear; no real model/network')
    browser.close()
