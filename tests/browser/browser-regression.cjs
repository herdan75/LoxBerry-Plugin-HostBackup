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
const cgiSource=fs.readFileSync(path.join(repo,'webfrontend/htmlauth/index.cgi'),'utf8');
const sourceValidator=cgiSource.match(/^sub source_selection_json \{[\s\S]*?^\}/m)[0];
const validatorProgram='use strict; use warnings; use JSON::PP;\n'+sourceValidator+'\n'+String.raw`
my $valid = source_selection_json('{"policy":"local","overrides":{"/media/usb/data":true,"/media/smb/nas":false}}');
my $decoded = decode_json($valid); die "source JSON values changed" unless $decoded->{overrides}{'/media/usb/data'} && !$decoded->{overrides}{'/media/smb/nas'};
for my $bad ('{}', '{"policy":"all","overrides":{}}', '{"policy":"local","overrides":{"/mnt":1}}', '{"policy":"local","overrides":{"/":true}}', '{"policy":"local","overrides":{"/mnt/../secret":true}}', '{"policy":"local","overrides":{"/mnt//nas":true}}', '{"policy":"local","overrides":{"/mnt/nas/":true}}', '{"policy":"local","overrides":{},"extra":true}') {
  eval { source_selection_json($bad) }; die "invalid source JSON accepted: $bad" unless $@;
}
print "CGI source selection validator passed\n";
`;
if(process.platform==='win32')execFileSync('C:/Program Files/Git/bin/bash.exe',['-s'],{cwd:repo,input:`perl -e ${quote(validatorProgram)}\n`,encoding:'utf8'});
else execFileSync('perl',['-e',validatorProgram],{cwd:repo,encoding:'utf8'});
let html;
if (process.platform === 'win32') {
  html = execFileSync('C:/Program Files/Git/bin/bash.exe', ['-s'], {cwd:repo, input:`PERL5LIB=${quote(perlLib)} LBPDATADIR=${quote(posix(temp))} REQUEST_METHOD=GET REMOTE_USER=fixture HTTP_USER_AGENT=fixture perl -MHostBackupFixture webfrontend/htmlauth/index.cgi\n`, encoding:'utf8'});
} else html = execFileSync('perl',['-MHostBackupFixture','webfrontend/htmlauth/index.cgi'], {cwd:repo,env:{...process.env, PERL5LIB:perlLib,LBPDATADIR:temp,REQUEST_METHOD:'GET',REMOTE_USER:'fixture',HTTP_USER_AGENT:'fixture'},encoding:'utf8'});
// Exercise the real lazy backup-row CGI renderer, not hand-maintained action
// markup. Only its list response and GET action are overridden in this process.
const backupFixture=[{backup_id:'fixture-ok',status:'complete',validation:{status:'ok'},host:{hostname:'fixture'},size_bytes:3221225472,files_count:100,finished_at:'2026-09-13T12:00:00Z',storage_format:'directory',export_status:'missing'}];
backupFixture.push({...backupFixture[0],backup_id:'fixture-second',host:{hostname:'second-fixture'}});
const backupRow='#backup-list-body tr:has([name="backup_id"][value="fixture-ok"])';
const backupRowsProgram=`BEGIN { require HostBackupFixture; require CGI; my $original=\\&CORE::GLOBAL::readpipe; no warnings 'redefine'; *CORE::GLOBAL::readpipe=sub { my ($command)=@_; if ($command =~ /'list'\\s+2>&1$/) { $?=0; return ${quote(JSON.stringify(backupFixture))}; } return $original->(@_); }; *CGI::param=sub { return ($_[1] || '') eq 'action' ? 'backup-list' : ''; }; } do './webfrontend/htmlauth/index.cgi'; die $@ if $@;`;
let backupRows;
if(process.platform==='win32')backupRows=execFileSync('C:/Program Files/Git/bin/bash.exe',['-s'],{cwd:repo,input:`PERL5LIB=${quote(perlLib)} LBPDATADIR=${quote(posix(temp))} REQUEST_METHOD=GET REMOTE_USER=fixture HTTP_USER_AGENT=fixture perl -e ${quote(backupRowsProgram)}\n`,encoding:'utf8'});
else backupRows=execFileSync('perl',['-e',backupRowsProgram],{cwd:repo,env:{...process.env,PERL5LIB:perlLib,LBPDATADIR:temp,REQUEST_METHOD:'GET',REMOTE_USER:'fixture',HTTP_USER_AGENT:'fixture'},encoding:'utf8'});
assert.match(backupRows,/<details class="backup-extra-actions">/);assert.match(backupRows,/value="fixture-ok"/);
assert.match(html,/value="\/fixture\/backup"/);
assert.doesNotMatch(html,/Speichern und Backup-Start bleiben gesperrt/);
assert.match(html, /<!doctype html><html><head>/);
const assetUrls = {};
const savedSources={overrides:{'/media/smb/disconnected':true},policy:'legacy'};
html=html.replace(/(id="source-selection-json" name="source_selection_json" value=")[^"]*(")/,(_,before,after)=>before+JSON.stringify(savedSources).replace(/"/g,'&quot;')+after);
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
let lastSavedSources, failSources=false, failBackupMetadata=false;
const probe={status:'error',mode:'network-compatible',message:'Der Test kann Eigentümer nicht erhalten.',checks:[{name:'Eigentümer und Rechte',status:'error',details:'CIFS erzwingt feste Rechte.',expected:'0:0 640',actual:'1000:1000 666',exit_code:23,stderr:'rsync: <img src=x onerror="window.unsafeProbe=true"> Operation not permitted'},{name:'xattrs',status:'skipped',details:'Bewusst ausgelassen.'}],advice:['Mount-Einstellungen prüfen oder Portable Archive mit Vollbackup und Offline-Restore verwenden.']};
const sourceVolumes=[{path:'/',kind:'system',fstype:'ext4',included:true,selectable:false,reason:'Systemdaten'},{path:'/media/usb',kind:'automount',fstype:'autofs',included:true,selectable:false,reason:'Automount-Bereich; einzelne Laufwerke auswählen'},{path:'/media/usb/data',kind:'local',fstype:'ext4',included:true,selectable:true},{path:'/media/usb/network',kind:'network',fstype:'cifs',included:true,selectable:true},{path:'/media/smb/nas',kind:'network',fstype:'cifs',included:true,selectable:true},{path:'/fixture/backup',kind:'local',fstype:'ext4',included:false,selectable:false,forced_excluded:true,reason:'Backup-Ziel'}];
sourceVolumes.push(...Array.from({length:72},(_,index)=>({path:'/var/lib/docker/overlay2/'+('mount-'+index+'-').repeat(3)+'/merged',kind:'local',fstype:'overlay',included:true,selectable:true})));
sourceVolumes.push(...['/proc','/sys','/dev','/run'].map(mount=>({path:mount,kind:'system',fstype:'tmpfs',included:false,selectable:false,forced_excluded:true,reason:'System-Sonderverzeichnis'})));
sourceVolumes.push(...['/opt/loxberry/log/plugins','/opt/loxberry/log/ramlog','/opt/loxberry/log/system_tmpfs'].map(mount=>({path:mount,kind:'local',fstype:'tmpfs',included:true,selectable:true})));
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
      if(action==='save-config') { lastSavedPath=params.get('backup_root');lastSavedSources=JSON.parse(params.get('source_selection_json')); await new Promise(resolve=>setTimeout(resolve,saveDelay)); return json(res,failSave?{ok:false,error:'Simulierter Speicherfehler'}:{ok:true,message:'Gespeichert'},failSave?400:200); }
      if(action==='backup'&&failBackupMetadata)return json(res,{ok:false,error:'Backup nicht gestartet: Metadatenprüfung fehlgeschlagen.',preflight:{status:'error',checks:[{name:'Metadaten-Modus',ok:false,value:'network-compatible'}],metadata_probe:probe},metadata_probe:probe},400);
      if(action==='record-restore-test') {
        assert.equal(params.get('backup_id'),'fixture-ok');assert.equal(params.get('result'),'passed');assert.match(params.get('tested_at'),/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
        const entry={result:params.get('result'),tested_at:params.get('tested_at'),note:params.get('note'),recorded_at:'2026-09-13T12:00:00Z',source:'manual-user-report',manifest_sha256:'fixture-hash',applies_to_current_manifest:true};
        Object.assign(verificationReport,{restore_tested:true,restore_test:entry,restore_test_history:[entry],restore_test_evidence:'manual-user-report'});
        return json(res,{ok:true,message:'Persönlicher Testeintrag gespeichert.',data:verificationReport});
      }
      return json(res,{ok:true,redirect:'?active_task='+task});
    }
    if(action==='csrf-token'){await new Promise(resolve=>setTimeout(resolve,tokenDelay));return json(res,{csrf_token:'fresh-'+(++tokenNumber),expires_at:Date.now()/1000+3600});}
    if(action==='source-info')return json(res,failSources?{ok:false,error:'Mountliste momentan nicht erreichbar'}:{selection:savedSources,volumes:sourceVolumes,notices:['Netzfreigaben bewusst auswählen.']},failSources?500:200);
    if(action==='task-overview')return json(res,{tasks:[{task,state:taskFinished?'finished':'running'}],active_task:taskFinished?null:task,last_success:{backup_id:overviewBackupId,finished_at:overviewFinishedAt},next_run:{local:'14.09.2026 02:00'},last_failure:overviewIssues?{task:'backup-old-failure.log',state:'failed'}:null,pending_service_recovery:overviewIssues?1:0,target:{configured:true,readable:true,path:overviewTarget,available_mb:20000}});
    if(['backup-preview','storage-info','runtime-cleanup-preview','diagnostics','inspect-backup','verification-report','recovery-sheet'].includes(action))reportRequests++;
    if(action==='task-status'){statusCount++;return json(res,{state:taskFinished?'finished':'running',phase:taskFinished?'complete':taskPhase,now:100,mtime:99,content_b64:Buffer.from(longLog()).toString('base64')});}
    if(action==='target-notice'){res.end('<section class="inline-notice">Fixture-Ziel verfügbar</section>');return;}
    if(action==='backup-list'){res.end(backupRows);return;}
    if(action==='stop-targets'){await new Promise(resolve=>setTimeout(resolve,100));res.end('<input type="hidden" name="stop_targets_loaded" value="1"><label><input type="checkbox" name="stop_targets" value="systemd:test.service" checked>Testdienst</label><button type="button" data-stop-target-preset="none">Keine Dienste</button>');return;}
    if(action==='backup-preview')return json(res,{saved_config:true,backup_mode:'snapshot',metadata_mode:'network-compatible',full_baseline_required:true,excludes:['/fixture/backup/***'],source_volumes:[{path:'/',included:true,reason:'System'}],available_mb:20000,baseline_estimate_mb:3000,metadata_probe:probe});
    if(action==='verification-report')return json(res,verificationReport);
    if(url.pathname==='/system/images/icons/loxberryhostbackup/icon_64.png'){res.writeHead(200,{'Content-Type':'image/png'});res.end(fs.readFileSync(path.join(repo,'icons/icon_64.png')));return;}
    if(url.pathname.startsWith('/system/')){res.writeHead(204);res.end();return;}
    htmlCount++;res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(html);
  }catch(error){errors.push(error.message);json(res,{error:error.message},500);}
});
async function visible(page,selector){await page.locator(selector).waitFor({state:'visible'});}
async function sourceTypographyFailures(page){
  return page.locator('#source-selection-panel').evaluate(node=>Array.from(node.querySelectorAll('p,summary')).map(item=>{const style=getComputedStyle(item);return {tag:item.tagName,text:item.textContent.slice(0,90),size:parseFloat(style.fontSize),weight:parseInt(style.fontWeight,10),spacing:style.letterSpacing};}).filter(item=>item.size>(item.tag==='SUMMARY'?15:14)||item.weight>(item.tag==='SUMMARY'?700:400)||!['normal','0px'].includes(item.spacing)));
}
async function checkSourceHelp(page,viewportName){
  const legend=page.locator('#source-selection-legend'),button=legend.locator('.info-button'),bubble=legend.locator('.info-bubble');
  const selectionBefore=await page.locator('#source-selection-json').inputValue(),dirtyBefore=await page.locator('#settings-change-popup').getAttribute('aria-hidden'),postsBefore=postCount;
  assert.equal(await button.count(),1,'Data sources use the same single info button as the other setting groups');
  assert.equal(await button.getAttribute('type'),'button');
  assert.ok(await button.getAttribute('aria-label'),'Info button has an accessible name');
  assert.equal(await button.getAttribute('aria-describedby'),await bubble.getAttribute('id'),'Help text is associated with its trigger for assistive technology');
  const helpText=await bubble.textContent();
  for(const topic of ['Backup-Ziel','Metadaten-Profil','USB','Automount','speichern'])assert.ok(helpText.includes(topic),'Source help explains '+topic);
  await button.evaluate(node=>node.scrollIntoView({block:'center'}));
  await button.click();
  assert.equal(await button.getAttribute('aria-expanded'),'true');
  assert.equal(await bubble.getAttribute('role'),'tooltip');
  await visible(page,'#source-selection-legend .info-bubble');
  const geometry=await bubble.evaluate(node=>{const rect=node.getBoundingClientRect(),style=getComputedStyle(node);return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,width:window.innerWidth,height:window.innerHeight,client:node.clientHeight,scroll:node.scrollHeight,overflow:style.overflowY,whiteSpace:style.whiteSpace,fontSize:parseFloat(style.fontSize),weight:parseInt(style.fontWeight,10),spacing:style.letterSpacing};});
  assert.ok(geometry.left>=-1&&geometry.right<=geometry.width+1&&geometry.top>=-1&&geometry.bottom<=geometry.height+1,viewportName+': full help stays within viewport '+JSON.stringify(geometry));
  assert.ok(geometry.fontSize<=14&&geometry.weight<=400&&['normal','0px'].includes(geometry.spacing),viewportName+': tooltip is normal setting copy, not host-theme heading text '+JSON.stringify(geometry));
  assert.equal(geometry.whiteSpace,'pre-line','Paragraph breaks remain readable without interpreting HTML');
  if(geometry.scroll>geometry.client+1){
    await bubble.focus();await page.keyboard.press('Home');
    await page.waitForFunction(()=>document.querySelector('#source-selection-legend .info-bubble').scrollTop===0);
  }
  await page.screenshot({path:path.join(temp,'source-help-'+viewportName+'.png')});
  if(geometry.scroll>geometry.client+1){
    assert.ok(['auto','scroll'].includes(geometry.overflow),'Long help must be scrollable');
    await bubble.focus();await page.keyboard.press('End');
    await page.waitForFunction(()=>{const node=document.querySelector('#source-selection-legend .info-bubble');return node.scrollTop>=node.scrollHeight-node.clientHeight-2;});
    await page.screenshot({path:path.join(temp,'source-help-'+viewportName+'-scrolled.png')});
  }
  await page.keyboard.press('Escape');
  assert.equal(await button.getAttribute('aria-expanded'),'false');
  await page.mouse.move(1,1);await bubble.waitFor({state:'hidden'});
  await button.focus();await page.keyboard.press('Enter');
  assert.equal(await button.getAttribute('aria-expanded'),'true','Source help can be opened by keyboard');
  await page.keyboard.press('Escape');await page.mouse.move(1,1);await bubble.waitFor({state:'hidden'});
  assert.equal(await page.locator('#source-selection-json').inputValue(),selectionBefore,'Reading source help never changes selection');
  assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),dirtyBefore,'Reading source help never changes dirty state');
  assert.equal(postCount,postsBefore,'Reading source help never saves or starts a backup');
}
async function checkActionHelp(page,key,viewportName,expectedTopics=[],saveScreenshot=false){
  const id='help-'+key,bubble=page.locator('[id="'+id+'"]'),button=page.locator('.info-button[aria-describedby="'+id+'"]');
  assert.equal(await button.count(),1,'Actual CGI action has one contextual info button: '+key);
  assert.equal(await button.getAttribute('type'),'button');assert.ok(await button.getAttribute('aria-label'));
  assert.equal(await bubble.getAttribute('role'),'tooltip');assert.equal(await bubble.getAttribute('tabindex'),'0');
  const helpText=await bubble.textContent();assert.ok(helpText.length>=60,'Context help is explanatory: '+key);
  for(const topic of expectedTopics)assert.match(helpText,topic,key+' explains its scope and limits');
  const stateBefore=await page.evaluate(()=>Array.from(document.querySelectorAll('#settings-save-form [name],#maintenance-settings-form [name]')).map(node=>[node.name,node.value,node.checked||false]));
  const dirtyBefore=await page.locator('#settings-change-popup').getAttribute('aria-hidden'),postsBefore=postCount,reportsBefore=reportRequests;
  const detailsBefore=await button.evaluate(node=>{const details=node.closest('details');return details?details.open:null;});
  await button.evaluate(node=>node.scrollIntoView({block:'center'}));await button.click();
  assert.equal(await button.getAttribute('aria-expanded'),'true');
  assert.equal(await button.evaluate(node=>{const details=node.closest('details');return details?details.open:null;}),detailsBefore,'Info clicks must not toggle their details container: '+key);
  const bounds=await bubble.evaluate(node=>{const rect=node.getBoundingClientRect();return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,width:window.innerWidth,height:window.innerHeight};});
  assert.ok(bounds.left>=-1&&bounds.right<=bounds.width+1&&bounds.top>=-1&&bounds.bottom<=bounds.height+1,viewportName+' '+key+' tooltip stays in viewport '+JSON.stringify(bounds));
  if(saveScreenshot)await page.screenshot({path:path.join(temp,'action-help-'+key+'-'+viewportName+'.png')});
  // Reading/copying tooltip text inside a label or summary must not activate its
  // native checkbox/disclosure default action either.
  await bubble.click({position:{x:12,y:12}});
  assert.equal(await button.evaluate(node=>{const details=node.closest('details');return details?details.open:null;}),detailsBefore,'Clicking help text must not toggle its details container: '+key);
  await page.keyboard.press('Escape');await page.mouse.move(1,1);await bubble.waitFor({state:'hidden'});
  assert.equal(await button.getAttribute('aria-expanded'),'false');
  assert.equal(postCount,postsBefore,'Info button must not POST: '+key);assert.equal(reportRequests,reportsBefore,'Info button must not run a report: '+key);
  assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),dirtyBefore,'Reading help never changes dirty state: '+key);
  assert.deepEqual(await page.evaluate(()=>Array.from(document.querySelectorAll('#settings-save-form [name],#maintenance-settings-form [name]')).map(node=>[node.name,node.value,node.checked||false])),stateBefore,'Info inside labels must not toggle any settings: '+key);
}
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
    await page.locator('#source-selection-panel').evaluate(node=>node.open=true);
    await page.waitForFunction(()=>!document.querySelector('#source-policy').disabled);
    assert.deepEqual(await page.locator('#source-policy option').evaluateAll(options=>options.map(node=>({value:node.value,label:node.textContent}))),[
      {value:'local',label:'Lokale Laufwerke; Netzfreigaben einzeln (empfohlen)'},
      {value:'legacy',label:'Alle eingebundenen Laufwerke und Netzfreigaben'},
    ],'Scope labels are meaningful on a first install; persisted policy values remain unchanged');
    assert.equal(await page.locator('#source-policy').inputValue(),'legacy','Existing missing-key fixture remains legacy; help/labels do not migrate settings');
    assert.doesNotMatch(await page.locator('#source-selection-summary').textContent(),/bisherig/i);
    assert.doesNotMatch(await page.locator('#source-policy-note').textContent(),/Bisheriges Verhalten|Bisherige Grundregel|Bisheriger Umfang/i);
    await checkSourceHelp(page,'desktop');
    receipts.push('Data-source labels describe both policies explicitly; desktop info tooltip is accessible, bounded and cannot alter saved settings');
    const typographyFailures=await sourceTypographyFailures(page);
    if(typographyFailures.length) {
      await page.locator('#source-selection-panel').screenshot({path:path.join(temp,'source-typography-regression.png')});
      const reproduction={status:'failed',reason:'Source typography inherits global host theme',failures:typographyFailures,artifacts:temp};
      fs.writeFileSync(path.join(temp,'source-typography-reproduction.json'),JSON.stringify(reproduction,null,2));console.log(JSON.stringify(reproduction,null,2));
    }
    assert.deepEqual(typographyFailures,[],'Source copy must remain <=14px/normal weight and summaries <=15px/700, with normal letter spacing despite global host-theme rules');
    const paragraphStress=await page.addStyleTag({content:'p, summary {font-size:50px;font-weight:700;letter-spacing:4px;}'});
    assert.deepEqual(await sourceTypographyFailures(page),[],'Source typography also resists a separate late-loaded global element-rule stress case');
    await paragraphStress.evaluate(node=>node.remove());
    receipts.push('Source typography overrides real LoxBerry 4.0.0.15 wide-class inheritance and a separate late-loaded paragraph/summary stress case');
    const technicalDetails=page.locator('#source-technical-details'),technicalList=page.locator('#source-technical-list'),mainSources=page.locator('#source-volume-list');
    assert.equal(await technicalDetails.evaluate(node=>node.open),false,'Technical sources are closed initially');
    assert.ok(await technicalList.locator('.source-volume').count()>=80,'Fixture includes a realistic long system/Docker mount inventory');
    for(const requiredPath of ['/','/media/usb/data','/media/smb/nas','/media/smb/disconnected'])assert.equal(await mainSources.locator('[data-source-path="'+requiredPath+'"]').count(),1,'Important source must remain outside technical disclosure: '+requiredPath);
    assert.equal(await mainSources.locator('[data-source-path*="/overlay2/"]').count(),0,'Unmodified container mounts belong in the technical group');
    const compactSourceDesktop=await page.locator('#source-selection-panel').evaluate(node=>({height:node.getBoundingClientRect().height,mainHeight:node.querySelector('#source-volume-list').getBoundingClientRect().height}));
    assert.ok(compactSourceDesktop.height<900&&compactSourceDesktop.mainHeight<=422,JSON.stringify(compactSourceDesktop));
    const cleanSourceState=await page.locator('#source-selection-json').inputValue();
    await technicalDetails.locator('summary').focus();await page.keyboard.press('Enter');
    assert.equal(await technicalDetails.evaluate(node=>node.open),true);
    const technicalBounds=await technicalList.evaluate(node=>({height:node.getBoundingClientRect().height,scrollHeight:node.scrollHeight,overflow:getComputedStyle(node).overflowY}));
    assert.ok(technicalBounds.height<=322&&technicalBounds.scrollHeight>technicalBounds.height&&['auto','scroll'].includes(technicalBounds.overflow),JSON.stringify(technicalBounds));
    await page.locator('#source-selection-reload').click();await page.waitForFunction(()=>!document.querySelector('#source-selection-reload').disabled);
    assert.equal(await technicalDetails.evaluate(node=>node.open),true,'Inventory refresh must preserve the open technical disclosure');
    assert.equal(await page.locator('#source-selection-json').inputValue(),cleanSourceState,'Opening/refreshing technical rows must not edit configuration');
    const technicalPath=sourceVolumes.find(item=>item.fstype==='overlay').path;
    assert.equal(await technicalList.locator('[data-source-path="'+technicalPath+'"]').isChecked(),true);
    // A real click intentionally moves this row out of the technical group;
    // uncheck() would keep resolving the obsolete group-scoped locator.
    await technicalList.locator('[data-source-path="'+technicalPath+'"]').click();
    assert.equal(await mainSources.locator('[data-source-path="'+technicalPath+'"]').isChecked(),false,'A conscious technical override moves into the primary list');
    assert.equal(await technicalDetails.evaluate(node=>node.open),true,'Editing a technical source must preserve disclosure state');
    await mainSources.locator('[data-source-reset="'+technicalPath+'"]').click();
    assert.equal(await technicalList.locator('[data-source-path="'+technicalPath+'"]').isChecked(),true,'Reset restores the inherited selection and technical grouping');
    assert.equal(await page.locator('#source-selection-json').inputValue(),cleanSourceState);
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    await technicalDetails.locator('summary').focus();await page.keyboard.press('Space');
    assert.equal(await technicalDetails.evaluate(node=>node.open),false);
    receipts.push('Large mount inventories stay compact; technical disclosure is keyboard-operable, bounded and state-preserving, while important and deliberately overridden sources remain primary');
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
    assert.equal(await page.locator('#backup-list-body .backup-extra-actions').count(),2,'Real CGI fixture includes two completed backup rows');
    const extraActions=page.locator(backupRow+' .backup-extra-actions');await extraActions.evaluate(node=>node.open=true);
    const actionTopics=[['inspect-backup',[/Manifest/,/keine Prüfsummen/]],['verify-backup',[/SHA-256/,/Vergleichsbasis/,/Restore-Test/]],['verification-report',[/keine neue Prüfung/,/JSON/]],['recovery-sheet',[/keinen Restore/,/Bootloader/]],['protect-backup',[/ausserhalb/,/Datenträger/]]];
    for(const [action,topics] of actionTopics){
      await checkActionHelp(page,action+'-fixture-ok','desktop',topics,action==='verify-backup');
      const submit=page.locator(backupRow+' form:has([name="action"][value="'+action+'"]) button[type="submit"]');
      assert.equal(await submit.isVisible(),true);assert.equal(await submit.isEnabled(),true,'Actual action remains enabled next to help: '+action);
      assert.equal(await page.locator('.info-button[aria-describedby="help-'+action+'-fixture-second"]').count(),1,'Second backup has independently associated contextual help: '+action);
    }
    assert.equal(await page.locator(backupRow+' .restore-test-record').evaluate(node=>node.open),false);
    await checkActionHelp(page,'record-restore-test-fixture-ok','desktop',[/kein Restore gestartet/,/persönliche/]);
    assert.equal(await page.locator(backupRow+' .restore-test-record').evaluate(node=>node.open),false,'Summary info does not open the restore-test form');
    const maintenance=page.locator('.maintenance-card');await maintenance.evaluate(node=>node.open=true);
    await checkActionHelp(page,'integrity-enabled','desktop',[/Standard: aus/,/Vergleichsbasis/]);await maintenance.evaluate(node=>node.open=false);
    await disclosure.evaluate(node=>node.open=true);await checkActionHelp(page,'backup-preview','desktop',[/gespeicherten Einstellungen/,/kein Backup/]);await disclosure.evaluate(node=>node.open=false);
    const helpIds=await page.locator('.info-bubble[id]').evaluateAll(nodes=>nodes.map(node=>node.id));assert.equal(new Set(helpIds).size,helpIds.length,'Context help IDs are unique across actual page and dynamically rendered backup rows');
    receipts.push('Actual CGI backup-action help and overview/maintenance help explain scope without POST, report requests, dirty changes or disclosure/label toggles; adjacent actions stay reachable');
    taskPhase='retention';
    await page.waitForFunction(()=>document.querySelector('#task-heartbeat').textContent.includes('Aufbewahrung prüfen und alte Backups bereinigen'));
    assert.match(await page.locator('#task-state').textContent(),/läuft/);
    receipts.push('Retention displays its own readable phase and remains running until backend completion');
    await page.locator('#source-selection-panel').evaluate(node=>node.open=true);
    await page.waitForFunction(()=>!document.querySelector('#source-policy').disabled);
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true','Loading data sources must not mark saved settings dirty');
    assert.equal(await page.locator('#source-policy').inputValue(),'legacy');
    const nasSource=page.locator('[data-source-path="/media/smb/nas"]'),usbSource=page.locator('[data-source-path="/media/usb/data"]');
    assert.equal(await nasSource.isChecked(),true);assert.equal(await usbSource.isChecked(),true);
    assert.equal(await page.locator('[data-source-path="/media/smb/disconnected"]').isChecked(),true);
    assert.equal(await page.locator('[data-source-path="/fixture/backup"]').isEnabled(),false);
    await page.locator('#source-policy').selectOption('local');await visible(page,'#settings-change-popup');
    assert.match(await page.locator('#settings-change-list').textContent(),/Lokale Laufwerke; Netzfreigaben einzeln/);
    assert.doesNotMatch(await page.locator('#source-selection-summary').textContent(),/bisherig/i);
    assert.doesNotMatch(await page.locator('#settings-change-list').textContent(),/Bisherige Grundregel|Bisheriges Verhalten/i);
    assert.equal(await nasSource.isChecked(),false);assert.equal(await usbSource.isChecked(),true,'Recommended policy must preserve local USB data');
    assert.equal(await page.locator('[data-source-path="/media/usb"]').isChecked(),false,'Autofs container remains excluded');assert.equal(await page.locator('[data-source-path="/media/usb/network"]').isChecked(),false,'Nested network sibling must not follow local USB');
    await page.locator('#source-policy').selectOption('legacy');assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true','Reverting policy restores the exact clean baseline');
    await nasSource.uncheck();await visible(page,'#settings-change-popup');
    assert.match(await page.locator('#settings-change-list').textContent(),/Alle eingebundenen Laufwerke und Netzfreigaben/);
    assert.doesNotMatch(await page.locator('#settings-change-list').textContent(),/Bisherige Grundregel|Bisheriges Verhalten/i);
    const sourceDraft=await page.locator('#source-selection-json').inputValue();
    await page.locator('#source-selection-reload').click();await page.waitForFunction(()=>!document.querySelector('#source-selection-reload').disabled);
    assert.equal(await page.locator('#source-selection-json').inputValue(),sourceDraft,'Reload must not replace draft with saved server selection');
    failSources=true;await page.locator('#source-selection-reload').click();await page.waitForFunction(()=>document.querySelector('#source-selection-notices').textContent.includes('nicht geladen'));
    assert.equal(await nasSource.isChecked(),false);assert.equal(await page.locator('#source-selection-json').inputValue(),sourceDraft);failSources=false;
    receipts.push('Source selection preserves legacy behavior, excludes networks only after explicit policy change, retains USB and unmounted overrides, and survives refresh failures');
    await page.locator('#source-selection-panel').screenshot({path:path.join(temp,'source-selection-desktop.png')});
    assert.equal(await page.locator('.source-volume > label').first().evaluate(node=>getComputedStyle(node).flexDirection),'row');
    await page.locator('[name="metadata_mode"][value="network-compatible"]').check();await visible(page,'#settings-change-popup');
    const postBefore=postCount;await page.locator('.topbar-actions button[type="submit"]').click();assert.equal(postCount,postBefore);assert.match(await page.locator('#action-feedback').textContent(),/Zuerst Änderungen speichern/);receipts.push('Dirty profile blocks backup until explicitly saved');
    await page.locator('#backup-root-input').fill('/fixture/edited');
    await page.locator('.stop-target-panel').evaluate(node=>node.open=true);await page.locator('[name="stop_targets"]').uncheck();
    await page.locator('#settings-change-toggle').click();assert.match(await page.locator('#settings-change-list').textContent(),/Zu stoppende Dienste/);
    await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Simulierter Speicherfehler'));
    assert.equal(await nasSource.isChecked(),false);assert.equal(lastSavedSources.overrides['/media/smb/nas'],false);assert.equal(lastSavedSources.overrides['/media/smb/disconnected'],true);assert.equal(lastSavedSources.policy,'legacy');
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
    failBackupMetadata=true;await page.locator('.topbar-actions button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#operation-result').textContent.includes('CIFS erzwingt feste Rechte'));
    assert.match(await page.locator('#operation-result').textContent(),/0:0 640/);assert.match(await page.locator('#operation-result').textContent(),/1000:1000 666/);assert.match(await page.locator('#operation-result').textContent(),/Offline/);
    assert.equal(await page.locator('#operation-result img').count(),0);assert.equal(await page.evaluate(()=>window.unsafeProbe),undefined);assert.equal(await page.locator('.preflight-confirm').count(),0);
    assert.equal(await page.locator('#operation-result .metadata-probe-check').first().evaluate(node=>node.open),true);failBackupMetadata=false;
    await page.locator('#operation-result').screenshot({path:path.join(temp,'metadata-diagnostics-desktop.png')});
    const profilePosts=postCount;await page.locator('[data-archive-profile-draft]').click();await visible(page,'#settings-change-popup');
    assert.equal(postCount,profilePosts,'Profile assistance must not save or start anything');
    assert.equal(await page.locator('[name="metadata_mode"][value="portable-archive"]').isChecked(),true);assert.equal(await page.locator('[name="backup_mode"][value="full"]').isChecked(),true);
    assert.match(await page.locator('#action-feedback').textContent(),/noch nicht gespeichert/);
    await page.locator('[name="metadata_mode"][value="network-compatible"]').check();await page.locator('[name="backup_mode"][value="snapshot"]').check();
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    receipts.push('Blocked metadata preflight exposes exact failed check, expected/actual values, rsync error and profile advice safely without warning override');
    await page.locator(backupRow+' .backup-extra-actions').evaluate(node=>node.open=true);
    await page.locator(backupRow+' form:has([name="action"][value="verification-report"]) button[type="submit"]').click();await visible(page,'#verification-download');assert.match(await page.locator('#operation-result').textContent(),/Dateien stimmen/);
    const downloadEvent=page.waitForEvent('download');await page.locator('#verification-download').click();const downloaded=await downloadEvent;
    assert.equal(downloaded.suggestedFilename(),'fixture-ok-verification.json');await downloaded.saveAs(path.join(temp,'verification-report.json'));
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(temp,'verification-report.json'),'utf8')),verificationReport);receipts.push('Verification JSON report renders and downloads identical content');
    await page.locator(backupRow+' .restore-test-record').evaluate(node=>node.open=true);
    await page.locator(backupRow+' .restore-test-form [name="result"]').selectOption('passed');await page.locator(backupRow+' .restore-test-form [name="tested_at"]').fill('2026-09-12T10:30');await page.locator(backupRow+' .restore-test-form [name="note"]').fill('Rescue-Test in separater Testumgebung; eigene Beobachtung.');
    await page.locator(backupRow+' .restore-test-form button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#operation-result').textContent.includes('Persönlich dokumentierter Restore-Test: Erfolgreich'));
    assert.match(await page.locator('#operation-result').textContent(),/Vom Plugin nicht überprüft/);assert.match(await page.locator('#operation-result').textContent(),/Rescue-Test in separater/);assert.match(await page.locator('#operation-result').textContent(),/keine Restore-Freigaben/);
    await page.locator(backupRow+' .backup-extra-actions').evaluate(node=>node.open=true);
    await page.locator(backupRow+' form:has([name="action"][value="verification-report"]) button[type="submit"]').click();await visible(page,'#verification-download');assert.match(await page.locator('#operation-result').textContent(),/Persönlich dokumentierter Restore-Test: Erfolgreich/);receipts.push('External restore test recorded with UTC date and displayed only as manual evidence');
    await summary.click();await page.locator('[data-load-action="backup-preview"]').click();await page.waitForFunction(()=>document.querySelector('#operation-result').textContent.includes('vollständige Basiskopie'));
    assert.match(await page.locator('#operation-result .metadata-probe').textContent(),/CIFS erzwingt feste Rechte/);
    await summary.click();assert.equal(await page.locator('#operation-result').isVisible(),true,'Loaded results remain visible when details close');
    await page.screenshot({path:path.join(temp,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await checkSourceHelp(page,'mobile');
    receipts.push('Long data-source help stays within mobile viewport, supports keyboard scrolling and does not change selection or dirty state');
    await page.locator(backupRow+' .backup-extra-actions').evaluate(node=>node.open=true);
    await checkActionHelp(page,'verify-backup-fixture-ok','mobile',[/SHA-256/,/Restore-Test/],true);
    await checkActionHelp(page,'record-restore-test-fixture-ok','mobile',[/kein Restore gestartet/]);
    await page.locator('.maintenance-card').evaluate(node=>node.open=true);await checkActionHelp(page,'integrity-enabled','mobile');await page.locator('.maintenance-card').evaluate(node=>node.open=false);
    receipts.push('Real lazily rendered action tooltips stay in the mobile viewport without toggling forms, settings or disclosure state');
    assert.deepEqual(await sourceTypographyFailures(page),[],'Real mobile wide-class rules must not resize or space source copy');
    const compactSourceMobile=await page.locator('#source-selection-panel').evaluate(node=>({height:node.getBoundingClientRect().height,mainHeight:node.querySelector('#source-volume-list').getBoundingClientRect().height,technicalOpen:node.querySelector('#source-technical-details').open}));
    assert.ok(compactSourceMobile.height<1450&&compactSourceMobile.mainHeight<=422&&!compactSourceMobile.technicalOpen,JSON.stringify(compactSourceMobile));
    await page.locator('#source-selection-panel').screenshot({path:path.join(temp,'source-selection-mobile.png')});
    assert.ok(await page.locator('#source-selection-panel').evaluate(node=>{const right=node.getBoundingClientRect().right;return Array.from(node.querySelectorAll('select,label,strong,small')).every(item=>item.getBoundingClientRect().right<=right+1);}), 'Source controls and descriptions stay inside their mobile panel');
    await page.locator('#operational-overview').scrollIntoViewIfNeeded();
    const mobileOverview=await page.locator('#overview-values').evaluate(node=>({columns:getComputedStyle(node).gridTemplateColumns.split(' ').length,cards:Array.from(node.children).map(card=>{const title=card.querySelector('.overview-label').getBoundingClientRect(),value=card.querySelector('.overview-value').getBoundingClientRect();return {gap:value.top-title.bottom,right:card.getBoundingClientRect().right};})}));
    assert.equal(mobileOverview.columns,1);assert.ok(mobileOverview.cards.every(card=>card.gap>=4.5&&card.right<=392),JSON.stringify(mobileOverview));
    await page.locator('#operational-overview').screenshot({path:path.join(temp,'overview-mobile.png')});
    await summary.click();
    assert.ok(await page.locator('#overview-detail-values').evaluate(node=>Array.from(node.children).every(child=>child.getBoundingClientRect().right<=392)));
    await page.locator('#operational-overview').screenshot({path:path.join(temp,'overview-mobile-expanded.png')});
    receipts.push('Responsive overview has four/two/one columns; expanded mobile details keep full long backup paths inside the viewport');
    await page.locator(backupRow+' .backup-extra-actions').evaluate(node=>node.open=true);
    const mobileActionButton=page.locator('.info-button[aria-describedby="help-inspect-backup-fixture-ok"]');
    await mobileActionButton.click();
    const tip=await page.locator('#help-inspect-backup-fixture-ok').boundingBox();assert.ok(tip.x>=0&&tip.x+tip.width<=392);
    assert.equal(await page.locator('#backup-list-body td').first().evaluate(node=>getComputedStyle(node,'::before').content),'"ID"');
    const overflow=await page.evaluate(()=>({width:window.innerWidth,scroll:document.documentElement.scrollWidth,nodes:Array.from(document.querySelectorAll('body *')).filter(node=>{const r=node.getBoundingClientRect();return r.right>window.innerWidth+2&&r.width>0&&getComputedStyle(node).position!=='absolute';}).slice(0,12).map(node=>({tag:node.tagName,id:node.id,cls:node.className,width:node.getBoundingClientRect().width,right:node.getBoundingClientRect().right}))}));
    assert.ok(overflow.scroll<=overflow.width+2,JSON.stringify(overflow));
    await page.screenshot({path:path.join(temp,'mobile.png'),fullPage:true});receipts.push('Mobile labels, delegated tooltip inside viewport and no page overflow');
    await page.keyboard.press('Escape');assert.equal(await mobileActionButton.getAttribute('aria-expanded'),'false');
    assert.deepEqual(errors,[]);
    const result={status:'passed',tests:receipts,artifacts:temp,renderer:'actual CGI with mocked backend; read-only mount discovery',browser:await browser.version()};
    fs.writeFileSync(path.join(temp,'receipt.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
