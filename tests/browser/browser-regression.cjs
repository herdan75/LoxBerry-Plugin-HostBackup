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
const publicRepositoryStatus=cgiSource.match(/^sub repository_public_status \{[\s\S]*?^\}/m)[0];
const portableSettingsValidator=cgiSource.match(/^sub portable_settings_error \{[\s\S]*?^\}/m)[0];
const validatorProgram='use strict; use warnings; use JSON::PP;\n'+sourceValidator+'\n'+publicRepositoryStatus+'\n'+String.raw`
my $public=repository_public_status({initialized=>JSON::PP::true,key_confirmed=>JSON::PP::false,key_exported=>JSON::PP::true,available=>JSON::PP::true,repository_id=>'fixture',engine_version=>'0.19.1',secret=>'NEVER-PUBLIC',password=>'NEVER-PUBLIC',message=>'NEVER-PUBLIC'});
die "repository status leaks extra fields" unless join(',',sort keys %$public) eq 'available,engine_version,initialized,key_confirmed,key_exported,repository_id';
die "repository status booleans changed" unless $public->{initialized} && !$public->{key_confirmed};
die "truthy string accepted as capability" if repository_public_status({available=>'false'})->{available};
eval { repository_public_status([]) }; die "invalid repository status accepted" unless $@;
my $valid = source_selection_json('{"policy":"local","overrides":{"/media/usb/data":true,"/media/smb/nas":false}}');
my $decoded = decode_json($valid); die "source JSON values changed" unless $decoded->{overrides}{'/media/usb/data'} && !$decoded->{overrides}{'/media/smb/nas'};
for my $bad ('{}', '{"policy":"all","overrides":{}}', '{"policy":"local","overrides":{"/mnt":1}}', '{"policy":"local","overrides":{"/":true}}', '{"policy":"local","overrides":{"/mnt/../secret":true}}', '{"policy":"local","overrides":{"/mnt//nas":true}}', '{"policy":"local","overrides":{"/mnt/nas/":true}}', '{"policy":"local","overrides":{},"extra":true}') {
  eval { source_selection_json($bad) }; die "invalid source JSON accepted: $bad" unless $@;
}
print "CGI source selection validator passed\n";
`;
if(process.platform==='win32')execFileSync('C:/Program Files/Git/bin/bash.exe',['-s'],{cwd:repo,input:`perl -e ${quote(validatorProgram)}\n`,encoding:'utf8'});
else execFileSync('perl',['-e',validatorProgram],{cwd:repo,encoding:'utf8'});
const repositoryHandler=cgiSource.match(/^if \(\$action =~ \/\\Arepository-[\s\S]*?^\}/m)[0];
const repositoryGuardProgram='use strict; use warnings; use JSON::PP;\n'+publicRepositoryStatus+'\n'+String.raw`
{ package Request; sub request_method { $_[0]->{method} } sub param { $_[0]->{$_[1]} || '' } }
my ($action,$q,$ajax_request,$csrf_valid,$root_ack,@calls,$response);
sub reject_request { die 'REJECT:'.$_[0]; }
sub json_response { $response=$_[0]; die 'RESPONSE'; }
sub redirect_with { die 'REDIRECT'; }
sub valid_csrf_request { return $csrf_valid; }
sub backend_cmd { return join(' ',@_); }
sub repository_key_download { push @calls,'SECRET_ATTACHMENT'; die 'DOWNLOAD'; }
sub run_shell { my ($cmd)=@_;push @calls,$cmd;return (0,encode_json({root_permission_ack=>$root_ack?JSON::PP::true:JSON::PP::false})) if $cmd eq 'config';return (0,encode_json({available=>JSON::PP::true,initialized=>JSON::PP::true,key_confirmed=>JSON::PP::false,key_exported=>JSON::PP::false,secret=>'NEVER-PUBLIC'})); }
`+'my $handler=sub {\n'+repositoryHandler+'\n};\n'+String.raw`
sub exercise { my ($a,$method,$csrf,$ack,$confirm)=@_;$action=$a;$q=bless({method=>$method,recovery_key_saved=>$confirm},'Request');$ajax_request=1;$csrf_valid=$csrf;$root_ack=$ack;@calls=();$response=undef;eval {$handler->()};return $@; }
for my $a ('repository-init','repository-key-export','repository-confirm-key') {
 die 'write action accepted GET' unless exercise($a,'GET',1,1,'1') =~ /REJECT:405/ && !@calls;
 die 'write action accepted invalid CSRF' unless exercise($a,'POST',0,1,'1') =~ /REJECT:403/ && !@calls;
 die 'write action accepted missing saved root ack' unless exercise($a,'POST',1,0,'1') =~ /REJECT:403/ && join(',',@calls) eq 'config';
}
die 'key confirmation accepted unchecked acknowledgement' unless exercise('repository-confirm-key','POST',1,1,'') =~ /REJECT:400/ && join(',',@calls) eq 'config';
die 'key download not isolated attachment' unless exercise('repository-key-export','POST',1,1,'') =~ /DOWNLOAD/ && join(',',@calls) eq 'config,SECRET_ATTACHMENT';
die 'status accepted POST' unless exercise('repository-status','POST',1,1,'') =~ /REJECT:405/ && !@calls;
die 'read-only status failed' unless exercise('repository-status','GET',0,0,'') =~ /RESPONSE/ && join(',',@calls) eq 'repository-status' && !exists $response->{secret};
die 'valid init failed' unless exercise('repository-init','POST',1,1,'') =~ /RESPONSE/ && join(',',@calls) eq 'config,repository-init,repository-status' && !exists $response->{data}{secret};
die 'valid key confirmation failed' unless exercise('repository-confirm-key','POST',1,1,'1') =~ /RESPONSE/ && join(',',@calls) eq 'config,repository-confirm-key,repository-status';
print "Actual CGI repository guard cases passed\n";
`;
if(process.platform==='win32')execFileSync('C:/Program Files/Git/bin/bash.exe',['-s'],{cwd:repo,input:`perl -e ${quote(repositoryGuardProgram)}\n`,encoding:'utf8'});
else execFileSync('perl',['-e',repositoryGuardProgram],{cwd:repo,encoding:'utf8'});
const portableSettingsProgram='use strict; use warnings; use JSON::PP;\n'+publicRepositoryStatus+'\n'+portableSettingsValidator+'\n'+String.raw`
my ($repo_status,$config_status,$repo_data,$saved_root,@calls)=(0,0,{},'/fixture/saved');
sub backend_cmd { join(' ',@_) }
sub run_shell { my ($cmd)=@_;push @calls,$cmd;return ($config_status,encode_json({backup_root=>$saved_root})) if $cmd eq 'config';return ($repo_status,encode_json($repo_data)); }
sub check { @calls=();portable_settings_error(@_) }
die 'normal profile queried repository' if check('native-strict','snapshot','false','/new') || @calls;
die 'portable full requires repository' if check('portable-archive','full','false','/new') || @calls;
die 'auto export accepted' unless check('portable-archive','snapshot','true','/fixture/saved') =~ /Export/ && !@calls;
$repo_data={available=>JSON::PP::true,initialized=>JSON::PP::true,key_confirmed=>JSON::PP::true};
die 'ready repository rejected' if check('portable-archive','snapshot','false','/fixture/saved');
die 'wrong target accepted' unless check('portable-archive','snapshot','false','/different') && join(',',@calls) eq 'config';
for my $field ('available','initialized','key_confirmed') {
 for my $bad (JSON::PP::false,'true',1,undef) { $repo_data->{$field}=$bad;die 'unsafe repository status accepted' unless check('portable-archive','snapshot','false','/fixture/saved'); }
 $repo_data->{$field}=JSON::PP::true;
}
$repo_status=1;die 'failed status accepted' unless check('portable-archive','snapshot','false','/fixture/saved');
$repo_status=0;$config_status=1;die 'failed saved config accepted' unless check('portable-archive','snapshot','false','/fixture/saved');
print "Actual CGI portable settings gate passed\n";
`;
if(process.platform==='win32')execFileSync('C:/Program Files/Git/bin/bash.exe',['-s'],{cwd:repo,input:`perl -e ${quote(portableSettingsProgram)}\n`,encoding:'utf8'});
else execFileSync('perl',['-e',portableSettingsProgram],{cwd:repo,encoding:'utf8'});
function renderFixture(metadataMode) {
  if (process.platform === 'win32') return execFileSync('C:/Program Files/Git/bin/bash.exe', ['-s'], {cwd:repo, input:`HOSTBACKUP_FIXTURE_METADATA=${quote(metadataMode)} PERL5LIB=${quote(perlLib)} LBPDATADIR=${quote(posix(temp))} REQUEST_METHOD=GET REMOTE_USER=fixture HTTP_USER_AGENT=fixture perl -MHostBackupFixture webfrontend/htmlauth/index.cgi\n`, encoding:'utf8'});
  return execFileSync('perl',['-MHostBackupFixture','webfrontend/htmlauth/index.cgi'], {cwd:repo,env:{...process.env,HOSTBACKUP_FIXTURE_METADATA:metadataMode,PERL5LIB:perlLib,LBPDATADIR:temp,REQUEST_METHOD:'GET',REMOTE_USER:'fixture',HTTP_USER_AGENT:'fixture'},encoding:'utf8'});
}
let html=renderFixture('native-strict');
const portableHtml=renderFixture('portable-archive');
function assertNoNestedFormMarkup(markup) {
  let depth=0;
  for(const tag of markup.matchAll(/<\/?form\b[^>]*>/gi)) {
    if(/^<\/form/i.test(tag[0])) { assert.equal(depth,1,'Form closing tag matches one open form');depth--; }
    else { assert.equal(depth,0,'Actual CGI markup must never nest forms');depth++; }
  }
  assert.equal(depth,0,'All forms are closed');
}
assertNoNestedFormMarkup(html);assertNoNestedFormMarkup(portableHtml);
for(const mode of ['network-compatible','fake-super']) {
  const legacyHtml=renderFixture(mode);
  assert.match(legacyHtml,/<details class="metadata-advanced" id="metadata-advanced" open>/,'Existing advanced selection remains visible without JavaScript: '+mode);
  assert.ok(legacyHtml.includes('name="metadata_mode" value="'+mode+'" checked'),'Existing enum remains checked: '+mode);
}
assert.match(html,/<details class="metadata-advanced" id="metadata-advanced">/,'Normal profile starts with advanced choices collapsed');
// Exercise the real lazy backup-row CGI renderer, not hand-maintained action
// markup. Only its list response and GET action are overridden in this process.
const backupFixture=[{backup_id:'fixture-ok',status:'complete',validation:{status:'ok'},host:{hostname:'fixture'},size_bytes:3221225472,files_count:100,finished_at:'2026-09-13T12:00:00Z',storage_format:'directory',export_status:'missing'}];
backupFixture.push({...backupFixture[0],backup_id:'fixture-second',host:{hostname:'second-fixture'}});
backupFixture.push({...backupFixture[0],backup_id:'fixture-repository',backup:{storage_format:'portable-repository'},export_status:'available',export_file:'/fixture/not-a-standalone-export.tar'});
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
let targetNoticeMode='http-error',targetNoticeRequests=0;
const maintenanceFields=['retention_mode','keep_daily','keep_weekly','keep_monthly','log_retention_days','quarantine_retention_days','integrity_enabled','integrity_interval_days'];
const postActions=[],maintenancePolicies=[],maintenancePreviews=[];
let failMaintenance=false,maintenanceDelay=0,savedMaintenance={};
const repositoryState={initialized:false,key_confirmed:false,key_exported:false,available:true,engine_version:'fixture'};
const repositoryPosts=[],recoveryFixture='{"test_only":true,"secret":"FIXTURE-NOT-A-REAL-RECOVERY-KEY"}\n';
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
      postActions.push(action);
      if(action&&action.startsWith('repository-')) {
        repositoryPosts.push(action);
        if(action==='repository-init') { assert.equal(repositoryState.initialized,false);repositoryState.initialized=true;return json(res,{ok:true,data:repositoryState,message:'Repository eingerichtet. Wiederherstellungsdatei herunterladen.'}); }
        if(action==='repository-key-export') { assert.equal(repositoryState.initialized,true);repositoryState.key_exported=true;res.writeHead(200,{'Content-Type':'application/json','Content-Disposition':'attachment; filename="loxberryhostbackup-recovery-key.json"','Cache-Control':'no-store'});res.end(recoveryFixture);return; }
        if(action==='repository-confirm-key') { assert.equal(repositoryState.key_exported,true);assert.equal(params.get('recovery_key_saved'),'1');repositoryState.key_confirmed=true;return json(res,{ok:true,data:repositoryState,message:'Sichere Aufbewahrung bestätigt.'}); }
        throw new Error('Unexpected repository action');
      }
      if(action==='save-config') { assert.equal(params.has('recovery_key_saved'),false,'Repository acknowledgement must never be saved as a setting');for(const name of [...maintenanceFields,'policy_json'])assert.equal(params.has(name),false,'Main settings must not submit maintenance field '+name);lastSavedPath=params.get('backup_root');lastSavedSources=JSON.parse(params.get('source_selection_json')); await new Promise(resolve=>setTimeout(resolve,saveDelay)); return json(res,failSave?{ok:false,error:'Simulierter Speicherfehler'}:{ok:true,message:'Gespeichert'},failSave?400:200); }
      if(action==='maintenance-config') {
        assert.equal(params.has('backup_root'),false);assert.equal(params.has('source_selection_json'),false);
        const policy=JSON.parse(params.get('policy_json'));assert.deepEqual(Object.keys(policy).sort(),maintenanceFields.slice().sort(),'External form serializes all eight maintenance settings only');
        assert.equal(typeof policy.integrity_enabled,'boolean');for(const name of maintenanceFields.filter(name=>!['retention_mode','integrity_enabled'].includes(name)))assert.equal(typeof policy[name],'number');
        maintenancePolicies.push(policy);await new Promise(resolve=>setTimeout(resolve,maintenanceDelay));
        if(failMaintenance)return json(res,{ok:false,error:'Simulierter Wartungsfehler'},400);
        savedMaintenance={...policy};return json(res,{ok:true,message:'Wartung gespeichert'});
      }
      if(action==='maintenance-preview') {
        assert.deepEqual(Array.from(params.keys()).sort(),['action','csrf_token'],'Preview never submits draft settings');
        maintenancePreviews.push({...savedMaintenance});return json(res,{ok:true,data:{applied:false,keep:[{backup_id:'saved-policy-'+savedMaintenance.keep_daily,reasons:['Gespeicherte Regel']}],delete:[]},message:'Vorschau ohne Löschung erstellt'});
      }
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
    if(action==='repository-status')return json(res,repositoryState);
    if(action==='source-info')return json(res,failSources?{ok:false,error:'Mountliste momentan nicht erreichbar'}:{selection:savedSources,volumes:sourceVolumes,notices:['Netzfreigaben bewusst auswählen.']},failSources?500:200);
    if(action==='task-overview')return json(res,{tasks:[{task,state:taskFinished?'finished':'running'}],active_task:taskFinished?null:task,last_success:{backup_id:overviewBackupId,finished_at:overviewFinishedAt},next_run:{local:'14.09.2026 02:00'},last_failure:overviewIssues?{task:'backup-old-failure.log',state:'failed'}:null,pending_service_recovery:overviewIssues?1:0,target:{configured:true,readable:true,path:overviewTarget,available_mb:20000}});
    if(['backup-preview','storage-info','runtime-cleanup-preview','diagnostics','inspect-backup','verification-report','recovery-sheet'].includes(action))reportRequests++;
    if(action==='task-status'){statusCount++;return json(res,{state:taskFinished?'finished':'running',phase:taskFinished?'complete':taskPhase,now:100,mtime:99,content_b64:Buffer.from(longLog()).toString('base64')});}
    if(action==='target-notice'){
      targetNoticeRequests++;
      if(targetNoticeMode==='pending')return; // Real browser AbortController timeout, no shortened production timer.
      if(targetNoticeMode==='http-error'){res.writeHead(500,{'Content-Type':'text/html'});res.end('<img src=x onerror="window.unsafeTargetError=true">Backend failure');return;}
      res.end('<section class="inline-notice">Fixture-Ziel verfügbar</section>');return;
    }
    if(action==='backup-list'){res.end(backupRows);return;}
    if(action==='stop-targets'){await new Promise(resolve=>setTimeout(resolve,100));res.end('<input type="hidden" name="stop_targets_loaded" value="1"><label><input type="checkbox" name="stop_targets" value="systemd:test.service" checked>Testdienst</label><button type="button" data-stop-target-preset="none">Keine Dienste</button>');return;}
    if(action==='backup-preview')return json(res,{saved_config:true,backup_mode:'snapshot',metadata_mode:'network-compatible',full_baseline_required:true,excludes:['/fixture/backup/***'],source_volumes:[{path:'/',included:true,reason:'System'}],available_mb:20000,baseline_estimate_mb:3000,metadata_probe:probe});
    if(action==='verification-report')return json(res,verificationReport);
    if(url.pathname==='/system/images/icons/loxberryhostbackup/icon_64.png'){res.writeHead(200,{'Content-Type':'image/png'});res.end(fs.readFileSync(path.join(repo,'icons/icon_64.png')));return;}
    if(url.pathname.startsWith('/system/')){res.writeHead(204);res.end();return;}
    htmlCount++;res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(url.searchParams.get('fixture')==='portable'?portableHtml:html);
  }catch(error){errors.push(error.message);json(res,{error:error.message},500);}
});
async function visible(page,selector){await page.locator(selector).waitFor({state:'visible'});}
async function openRepositoryByKeyboard(page) {
  const panel=page.locator('#portable-repository-panel');await panel.waitFor({state:'visible'});
  if(!await panel.evaluate(node=>node.open)) {await panel.locator(':scope > summary').focus();await page.keyboard.press('Enter');}
  assert.equal(await panel.evaluate(node=>node.open),true,'Repository disclosure opens with keyboard');
}
async function configurationControls(page) {
  return page.evaluate(()=>Array.from(document.getElementById('settings-save-form').elements).filter(node=>node.name&&node.name!=='csrf_token').map(node=>[node.name,node.value,node.checked||false]));
}
async function checkMaintenance(browser,base) {
  const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
  await page.goto(base);await visible(page,'#settings-save-form');await page.locator('#stop-targets-list [name="stop_targets_loaded"]').waitFor({state:'attached'});
  const panel=page.locator('#maintenance-settings-panel'),summary=panel.locator(':scope > summary');
  assert.equal(await summary.locator('.info-button[aria-describedby="help-maintenance-settings"]').count(),1,'Maintenance overview help is directly accessible in its summary');
  const maintenanceHelpTopics=[/Aufbewahr/,/Prüfsummen/,/Vergleichsbasis/,/zuerst|erste|angelegt/,/Restore/,/speichern/i,/Löschvorschau/];
  assert.equal(await panel.evaluate(node=>node.open),false,'Maintenance starts collapsed');
  assert.equal(await panel.evaluate(node=>node.parentElement.id),'options-permissions-settings');
  assert.equal(await panel.evaluate(node=>node.previousElementSibling.classList.contains('stop-target-panel')),true,'Maintenance is the direct next section after stopped services');
  assert.equal(await page.locator('form form').count(),0);
  const owners=await panel.locator('[name]').evaluateAll(nodes=>nodes.map(node=>({name:node.name,owner:node.form.id})));
  assert.deepEqual(owners.map(item=>item.name).sort(),maintenanceFields.slice().sort());
  assert.ok(owners.every(item=>item.owner==='maintenance-settings-form'));
  for(const id of ['maintenance-settings-form','maintenance-preview-form']) {
    assert.equal(await page.locator('#'+id).evaluate(node=>node.closest('#settings-save-form')),null,'Independent action forms are outside the main form');
    assert.equal(await panel.locator('button[form="'+id+'"]').evaluate(node=>node.form.id),id);
  }
  const mainBefore=await configurationControls(page),postsBefore=postCount;
  savedMaintenance=await page.evaluate(()=>Object.fromEntries(Array.from(document.getElementById('maintenance-settings-form').elements).filter(node=>node.name&&!['action','csrf_token'].includes(node.name)).map(node=>[node.name,node.type==='checkbox'?node.checked:node.type==='number'?Number(node.value):node.value])));
  for(const [view,width,height] of [['desktop',1440,1100],['mobile',390,844]]) {
    await page.setViewportSize({width,height});await page.locator('#options-permissions-settings').screenshot({path:path.join(temp,'options-maintenance-'+view+'-closed.png')});
    await checkActionHelp(page,'maintenance-settings',view+'-closed',maintenanceHelpTopics,true);
    await summary.focus();await page.keyboard.press('Enter');assert.equal(await panel.evaluate(node=>node.open),true);
    await checkActionHelp(page,'maintenance-settings',view+'-open',maintenanceHelpTopics,true);
    const geometry=await panel.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,overflow:node.scrollWidth-node.clientWidth,gap:node.getBoundingClientRect().top-node.previousElementSibling.getBoundingClientRect().bottom,copy:Array.from(node.querySelectorAll(':scope > p,:scope > summary')).map(item=>({tag:item.tagName,size:parseFloat(getComputedStyle(item).fontSize),weight:parseInt(getComputedStyle(item).fontWeight,10),spacing:getComputedStyle(item).letterSpacing})),controls:Array.from(node.querySelectorAll('input,select,button')).filter(item=>item.getBoundingClientRect().width>0).map(item=>({right:item.getBoundingClientRect().right,size:parseFloat(getComputedStyle(item).fontSize)}))}));
    assert.ok(geometry.left>=0&&geometry.right<=width+1&&geometry.overflow<=1,view+' maintenance stays inside viewport '+JSON.stringify(geometry));
    assert.ok(geometry.gap>=0&&geometry.gap<=30,view+' related settings retain compact vertical spacing '+JSON.stringify(geometry));
    assert.ok(geometry.copy.every(item=>item.size===13&&item.weight===(item.tag==='SUMMARY'?700:400)&&['normal','0px'].includes(item.spacing)),view+' actual LoxBerry wide styling cannot enlarge maintenance text '+JSON.stringify(geometry));
    assert.ok(geometry.controls.every(item=>item.right<=width+1&&item.size<=16),view+' maintenance controls fit normally');
    await page.locator('#options-permissions-settings').screenshot({path:path.join(temp,'options-maintenance-'+view+'-open.png')});
    await summary.focus();await page.keyboard.press('Space');assert.equal(await panel.evaluate(node=>node.open),false);
  }
  assert.deepEqual(await configurationControls(page),mainBefore);assert.equal(postCount,postsBefore);
  assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true','Opening/closing maintenance never creates a draft');
  const noScript=await browser.newPage({javaScriptEnabled:false,viewport:{width:390,height:844}});await noScript.goto(base);
  assert.equal(await noScript.locator('#maintenance-settings-panel').evaluate(node=>node.open),false);
  await noScript.locator('#maintenance-settings-panel > summary').focus();await noScript.keyboard.press('Enter');
  const serialized=await noScript.evaluate(()=>Object.fromEntries(['settings-save-form','maintenance-settings-form','maintenance-preview-form'].map(id=>[id,Array.from(new FormData(document.getElementById(id)).keys())])));
  for(const name of maintenanceFields)assert.equal(serialized['settings-save-form'].includes(name),false,'No-JS main FormData excludes '+name);
  assert.ok(maintenanceFields.filter(name=>name!=='integrity_enabled').every(name=>serialized['maintenance-settings-form'].includes(name)));
  assert.deepEqual(serialized['maintenance-preview-form'].sort(),['action','csrf_token']);
  for(const id of ['maintenance-settings-form','maintenance-preview-form'])assert.equal(await noScript.locator('button[form="'+id+'"]').evaluate(node=>node.form.id),id);
  await noScript.close();receipts.push('Maintenance sits directly after services within options, compact 13px desktop/mobile with keyboard disclosure; separate form owners and no-JS FormData prevent nested forms or accidental settings writes');
  receipts.push('Maintenance summary help explains retention, checksum baseline, restore limits and saved-only preview on desktop/mobile; closed/open disclosure, inputs, dirty state and requests remain unchanged');
  await page.setViewportSize({width:1440,height:1100});await summary.focus();await page.keyboard.press('Enter');
  const daily=page.locator('[name="keep_daily"]'),weekly=page.locator('[name="keep_weekly"]'),root=page.locator('#backup-root-input');
  const save=panel.locator('button[form="maintenance-settings-form"]'),preview=panel.locator('button[form="maintenance-preview-form"]'),globalSave=page.locator('#settings-change-popup button[type="submit"]');
  const clean=()=>page.waitForFunction(()=>document.querySelector('#settings-change-popup').getAttribute('aria-hidden')==='true');
  async function submitAndWait(button,action) {
    const response=page.waitForResponse(reply=>reply.request().method()==='POST'&&new URL(reply.url()).searchParams.get('action')===action);
    await button.click();await response;await page.waitForFunction(id=>document.getElementById(id).getAttribute('aria-busy')==='false',action==='maintenance-config'?'maintenance-settings-form':action==='maintenance-preview'?'maintenance-preview-form':'settings-save-form');
  }
  await daily.fill('13');await page.locator('[name="integrity_enabled"]').check();
  await preview.click();assert.equal(maintenancePreviews.length,0,'Unsaved maintenance cannot generate a misleading preview');
  await submitAndWait(save,'maintenance-config');await clean();assert.equal(savedMaintenance.keep_daily,13);assert.equal(savedMaintenance.integrity_enabled,true);
  assert.deepEqual(await configurationControls(page),mainBefore,'Direct maintenance save leaves main settings untouched');
  await root.fill('/fixture/main-draft');await weekly.fill('5');await submitAndWait(save,'maintenance-config');
  assert.equal(await root.inputValue(),'/fixture/main-draft');assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'false','Direct maintenance save must not erase an independent main draft');
  await preview.click();assert.equal(maintenancePreviews.length,0,'Main drafts also block preview');await root.fill('/fixture/backup');await clean();
  failMaintenance=true;await daily.fill('14');await submitAndWait(save,'maintenance-config');assert.match(await page.locator('#action-feedback').textContent(),/Wartungsfehler.*nicht verworfen/);assert.equal(savedMaintenance.keep_daily,13);assert.equal(await daily.inputValue(),'14');
  failMaintenance=false;maintenanceDelay=350;
  const delayedRequest=page.waitForRequest(request=>request.method()==='POST'&&request.url().includes('action=maintenance-config'));
  await save.click();await delayedRequest;await daily.fill('15');await page.waitForFunction(()=>document.getElementById('maintenance-settings-form').getAttribute('aria-busy')==='false');
  assert.equal(savedMaintenance.keep_daily,14);assert.equal(await daily.inputValue(),'15');assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'false','In-flight maintenance edits stay visibly unsaved');
  maintenanceDelay=0;await submitAndWait(save,'maintenance-config');await clean();
  receipts.push('Maintenance direct save serializes eight typed settings independently; failed and in-flight saves preserve drafts and never clear another form');
  await root.fill('/fixture/global');await daily.fill('16');let actionsBefore=postActions.length;
  await submitAndWait(globalSave,'maintenance-config');await clean();assert.deepEqual(postActions.slice(actionsBefore),['save-config','maintenance-config']);assert.equal(lastSavedPath,'/fixture/global');assert.equal(savedMaintenance.keep_daily,16);
  await root.fill('/fixture/global-failed');await daily.fill('17');failSave=true;actionsBefore=postActions.length;
  await submitAndWait(globalSave,'save-config');assert.deepEqual(postActions.slice(actionsBefore),['save-config'],'Main failure must not start maintenance save');assert.equal(await daily.inputValue(),'17');assert.equal(savedMaintenance.keep_daily,16);
  failSave=false;failMaintenance=true;actionsBefore=postActions.length;
  await submitAndWait(globalSave,'maintenance-config');assert.deepEqual(postActions.slice(actionsBefore),['save-config','maintenance-config']);assert.equal(lastSavedPath,'/fixture/global-failed');assert.equal(savedMaintenance.keep_daily,16);assert.equal(await daily.inputValue(),'17');
  assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'false','Maintenance failure after a successful main save remains dirty');
  failMaintenance=false;await submitAndWait(save,'maintenance-config');await clean();
  assert.equal(lastSavedPath,'/fixture/global-failed');assert.equal(savedMaintenance.keep_daily,17);
  receipts.push('Global save submits main and maintenance as independent sequential actions; either failure preserves the remaining draft and direct retry cleans only its own form');
  await submitAndWait(preview,'maintenance-preview');assert.deepEqual(maintenancePreviews.at(-1),savedMaintenance);assert.match(await page.locator('#operation-result').textContent(),/saved-policy-17/);
  const previewCount=maintenancePreviews.length;tokenDelay=350;const pendingToken=page.waitForRequest(request=>request.url().includes('action=csrf-token'));
  await preview.click();await pendingToken;await daily.fill('18');await page.waitForFunction(()=>document.getElementById('maintenance-preview-form').getAttribute('aria-busy')==='false');tokenDelay=0;
  assert.equal(maintenancePreviews.length,previewCount,'A draft created during CSRF refresh also blocks saved-only preview');
  await daily.fill('17');await clean();await submitAndWait(preview,'maintenance-preview');assert.deepEqual(maintenancePreviews.at(-1),savedMaintenance);
  assert.equal(postActions.includes('maintenance-run'),false,'Layout and preview tests never invoke a deletion');
  receipts.push('Maintenance preview submits only action/CSRF and uses persisted policy; drafts in either form or introduced during token refresh block it; no deletion invoked');
  await page.close();
}
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
    assert.equal(await page.locator('#portable-repository-panel').isVisible(),false,'Native profile hides portable-only setup');
    assert.equal(await page.locator('#portable-repository-panel').evaluate(node=>node.open),false,'Setup is initially collapsed');
    assert.equal(await page.locator('#backup-method-settings #portable-repository-panel').count(),1,'Setup is adjacent to storage method selection');
    assert.equal(await page.locator('#backup-type-settings #backup-extra-export [name="create_export_after_backup"]').count(),1,'Additional archive export belongs to backup type');
    assert.equal(await page.locator('form form').count(),0);
    for(const action of ['init','key-export','confirm-key']) {
      const id='repository-'+action+'-form';
      assert.equal(await page.locator('#settings-save-form form#'+id).count(),0,'Repository action form stays outside settings form');
      assert.equal(await page.locator('button[form="'+id+'"]').evaluate(node=>node.form.id),id);
      assert.equal(await page.locator('button[form="'+id+'"]').evaluate(node=>node.closest('fieldset').id),'backup-method-settings');
    }
    assert.equal(await page.locator('[name="recovery_key_saved"]').evaluate(node=>node.form.id),'repository-confirm-key-form');
    assert.equal(await page.evaluate(()=>new FormData(document.getElementById('settings-save-form')).has('recovery_key_saved')),false);
    assert.equal(await page.locator('[name="metadata_mode"]').count(),4,'Renaming adds no fifth profile');
    assert.equal(await page.locator('#metadata-advanced').evaluate(node=>node.open),false);
    assert.equal(await page.locator('[name="metadata_mode"]:visible').count(),2,'Only two normal choices');
    assert.equal(await page.locator('[name="metadata_mode"][value="native-strict"]').isChecked(),true);
    await page.locator('#metadata-advanced > summary').click();
    assert.equal(await page.locator('[name="metadata_mode"]:visible').count(),4);
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true','Opening advanced settings does not change configuration');
    receipts.push('Two normal storage methods; advanced legacy profiles preserved and server-rendered selected profiles opened without JavaScript');
    const repositoryRow=page.locator('#backup-list-body tr:has([name="backup_id"][value="fixture-repository"])');
    await repositoryRow.waitFor();
    for(const action of ['start-export','download-export','delete-export']) assert.equal(await repositoryRow.locator('[name="action"][value="'+action+'"]').count(),0,'Repository row cannot invoke generic '+action);
    assert.equal(await repositoryRow.locator('[name="browse_id"],[name="restore_id"]').count(),0,'Repository row does not offer generic browse or online restore');
    assert.equal(await repositoryRow.locator('[name="action"][value="verify-backup"]').count(),1);
    assert.equal(await repositoryRow.locator('[name="action"][value="protect-backup"]').count(),1);
    assert.match(await repositoryRow.textContent(),/Restore nur offline.*leeren Linux-Zwischenspeicher/);
    assert.equal(await repositoryRow.locator('a[href$="docs/PORTABLE-REPOSITORY.md"]').count(),1);
    const methodPanel=page.locator('fieldset.schedule-card').filter({has:page.locator('[name="metadata_mode"][value="native-strict"]')});
    for(const [view,width,height] of [['desktop',1440,1100],['mobile',390,844]]) {
      await page.setViewportSize({width,height});
      const layout=await methodPanel.evaluate(node=>({right:node.getBoundingClientRect().right,overflow:node.scrollWidth-node.clientWidth,cardWidths:Array.from(node.querySelectorAll('.metadata-modes > label')).map(item=>item.getBoundingClientRect().width),headings:Array.from(node.querySelectorAll('.metadata-profile-title strong,.metadata-advanced > summary')).map(item=>({size:parseFloat(getComputedStyle(item).fontSize),spacing:getComputedStyle(item).letterSpacing}))}));
      assert.ok(layout.right<=width+1&&layout.overflow<=1,view+' storage choices stay inside panel '+JSON.stringify(layout));
      assert.ok(layout.headings.every(item=>item.size<=16&&['normal','0px'].includes(item.spacing)),view+' storage choices retain normal typography');
      assert.ok(layout.cardWidths.every(width=>width>=220),view+' profile cards must not inherit narrow calendar columns '+JSON.stringify(layout));
      await methodPanel.screenshot({path:path.join(temp,'storage-methods-'+view+'.png')});
      const exportLayout=await page.locator('#backup-type-settings').evaluate(node=>({right:node.getBoundingClientRect().right,overflow:node.scrollWidth-node.clientWidth,labels:Array.from(node.querySelectorAll('label,p')).map(item=>({right:item.getBoundingClientRect().right,size:parseFloat(getComputedStyle(item).fontSize)}))}));
      assert.ok(exportLayout.right<=width+1&&exportLayout.overflow<=1&&exportLayout.labels.every(item=>item.right<=width+1&&item.size<=16),view+' backup type and additional export fit the viewport '+JSON.stringify(exportLayout));
      await page.locator('#backup-type-settings').screenshot({path:path.join(temp,'backup-type-export-'+view+'.png')});
    }
    await page.setViewportSize({width:1440,height:1100});
    const nativeControls=await configurationControls(page),initialPosts=postCount;
    await page.locator('[name="metadata_mode"][value="portable-archive"]').check();
    await visible(page,'#portable-repository-panel');
    assert.equal(await page.locator('#portable-repository-panel').evaluate(node=>node.open),false,'Choosing Portable does not expand setup automatically');
    for(const mode of ['fake-super','network-compatible','native-strict']) {
      await page.locator('[name="metadata_mode"][value="'+mode+'"]').check();
      assert.equal(await page.locator('#portable-repository-panel').isVisible(),false,'Other profiles hide portable setup: '+mode);
    }
    assert.deepEqual(await configurationControls(page),nativeControls,'Profile roundtrip never changes backup type, export, target or other settings');
    assert.equal(postCount,initialPosts,'Profile changes never initialize, save or back up');
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    const noScript=await browser.newPage({javaScriptEnabled:false,viewport:{width:390,height:844}});
    await noScript.goto(base);assert.equal(await noScript.locator('#portable-repository-panel').isVisible(),false);
    await noScript.goto(base+'?fixture=portable');assert.equal(await noScript.locator('#portable-repository-panel').isVisible(),true);
    assert.equal(await noScript.locator('#portable-repository-panel').evaluate(node=>node.open),false);
    await openRepositoryByKeyboard(noScript);
    assert.equal(await noScript.locator('button[form="repository-init-form"]').evaluate(node=>node.form.id),'repository-init-form');
    assert.equal(await noScript.locator('[name="recovery_key_saved"]').evaluate(node=>node.form.id),'repository-confirm-key-form');
    await noScript.close();
    receipts.push('Repository setup is inline under storage method, portable-only and initially collapsed; explicit form owners, backup-type export and no-JS visibility are correct');
    await page.goto(base+'?fixture=portable');await visible(page,'#download-task-log');
    await page.waitForFunction(()=>document.querySelector('#repository-status').textContent.includes('noch kein Repository'));
    assert.equal(await page.locator('#portable-repository-panel').evaluate(node=>node.open),false,'Saved Portable status loads while disclosure remains collapsed');
    await openRepositoryByKeyboard(page);
    assert.equal(repositoryPosts.length,0,'Reading status never initializes storage');
    assert.equal(await page.locator('button[form="repository-key-export-form"]').isEnabled(),false);
    await page.locator('#backup-root-input').fill('/fixture/not-yet-saved');
    await page.locator('button[form="repository-init-form"]').click();assert.equal(repositoryPosts.length,0,'Repository setup must not use a stale saved target while form is dirty');
    await page.locator('#backup-root-input').fill('/fixture/backup');
    const repositoryConfigBefore=await configurationControls(page);
    await page.locator('button[form="repository-init-form"]').click();
    await page.waitForFunction(()=>document.querySelector('button[form="repository-key-export-form"]').disabled===false);
    assert.deepEqual(repositoryPosts,['repository-init']);
    assert.equal(await page.locator('button[form="repository-confirm-key-form"]').isEnabled(),false,'Confirmation requires a key export first');
    const keyDownloadEvent=page.waitForEvent('download');await page.locator('button[form="repository-key-export-form"]').click();const keyDownload=await keyDownloadEvent;
    await keyDownload.saveAs(path.join(temp,'fixture-recovery-key.json'));
    assert.equal(fs.readFileSync(path.join(temp,'fixture-recovery-key.json'),'utf8'),recoveryFixture);
    assert.equal(keyDownload.suggestedFilename(),'loxberryhostbackup-recovery-key.json');
    await page.waitForFunction(()=>document.querySelector('button[form="repository-confirm-key-form"]').disabled===false);
    assert.equal(await page.locator('[name="recovery_key_saved"]').isChecked(),false,'Download does not silently acknowledge safe off-host storage');
    await page.locator('button[form="repository-confirm-key-form"]').click();assert.deepEqual(repositoryPosts,['repository-init','repository-key-export'],'Unchecked acknowledgement does not POST');
    await page.locator('[name="recovery_key_saved"]').check();
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true','External acknowledgement never dirties settings');
    assert.equal(await page.evaluate(()=>new FormData(document.getElementById('settings-save-form')).has('recovery_key_saved')),false);
    assert.equal(await page.evaluate(()=>new FormData(document.getElementById('repository-confirm-key-form')).get('recovery_key_saved')),'1','Explicit form ownership includes the external checkbox only in the confirmation');
    for(const [view,width,height] of [['desktop',1440,1100],['mobile',390,844]]) {
      await page.setViewportSize({width,height});
      const setupLayout=await page.locator('#portable-repository-panel').evaluate(node=>({right:node.getBoundingClientRect().right,left:node.getBoundingClientRect().left,overflow:node.scrollWidth-node.clientWidth,controls:Array.from(node.querySelectorAll('button,label,p')).map(item=>({right:item.getBoundingClientRect().right,font:parseFloat(getComputedStyle(item).fontSize)}))}));
      assert.ok(setupLayout.left>=0&&setupLayout.right<=width+1&&setupLayout.overflow<=1&&setupLayout.controls.every(item=>item.right<=width+1&&item.font<=16),view+' inline setup remains compact and bounded '+JSON.stringify(setupLayout));
      await page.locator('#backup-method-settings').screenshot({path:path.join(temp,'portable-inline-setup-'+view+'.png')});
      await page.locator('#portable-repository-panel > summary').focus();await page.keyboard.press('Enter');
      assert.equal(await page.locator('#portable-repository-panel').evaluate(node=>node.open),false);
      await openRepositoryByKeyboard(page);
      assert.equal(await page.locator('[name="recovery_key_saved"]').isChecked(),true,'Disclosure toggles retain explicit acknowledgement');
    }
    const setupPostsBeforeSwitch=postCount;
    await page.locator('[name="metadata_mode"][value="native-strict"]').check();assert.equal(await page.locator('#portable-repository-panel').isVisible(),false);
    await page.locator('[name="metadata_mode"][value="portable-archive"]').check();await openRepositoryByKeyboard(page);
    assert.equal(await page.locator('[name="recovery_key_saved"]').isChecked(),true,'Profile visibility changes do not clear or submit acknowledgement');
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    assert.equal(postCount,setupPostsBeforeSwitch);
    await page.locator('button[form="repository-confirm-key-form"]').focus();await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.querySelector('#repository-status').textContent.includes('Aufbewahrung der Wiederherstellungsdatei bestätigt'));
    assert.deepEqual(repositoryPosts,['repository-init','repository-key-export','repository-confirm-key']);
    assert.equal(await page.locator('button[form="repository-init-form"]').isEnabled(),false,'Existing repository is not reinitialized');
    assert.equal(await page.locator('button[form="repository-key-export-form"]').isEnabled(),true,'A recovery key can be downloaded again');
    assert.equal(await page.locator('button[form="repository-confirm-key-form"]').isEnabled(),false);
    assert.equal(await page.locator('body').textContent().then(text=>text.includes('FIXTURE-NOT-A-REAL-RECOVERY-KEY')),false,'Secret file contents never appear in DOM or status');
    assert.deepEqual(await configurationControls(page),repositoryConfigBefore,'Setup and download do not change profile, backup mode, target or configuration');
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    await page.locator('#portable-repository-panel > summary').click();
    receipts.push('Repository setup requires saved settings and explicit POST; secret download remains out of DOM; off-host acknowledgement stays separate and no backup/config change occurs');
    receipts.push('Desktop/mobile inline repository disclosure supports keyboard; external form confirmation survives toggles without becoming a setting');
    await page.setViewportSize({width:1440,height:1100});await page.goto(base);await visible(page,'#download-task-log');
    await page.locator('#metadata-advanced > summary').click();
    await page.waitForFunction(()=>document.querySelector('#target-notice .inline-notice.warning'));
    const targetNotice=page.locator('#target-notice'),targetDraft='/fixture/unsaved-target',targetSourceBefore=await page.locator('#source-selection-json').inputValue(),targetPostsBefore=postCount;
    assert.equal(await targetNotice.getAttribute('role'),'status');assert.equal(await targetNotice.getAttribute('aria-live'),'polite');
    assert.equal(await targetNotice.getAttribute('aria-busy'),'false');
    assert.match(await targetNotice.textContent(),/Gespeicherte Einstellungen bleiben erhalten/);
    assert.equal(await targetNotice.locator('img').count(),0);assert.equal(await page.evaluate(()=>window.unsafeTargetError),undefined,'HTTP error HTML is never interpreted as a notice');
    await page.locator('#backup-root-input').fill(targetDraft);
    await visible(page,'#settings-change-popup');
    for(const [name,width,height] of [['desktop',1440,1100],['mobile',390,844]]){
      await page.setViewportSize({width,height});await targetNotice.evaluate(node=>node.scrollIntoView({block:'center'}));
      const layout=await targetNotice.locator('.inline-notice').evaluate(node=>{const rect=node.getBoundingClientRect(),style=getComputedStyle(node);return {size:parseFloat(style.fontSize),weight:parseInt(style.fontWeight,10),spacing:style.letterSpacing,left:rect.left,right:rect.right,height:rect.height,overflow:node.scrollWidth-node.clientWidth};});
      assert.ok(layout.size<=14&&layout.weight<=400&&['normal','0px'].includes(layout.spacing)&&layout.height<230&&layout.left>=0&&layout.right<=width+1&&layout.overflow<=1,name+' failed target notice stays compact under host-theme rules '+JSON.stringify(layout));
      await page.screenshot({path:path.join(temp,'target-notice-error-'+name+'.png')});
    }
    targetNoticeMode='pending';
    const retryCount=targetNoticeRequests;
    await targetNotice.locator('[data-target-notice-retry]').focus();await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.querySelector('#target-notice').getAttribute('aria-busy')==='true');
    assert.equal(await targetNotice.locator('[data-target-notice-retry]').isEnabled(),false,'Retry is disabled while its read-only request is running');
    await page.waitForFunction(()=>document.querySelector('#target-notice').getAttribute('aria-busy')==='false',{},{timeout:30000});
    assert.equal(targetNoticeRequests,retryCount+1,'Retry starts one read-only target request');
    assert.equal(await targetNotice.locator('.inline-notice.warning').count(),1,'Timeout keeps the same standard warning layout');
    assert.equal(await targetNotice.locator('[data-target-notice-retry]').isEnabled(),true,'Timed-out request can be retried');
    assert.equal(await page.locator('#backup-root-input').inputValue(),targetDraft);
    assert.equal(await page.locator('#source-selection-json').inputValue(),targetSourceBefore);
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'false');
    targetNoticeMode='ok';await targetNotice.locator('[data-target-notice-retry]').click();
    await page.waitForFunction(()=>document.querySelector('#target-notice').textContent.includes('Fixture-Ziel verfügbar'));
    assert.equal(await targetNotice.locator('.warning').count(),0,'Successful retry replaces the failure notice');
    assert.equal(await targetNotice.locator('[data-target-notice-retry]').count(),0);
    assert.equal(await page.locator('#backup-root-input').inputValue(),targetDraft);assert.equal(postCount,targetPostsBefore,'Neither retry nor timeout saves settings or starts a backup');
    await page.locator('#backup-root-input').fill('/fixture/backup');
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    await page.setViewportSize({width:1440,height:1100});
    receipts.push('HTTP failure and real target-notice timeout keep compact desktop/mobile warning layout and preserve draft; keyboard retry recovers without POST or settings loss');
    const quickGuide=page.locator('.wizard-panel details'),guideSummary=quickGuide.locator('summary');
    const guidePosts=postCount,guideSources=await page.locator('#source-selection-json').inputValue();
    assert.equal(await quickGuide.evaluate(node=>node.open),false,'Quick guide remains collapsed initially');
    await guideSummary.focus();await page.keyboard.press('Enter');
    assert.equal(await quickGuide.evaluate(node=>node.open),true,'Quick guide opens by keyboard');
    assert.ok(await quickGuide.locator('li').count()>=9,'Quick guide covers setup through recovery');
    for(const [view,width,height] of [['desktop',1440,1100],['mobile',390,844]]){
      await page.setViewportSize({width,height});
      const guideLayout=await quickGuide.evaluate(node=>{const rect=node.getBoundingClientRect();return {right:rect.right,viewport:window.innerWidth,overflow:node.scrollWidth-node.clientWidth,items:Array.from(node.querySelectorAll('li')).map(item=>({size:parseFloat(getComputedStyle(item).fontSize),spacing:getComputedStyle(item).letterSpacing}))};});
      assert.ok(guideLayout.right<=width+1&&guideLayout.overflow<=1,view+' quick guide stays inside its panel '+JSON.stringify(guideLayout));
      assert.ok(guideLayout.items.every(item=>item.size<=16&&['normal','0px'].includes(item.spacing)),view+' quick guide retains normal typography');
      await quickGuide.screenshot({path:path.join(temp,'quick-guide-'+view+'.png')});
    }
    await page.setViewportSize({width:1440,height:1100});await guideSummary.focus();await page.keyboard.press('Space');
    assert.equal(await quickGuide.evaluate(node=>node.open),false,'Quick guide closes by keyboard');
    assert.equal(postCount,guidePosts,'Reading the quick guide never starts or saves anything');
    assert.equal(await page.locator('#source-selection-json').inputValue(),guideSources);
    assert.equal(await page.locator('#settings-change-popup').getAttribute('aria-hidden'),'true');
    receipts.push('Actual CGI quick guide is readable on desktop/mobile, keyboard-operable and cannot change settings or start actions');
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
    assert.equal(await page.locator('#backup-list-body .backup-extra-actions').count(),3,'Real CGI fixture includes two directory backups and one repository backup');
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
    repositoryState.key_confirmed=false;
    await page.locator('[name="metadata_mode"][value="portable-archive"]').check();
    await openRepositoryByKeyboard(page);
    await page.locator('#repository-status-refresh').click();await page.waitForFunction(()=>document.querySelector('#repository-status').textContent.includes('Jetzt ausserhalb'));
    const portablePosts=postCount;await page.locator('#settings-change-popup button[type="submit"]').click();assert.equal(postCount,portablePosts);assert.match(await page.locator('#action-feedback').textContent(),/bestätigte Aufbewahrung/);
    assert.equal(await page.locator('[name="backup_mode"][value="snapshot"]').isChecked(),true,'Blocked portable choice is not silently switched to full');
    repositoryState.key_confirmed=true;await page.locator('#repository-status-refresh').click();await page.waitForFunction(()=>document.querySelector('#repository-status').textContent.includes('Aufbewahrung der Wiederherstellungsdatei bestätigt'));
    await page.locator('[name="create_export_after_backup"]').check();await page.locator('#settings-change-popup button[type="submit"]').click();assert.equal(postCount,portablePosts);assert.match(await page.locator('#action-feedback').textContent(),/tar.gz-Export ausdrücklich deaktivieren/);
    assert.equal(await page.locator('[name="create_export_after_backup"]').isChecked(),true,'Incompatible export stays visible until user explicitly changes it');
    await page.locator('[name="create_export_after_backup"]').uncheck();
    await page.locator('#backup-root-input').fill('/fixture/unregistered-repository');await page.locator('#settings-change-popup button[type="submit"]').click();assert.equal(postCount,portablePosts);assert.match(await page.locator('#action-feedback').textContent(),/gespeicherten Backup-Ziel/);
    await page.locator('#backup-root-input').fill('/fixture/B');
    await page.locator('#portable-repository-panel > summary').focus();await page.keyboard.press('Enter');assert.equal(await page.locator('#portable-repository-panel').evaluate(node=>node.open),false);
    await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Einstellungen gespeichert'));assert.equal(postCount,portablePosts+1);
    assert.equal(await page.locator('[name="metadata_mode"][value="portable-archive"]').isChecked(),true);assert.equal(await page.locator('[name="backup_mode"][value="snapshot"]').isChecked(),true);
    await page.waitForFunction(()=>document.querySelector('#repository-status').textContent.includes('Aufbewahrung der Wiederherstellungsdatei bestätigt'));
    const previousKeep=await page.locator('[name="keep_backups"]').inputValue();await page.locator('[name="keep_backups"]').fill(String(Number(previousKeep)+1));
    const repeatedSave=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().includes('action=save-config'));
    await page.locator('#settings-change-popup button[type="submit"]').click();await repeatedSave;await page.waitForFunction(()=>document.querySelector('#settings-change-popup').getAttribute('aria-hidden')==='true');assert.equal(postCount,portablePosts+2,'Ready portable settings save repeatedly without opening setup');
    assert.equal(await page.locator('#portable-repository-panel').evaluate(node=>node.open),false);
    await page.locator('[name="keep_backups"]').fill(previousKeep);
    receipts.push('Portable snapshot requires saved-target repository and confirmed key; export and target mismatches block without auto-switch; ready configuration saves');
    await page.locator('[name="metadata_mode"][value="network-compatible"]').check();
    const incompatiblePosts=postCount;
    await page.locator('[name="schedule_enabled"]').check();await page.locator('[name="schedule_mode"][value="weekly"]').check();await page.locator('[data-schedule-panel="weekly"]').evaluate(node=>node.open=true);await page.locator('[name="schedule_weekdays"][value="1"]').uncheck();await page.locator('#settings-change-popup button[type="submit"]').click();assert.equal(postCount,incompatiblePosts);assert.match(await page.locator('#action-feedback').textContent(),/Wochentag/);
    await page.locator('[name="schedule_enabled"]').uncheck();await page.locator('#settings-change-popup button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#action-feedback').textContent.includes('Einstellungen gespeichert'));receipts.push('Empty weekly schedule rejected before POST');
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
    await checkMaintenance(browser,base);
    assert.deepEqual(errors,[]);
    const result={status:'passed',tests:receipts,artifacts:temp,renderer:'actual CGI with mocked backend; read-only mount discovery',browser:await browser.version()};
    fs.writeFileSync(path.join(temp,'receipt.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
