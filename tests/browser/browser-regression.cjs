'use strict';
// Actual CGI render + production JS/CSS, isolated loopback HTTP fixtures only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const repo = path.resolve(__dirname, '../..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'hostbackup-browser-'));
const posix = value => value.replace(/\\/g, '/');
const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";
const perlLib = ['tests/browser/perl','tests/perl-stub','tests/perl'].join(':');
let html;
if (process.platform === 'win32') {
  html = execFileSync('C:/Program Files/Git/bin/bash.exe', ['-s'], {cwd:repo, input:`PERL5LIB=${quote(perlLib)} LBPDATADIR=${quote(posix(temp))} REQUEST_METHOD=GET REMOTE_USER=fixture HTTP_USER_AGENT=fixture perl -MHostBackupFixture webfrontend/htmlauth/index.cgi\n`, encoding:'utf8'});
} else html = execFileSync('perl',['-MHostBackupFixture','webfrontend/htmlauth/index.cgi'], {cwd:repo,env:{...process.env, PERL5LIB:perlLib,LBPDATADIR:temp,REQUEST_METHOD:'GET',REMOTE_USER:'fixture',HTTP_USER_AGENT:'fixture'},encoding:'utf8'});
assert.match(html,/value="\/fixture\/backup"/);
assert.doesNotMatch(html,/Speichern und Backup-Start bleiben gesperrt/);
assert.match(html, /<!doctype html><html><head>/);
const assetUrls = {};
for (const name of ['style.css', 'hostbackup.js']) {
  const digest = createHash('sha256').update(fs.readFileSync(path.join(repo, 'webfrontend/htmlauth/assets', name))).digest('hex').slice(0, 16);
  const assetUrl = 'assets/' + name + '?v=' + digest;
  assert.ok(html.includes('"' + assetUrl + '"'), 'CGI must render content-fingerprinted asset URL: ' + assetUrl);
  assetUrls[name] = '/' + assetUrl;
}
const task='backup-fixture.log', errors=[], receipts=[];
const assetRequests=[];
const overviewBackupId='20260901-020002', overviewFinishedAt='2026-09-01T02:07:27+02:00';
const overviewTarget='/media/usb/PI_Backup/loxberry-hostbackup/'+'backup-target-with-a-deliberately-long-name-'.repeat(3);
const verificationReport={backup_id:'fixture-ok',status:'verified',checked_files:3,checked_at:'2026-09-13T12:00:00Z',changes:[],content_verified:true,restore_tested:false};
let failSave=true, taskFinished=false, tokenNumber=0, postCount=0, htmlCount=0, statusCount=0, tokenDelay=0, saveDelay=0, lastSavedPath='';
let overviewIssues=false, reportRequests=0, taskPhase='copying';
const longLog = () => Array.from({length:180+statusCount},(_,i)=>`${i}: 3.43G 96% 4.23MB/s ${'long-path/'.repeat(36)} file-${i}`).join('\r');
function json(res,value,status=200){res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));}
const server=http.createServer(async(req,res)=>{
  try{
    const url=new URL(req.url,'http://127.0.0.1');
    if(url.pathname==='/legacy-ui'){
      res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});
      res.end('<!doctype html><html><head><link rel="stylesheet" href="assets/style.css"></head><body><div class="overview-grid">Previously cached stylesheet</div></body></html>');return;
    }
    if(url.pathname.endsWith('/assets/style.css')||url.pathname.endsWith('/assets/hostbackup.js')){
      assetRequests.push(url.pathname+url.search);
      const file=path.join(repo,'webfrontend/htmlauth',url.pathname.replace(/^\//,''));
      res.writeHead(200,{'Content-Type':file.endsWith('.js')?'application/javascript':'text/css','Cache-Control':'public, max-age=31536000, immutable'});
      if(url.pathname.endsWith('/style.css')&&!url.search){res.end(':root { --hostbackup-legacy-css: cached; } .overview-grid { display: block; }');return;}
      res.end(fs.readFileSync(file));return;
    }
    const action=url.searchParams.get('action');
    if(req.method==='POST'){
      let body='';for await(const chunk of req)body+=chunk;
      postCount++;assert.equal(req.headers['x-hostbackup-request'],'1');assert.equal(req.headers['x-csrf-token'],'fresh-'+tokenNumber);
      const params=new URLSearchParams(body);assert.equal(params.get('csrf_token'),'fresh-'+tokenNumber);
      if(action==='save-config') { lastSavedPath=params.get('backup_root'); await new Promise(resolve=>setTimeout(resolve,saveDelay)); return json(res,failSave?{ok:false,error:'Simulierter Speicherfehler'}:{ok:true,message:'Gespeichert'},failSave?400:200); }
      if(action==='record-restore-test') {
        assert.equal(params.get('backup_id'),'fixture-ok');assert.equal(params.get('result'),'passed');assert.match(params.get('tested_at'),/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
        const entry={result:params.get('result'),tested_at:params.get('tested_at'),note:params.get('note'),recorded_at:'2026-09-13T12:00:00Z',source:'manual-user-report',manifest_sha256:'fixture-hash',applies_to_current_manifest:true};
        Object.assign(verificationReport,{restore_tested:true,restore_test:entry,restore_test_history:[entry],restore_test_evidence:'manual-user-report'});
        return json(res,{ok:true,message:'Persönlicher Testeintrag gespeichert.',data:verificationReport});
      }
      return json(res,{ok:true,redirect:'?active_task='+task});
    }
    if(action==='csrf-token'){await new Promise(resolve=>setTimeout(resolve,tokenDelay));return json(res,{csrf_token:'fresh-'+(++tokenNumber),expires_at:Date.now()/1000+3600});}
    if(action==='task-overview')return json(res,{tasks:[{task,state:taskFinished?'finished':'running'}],active_task:taskFinished?null:task,last_success:{backup_id:overviewBackupId,finished_at:overviewFinishedAt},next_run:{local:'14.09.2026 02:00'},last_failure:overviewIssues?{task:'backup-old-failure.log',state:'failed'}:null,pending_service_recovery:overviewIssues?1:0,target:{configured:true,readable:true,path:overviewTarget,available_mb:20000}});
    if(['backup-preview','storage-info','runtime-cleanup-preview','diagnostics'].includes(action))reportRequests++;
    if(action==='task-status'){statusCount++;return json(res,{state:taskFinished?'finished':'running',phase:taskFinished?'complete':taskPhase,now:100,mtime:99,content_b64:Buffer.from(longLog()).toString('base64')});}
    if(action==='target-notice'){res.end('<section class="inline-notice">Fixture-Ziel verfügbar</section>');return;}
    if(action==='backup-list'){res.end('<tr><td data-label="ID">fixture-ok</td><td data-label="Status">complete</td><td data-label="Host">fixture</td><td data-label="Grösse">3 GiB</td><td data-label="Dateien">100</td><td data-label="Fertiggestellt">heute</td><td data-label="Export">–</td><td data-label="Aktionen"><form method="get" class="operation-form"><input type="hidden" name="action" value="verification-report"><input type="hidden" name="backup_id" value="fixture-ok"><button type="submit">Prüfbericht anzeigen</button></form><details class="restore-test-record"><summary>Externen Restoretest dokumentieren</summary><form method="post" class="restore-test-form"><input type="hidden" name="action" value="record-restore-test"><input type="hidden" name="backup_id" value="fixture-ok"><label>Ergebnis<select name="result" required><option value="">Bitte wählen</option><option value="passed">Erfolgreich</option><option value="failed">Fehlgeschlagen</option></select></label><label>Datum und Uhrzeit<input name="tested_at" type="datetime-local" required></label><label>Notiz<textarea name="note" maxlength="2000"></textarea></label><button type="submit">Persönlichen Testeintrag speichern</button></form></details><span class="info-help"><button type="button" class="info-button" aria-label="Information">i</button><span class="info-bubble">Dynamisch geladene Information</span></span></td></tr>');return;}
    if(action==='stop-targets'){await new Promise(resolve=>setTimeout(resolve,100));res.end('<input type="hidden" name="stop_targets_loaded" value="1"><label><input type="checkbox" name="stop_targets" value="systemd:test.service" checked>Testdienst</label><button type="button" data-stop-target-preset="none">Keine Dienste</button>');return;}
    if(action==='backup-preview')return json(res,{saved_config:true,backup_mode:'snapshot',metadata_mode:'network-compatible',full_baseline_required:true,excludes:['/fixture/backup/***'],source_volumes:[{path:'/',included:true,reason:'System'}],available_mb:20000,baseline_estimate_mb:3000});
    if(action==='verification-report')return json(res,verificationReport);
    if(url.pathname==='/system/images/icons/loxberryhostbackup/icon_64.png'){res.writeHead(200,{'Content-Type':'image/png'});res.end(fs.readFileSync(path.join(repo,'icons/icon_64.png')));return;}
    if(url.pathname.startsWith('/system/')){res.writeHead(204);res.end();return;}
    htmlCount++;res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(html);
  }catch(error){errors.push(error.message);json(res,{error:error.message},500);}
});
async function visible(page,selector){await page.locator(selector).waitFor({state:'visible'});}
(async()=>{
  let browser;
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const base='http://127.0.0.1:'+server.address().port+'/';
    const launch={headless:true};if(process.env.HOSTBACKUP_BROWSER_EXECUTABLE)launch.executablePath=process.env.HOSTBACKUP_BROWSER_EXECUTABLE;
    browser=await chromium.launch(launch);
    const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',error=>errors.push(error.message));
    page.on('dialog',dialog=>dialog.accept());
    await page.goto(base+'legacy-ui');
    assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--hostbackup-legacy-css').trim()),'cached');
    await page.goto(base+'legacy-ui');
    assert.equal(assetRequests.filter(value=>value==='/assets/style.css').length,1,'The obsolete unversioned stylesheet really is cached');
    await page.goto(base);await visible(page,'#download-task-log');
    await page.locator('.overview-item .overview-value').first().waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--hostbackup-legacy-css').trim()),'');
    for(const assetUrl of Object.values(assetUrls))assert.ok(assetRequests.includes(assetUrl),'Fresh fingerprinted asset must be loaded: '+assetUrl);
    assert.equal(assetRequests.filter(value=>value==='/assets/style.css').length,1,'Updated CGI must not request the obsolete URL');
    receipts.push('Real CGI head fingerprints CSS/JS by content and bypasses a primed old stylesheet cache');
    const overviewCards=page.locator('#overview-values .overview-item');
    assert.equal(await overviewCards.count(),4);
    const desktopLayout=await page.locator('#overview-values').evaluate(node=>({display:getComputedStyle(node).display,columns:getComputedStyle(node).gridTemplateColumns.split(' ').length,cards:Array.from(node.children).map(card=>{const label=card.querySelector('.overview-label'),value=card.querySelector('.overview-value');return {gap:value.getBoundingClientRect().top-label.getBoundingClientRect().bottom,text:card.textContent,background:getComputedStyle(card).backgroundColor};})}));
    assert.equal(desktopLayout.display,'grid');assert.equal(desktopLayout.columns,4);
    assert.ok(desktopLayout.cards.every(card=>card.gap>=4.5),JSON.stringify(desktopLayout));
    assert.ok(desktopLayout.cards.every(card=>card.background==='rgb(255, 255, 255)'));
    assert.equal(desktopLayout.cards[0].text,'Letztes erfolgreiches Backup: '+overviewFinishedAt);
    assert.ok(desktopLayout.cards.some(card=>card.text==='Aktueller Vorgang: Backup'));
    assert.ok(desktopLayout.cards.some(card=>card.text==='Freier Speicher am Ziel: 19.53 GiB'));
    for(const id of ['operational-overview','task-monitor'])assert.equal(await page.locator('#'+id+' > .panel-content').evaluate(node=>getComputedStyle(node).backgroundColor),'rgb(255, 255, 255)');
    const disclosure=page.locator('#overview-details'), summary=disclosure.locator('summary');
    assert.equal(await disclosure.evaluate(node=>node.open),false);
    assert.equal(await page.locator('[data-load-action="backup-preview"]').isVisible(),false);
    assert.ok((await page.locator('#operational-overview').boundingBox()).height<250,'Closed desktop overview stays compact');
    await page.locator('#operational-overview').screenshot({path:path.join(temp,'overview-desktop.png')});
    await summary.focus();await page.keyboard.press('Enter');
    await visible(page,'#overview-detail-values');
    assert.match(await page.locator('#overview-detail-values').textContent(),new RegExp(overviewBackupId));
    assert.ok((await page.locator('#overview-detail-values').textContent()).includes('Backup-Ziel: '+overviewTarget));
    assert.ok((await page.locator('#overview-detail-values').textContent()).includes('Vorgangsdatei: '+task));
    assert.equal(await page.locator('[data-load-action="backup-preview"]').isVisible(),true);
    await page.locator('#operational-overview').screenshot({path:path.join(temp,'overview-expanded.png')});
    overviewIssues=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await visible(page,'#overview-last-failure');await visible(page,'#recover-services-form');
    assert.equal(await disclosure.evaluate(node=>node.open),true,'Polling preserves the open disclosure');
    await summary.focus();await page.keyboard.press('Space');
    assert.equal(await disclosure.evaluate(node=>node.open),false);
    assert.match(await page.locator('#overview-last-failure').innerText(),/Letzter protokollierter Fehler: backup-old-failure.log/);
    assert.equal(await page.locator('#recover-services-form').isVisible(),true,'Recovery action must not be hidden in details');
    overviewIssues=false;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.locator('#overview-last-failure').waitFor({state:'hidden'});
    assert.equal(await disclosure.evaluate(node=>node.open),false,'Polling preserves the closed disclosure');
    assert.equal(reportRequests,0,'Opening details must not start expensive checks');
    await page.setViewportSize({width:900,height:1100});
    assert.equal(await page.locator('#overview-values').evaluate(node=>getComputedStyle(node).gridTemplateColumns.split(' ').length),2);
    await page.setViewportSize({width:1440,height:1100});
    await page.evaluate(()=>{for(const sheet of document.styleSheets)sheet.disabled=true;});
    assert.match(await overviewCards.first().innerText(),/Letztes erfolgreiches Backup: 2026-09-01T02:07:27/);
    await page.evaluate(()=>{for(const sheet of document.styleSheets)sheet.disabled=false;});
    receipts.push('Compact overview has four primary values, keyboard-accessible details and complete IDs/paths; polling preserves disclosure state');
    receipts.push('Last failure and pending service recovery remain visible with details closed; expanding never runs checks');
    assert.equal(await page.locator('#task-history').inputValue(),task);receipts.push('Running task discovered without URL');
    taskPhase='retention';
    await page.waitForFunction(()=>document.querySelector('#task-heartbeat').textContent.includes('Aufbewahrung prüfen und alte Backups bereinigen'));
    assert.match(await page.locator('#task-state').textContent(),/läuft/);
    receipts.push('Retention displays its own readable phase and remains running until backend completion');
    await page.locator('[name="metadata_mode"][value="network-compatible"]').check();await visible(page,'#settings-change-popup');
    const postBefore=postCount;await page.locator('.topbar-actions button[type="submit"]').click();assert.equal(postCount,postBefore);assert.match(await page.locator('#action-feedback').textContent(),/Zuerst Änderungen speichern/);receipts.push('Dirty profile blocks backup until explicitly saved');
    await page.locator('#backup-root-input').fill('/fixture/edited');
    await page.locator('.stop-target-panel').evaluate(node=>node.open=true);await page.locator('[name="stop_targets"]').uncheck();
    await page.locator('#settings-change-toggle').click();assert.match(await page.locator('#settings-change-list').textContent(),/Zu stoppende Dienste/);
    await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Simulierter Speicherfehler'));
    assert.equal(await page.locator('#backup-root-input').inputValue(),'/fixture/edited');assert.equal(await page.locator('[name="stop_targets"]').isChecked(),false);assert.equal(await page.locator('[name="metadata_mode"][value="network-compatible"]').isChecked(),true);receipts.push('Failed AJAX save preserves text/radio/asynchronously loaded checkbox edits');
    const htmlBefore=htmlCount;taskFinished=true;
    await page.locator('#task-log').evaluate(node=>{node.scrollTop=100;node.scrollLeft=120;node.dispatchEvent(new Event('scroll'));});
    const scrollBefore=await page.locator('#task-log').evaluate(node=>({top:node.scrollTop,left:node.scrollLeft,wrap:getComputedStyle(node).whiteSpace,width:node.clientWidth,scrollWidth:node.scrollWidth}));
    assert.equal(scrollBefore.wrap,'pre');assert.ok(scrollBefore.scrollWidth>scrollBefore.width);assert.ok(scrollBefore.left>0);
    await page.waitForFunction(()=>document.querySelector('#task-state').textContent.includes('abgeschlossen'),{},{timeout:15000});
    assert.equal(htmlCount,htmlBefore);assert.equal(await page.locator('#backup-root-input').inputValue(),'/fixture/edited');
    const scrollAfter=await page.locator('#task-log').evaluate(node=>({top:node.scrollTop,left:node.scrollLeft}));assert.equal(scrollAfter.top,scrollBefore.top);assert.equal(scrollAfter.left,scrollBefore.left);receipts.push('Task completion preserves draft and both log scroll axes; no navigation');
    failSave=false;const tokenBefore=tokenNumber;await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Einstellungen gespeichert'));
    assert.ok(tokenNumber>tokenBefore);assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');receipts.push('Every POST uses refreshed CSRF token; successful save establishes clean baseline');
    tokenDelay=350;saveDelay=500;await page.locator('#backup-root-input').fill('/fixture/B');
    await page.locator('#settings-change-popup button[type="submit"]').click();
    await page.locator('#backup-root-input').fill('/fixture/C');
    await page.waitForRequest(request=>request.method()==='POST'&&request.url().includes('save-config'));
    await page.locator('#backup-root-input').fill('/fixture/B');
    await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Währenddessen geänderte'));
    assert.equal(lastSavedPath,'/fixture/C');assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'false');receipts.push('Delayed CSRF / in-flight edits use exact submitted baseline, never false clean');
    tokenDelay=0;saveDelay=0;await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Einstellungen gespeichert'));
    await page.locator('[name="metadata_mode"][value="portable-archive"]').check();const incompatiblePosts=postCount;await page.locator('#settings-change-popup button[type="submit"]').click();assert.equal(postCount,incompatiblePosts);assert.match(await page.locator('#action-feedback').textContent(),/Portable Archive/);
    await page.locator('[name="metadata_mode"][value="network-compatible"]').check();
    await page.locator('[name="schedule_enabled"]').check();await page.locator('[name="schedule_mode"][value="weekly"]').check();await page.locator('[data-schedule-panel="weekly"]').evaluate(node=>node.open=true);await page.locator('[name="schedule_weekdays"][value="1"]').uncheck();await page.locator('#settings-change-popup button[type="submit"]').click();assert.equal(postCount,incompatiblePosts);assert.match(await page.locator('#action-feedback').textContent(),/Wochentag/);
    await page.locator('[name="schedule_enabled"]').uncheck();await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Einstellungen gespeichert'));receipts.push('Incompatible portable snapshot and empty weekly schedule rejected before POST');
    await page.locator('#backup-list-body .operation-form button').click();await visible(page,'#verification-download');assert.match(await page.locator('#operation-result').textContent(),/Dateien stimmen/);
    const downloadEvent=page.waitForEvent('download');await page.locator('#verification-download').click();const downloaded=await downloadEvent;
    assert.equal(downloaded.suggestedFilename(),'fixture-ok-verification.json');await downloaded.saveAs(path.join(temp,'verification-report.json'));
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(temp,'verification-report.json'),'utf8')),verificationReport);receipts.push('Verification JSON report renders and downloads identical content');
    await page.locator('.restore-test-record').evaluate(node=>node.open=true);
    await page.locator('.restore-test-form [name="result"]').selectOption('passed');await page.locator('.restore-test-form [name="tested_at"]').fill('2026-09-12T10:30');await page.locator('.restore-test-form [name="note"]').fill('Rescue-Test in separater Testumgebung; eigene Beobachtung.');
    await page.locator('.restore-test-form button').click();await page.waitForFunction(()=>document.querySelector('#operation-result').textContent.includes('Persönlich dokumentierter Restore-Test: Erfolgreich'));
    assert.match(await page.locator('#operation-result').textContent(),/Vom Plugin nicht überprüft/);assert.match(await page.locator('#operation-result').textContent(),/Rescue-Test in separater/);assert.match(await page.locator('#operation-result').textContent(),/keine Restore-Freigaben/);
    await page.locator('#backup-list-body .operation-form button').click();await visible(page,'#verification-download');assert.match(await page.locator('#operation-result').textContent(),/Persönlich dokumentierter Restore-Test: Erfolgreich/);receipts.push('External restore test recorded with UTC date and displayed only as manual evidence');
    await summary.click();await page.locator('[data-load-action="backup-preview"]').click();await page.waitForFunction(()=>document.querySelector('#operation-result').textContent.includes('vollständige Basiskopie'));
    await summary.click();assert.equal(await page.locator('#operation-result').isVisible(),true,'Loaded results remain visible when details close');
    await page.screenshot({path:path.join(temp,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.locator('#operational-overview').scrollIntoViewIfNeeded();
    const mobileOverview=await page.locator('#overview-values').evaluate(node=>({columns:getComputedStyle(node).gridTemplateColumns.split(' ').length,cards:Array.from(node.children).map(card=>{const title=card.querySelector('.overview-label').getBoundingClientRect(),value=card.querySelector('.overview-value').getBoundingClientRect();return {gap:value.top-title.bottom,right:card.getBoundingClientRect().right};})}));
    assert.equal(mobileOverview.columns,1);assert.ok(mobileOverview.cards.every(card=>card.gap>=4.5&&card.right<=392),JSON.stringify(mobileOverview));
    await page.locator('#operational-overview').screenshot({path:path.join(temp,'overview-mobile.png')});
    await summary.click();
    assert.ok(await page.locator('#overview-detail-values').evaluate(node=>Array.from(node.children).every(child=>child.getBoundingClientRect().right<=392)));
    await page.locator('#operational-overview').screenshot({path:path.join(temp,'overview-mobile-expanded.png')});
    receipts.push('Responsive overview has four/two/one columns; expanded mobile details keep full long backup paths inside the viewport');
    await page.locator('#backup-list-body .info-button').click();
    const tip=await page.locator('#backup-list-body .info-bubble').boundingBox();assert.ok(tip.x>=0&&tip.x+tip.width<=392);
    assert.equal(await page.locator('#backup-list-body td').first().evaluate(node=>getComputedStyle(node,'::before').content),'"ID"');
    const overflow=await page.evaluate(()=>({width:window.innerWidth,scroll:document.documentElement.scrollWidth,nodes:Array.from(document.querySelectorAll('body *')).filter(node=>{const r=node.getBoundingClientRect();return r.right>window.innerWidth+2&&r.width>0&&getComputedStyle(node).position!=='absolute';}).slice(0,12).map(node=>({tag:node.tagName,id:node.id,cls:node.className,width:node.getBoundingClientRect().width,right:node.getBoundingClientRect().right}))}));
    assert.ok(overflow.scroll<=overflow.width+2,JSON.stringify(overflow));
    await page.screenshot({path:path.join(temp,'mobile.png'),fullPage:true});receipts.push('Mobile labels, delegated tooltip inside viewport and no page overflow');
    await page.keyboard.press('Escape');assert.equal(await page.locator('#backup-list-body .info-button').getAttribute('aria-expanded'),'false');
    assert.deepEqual(errors,[]);
    const result={status:'passed',tests:receipts,artifacts:temp,renderer:'actual CGI with mocked backend; read-only mount discovery',browser:await browser.version()};
    fs.writeFileSync(path.join(temp,'receipt.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
