'use strict';
const assert = require('node:assert/strict');
const ui = require('../webfrontend/htmlauth/assets/hostbackup.js');
const stoppedContainerId = 'ab'.repeat(32);
const runningIssue = ui.containerIssueMessages([{id:stoppedContainerId,name:'sonn-core',state:'running',stage:'after_copy'}])[0];
assert.match(runningIssue.title, /sonn-core.*wieder gestartet/);
assert.match(runningIssue.explanation, /nach dem Kopieren/);
assert.match(runningIssue.advice, /genaue Auslöser ist nicht bekannt/);
assert.match(runningIssue.advice, /eigene Oberfläche/);
assert.equal(runningIssue.id, stoppedContainerId);
const beforeCopyIssue = ui.containerIssueMessages([{id:stoppedContainerId,name:'loxpanel',state:'running',stage:'before_copy'}])[0];
assert.match(beforeCopyIssue.explanation, /vor dem Kopieren/);
const missingIssue = ui.containerIssueMessages([{id:stoppedContainerId,name:'loxpanel',state:'missing'}])[0];
assert.match(missingIssue.title, /nicht mehr vorhanden/);
assert.match(missingIssue.explanation, /Neuerstellung ist möglich, aber damit nicht nachgewiesen/);
const unavailableIssue = ui.containerIssueMessages([{id:stoppedContainerId,name:'loxpanel',state:'unavailable'}])[0];
assert.match(unavailableIssue.title, /konnte nicht geprüft werden/);
assert.match(unavailableIssue.explanation, /kein Nachweis für einen Neustart oder eine Löschung/);
for (const name of [undefined, '', '<img src=x onerror=alert(1)>', 'bad\nlabel', {}]) {
  const issue = ui.containerIssueMessages([{id:stoppedContainerId,name,state:'running'}])[0];
  assert.match(issue.title, new RegExp(stoppedContainerId));
  assert.doesNotMatch(issue.title, /<img|bad\n/);
}
for (const invalid of [null, {}, 'running', [null], [{id:'bad',state:'running'}],
  [{id:stoppedContainerId+'\n',state:'running'}], [{id:stoppedContainerId,state:'running\n'}],
  [{id:stoppedContainerId,state:'invented'}], [{id:stoppedContainerId,state:{}}]]) {
  assert.deepEqual(ui.containerIssueMessages(invalid), []);
}
assert.equal(ui.containerIssueMessages(Array(101).fill({id:stoppedContainerId,name:'test',state:'running'})).length, 100);
assert.deepEqual(ui.containerIssueMessages([]), [], 'A clean task cannot inherit diagnostics from another task');
assert.equal(ui.normalizeLogForDisplay('a\rb\r\nc\u001b[31md\u001b[0m'), 'a\nb\ncd');
assert.equal(ui.controlState([{type:'radio',value:'native',checked:false},{type:'radio',value:'network',checked:true}]), 'network');
assert.equal(ui.controlState([{type:'checkbox',name:'stop_targets',value:'docker:x',checked:true}]), 'docker:x');
assert.equal(ui.controlState([{type:'checkbox',name:'root_permission_ack',value:'1',checked:false}]), '0');
const stopRows=[{value:'systemd:mqtt.service',aliases:['mqtt.service','mqtt-old.service','mqtt-second.service']},{value:'docker:mqtt-old.service'}];
const oldStopSelection=['systemd:mqtt-old.service','systemd:mqtt-second.service','systemd:mqtt.service','docker:mqtt-old.service','systemd:removed.service'];
const originalStopData=JSON.stringify({stopRows,oldStopSelection});
assert.deepEqual(ui.stopTargetSelection(oldStopSelection,stopRows),{selected:['systemd:mqtt.service','docker:mqtt-old.service','systemd:removed.service'],missing:['systemd:removed.service']},'Aliases deduplicate into one canonical choice; Docker names remain exact and missing choices stay visible');
assert.deepEqual(ui.stopTargetSelection([],stopRows),{selected:[],missing:[]},'An explicit unchecked draft does not regain a server-selected alias');
assert.equal(JSON.stringify({stopRows,oldStopSelection}),originalStopData,'Alias mapping never changes its input or saved configuration');
assert.deepEqual(ui.stopTargetSelection(['systemd:legacy.service'],[{value:'systemd:legacy.service'}]),{selected:['systemd:legacy.service'],missing:[]},'Old responses without alias metadata remain supported');
for(const aliases of [null,'mqtt-old.service',{},[null],[1],[{}],['bad\nname.service'],['foo$(id).service'],['a.socket'],['template@.service'],['same.service','same.service']]) {
  assert.throws(()=>ui.stopTargetSelection([],[{value:'systemd:mqtt.service',aliases}]),/invalid-stop-targets/);
}
assert.throws(()=>ui.stopTargetSelection([],[{value:'docker:mqtt',aliases:[]}]),/invalid-stop-targets/);
assert.throws(()=>ui.stopTargetSelection([],[{value:'systemd:a.service',aliases:['b.service']},{value:'systemd:b.service'}]),/invalid-stop-targets/);
assert.throws(()=>ui.stopTargetSelection([],[{value:'systemd:a.service',aliases:['shared.service']},{value:'systemd:b.service',aliases:['shared.service']}]),/invalid-stop-targets/);
assert.throws(()=>ui.stopTargetSelection(['invalid'],stopRows),/invalid-stop-targets/);
const validUnitNames=['plain.service','_worker.service',':worker.service','-worker.service','.worker.service',
  'worker:zone.service','worker@zone:one@two.service','worker@@.service',String.raw`worker@room\x20one.service`,String.raw`\x2dworker.service`,String.raw`raw\q.service`,String.raw`slash\.service`,
  'a'.repeat(247)+'.service'];
for(const name of validUnitNames) {
  assert.equal(ui.validStopTargetName('systemd',name),true,'Valid literal systemd name: '+name);
  assert.equal(ui.validStopTargetValue('systemd:'+name),true);
  assert.deepEqual(ui.stopTargetSelection(['systemd:'+name],[{value:'systemd:'+name,aliases:[name]}]),{selected:['systemd:'+name],missing:[]});
}
for(const name of ['', '.service','@worker.service','worker@.service','worker.socket','a'.repeat(248)+'.service',
  'worker.service\n','worker.service\r','worker.service\u2028','bad name.service','bad\tname.service','worker/other.service',
  'worker*.service','worker?.service','worker[one].service','worker;id.service','worker$(id).service','worker`id`.service',
  "worker'one.service",'worker"one.service','worker,one.service','wörker.service']) {
  assert.equal(ui.validStopTargetName('systemd',name),false,'Invalid systemd name: '+JSON.stringify(name));
  assert.throws(()=>ui.stopTargetSelection(['systemd:'+name],[]),/invalid-stop-targets/);
  assert.throws(()=>ui.stopTargetSelection([],[{value:'systemd:valid.service',aliases:[name]}]),/invalid-stop-targets/);
}
for(const name of ['sonn-core','1worker','test_a.b-c'])assert.equal(ui.validStopTargetName('docker',name),true);
for(const name of ['-option','_leading','with:colon','with@at',String.raw`with\slash`,'sonn-core\n'])assert.equal(ui.validStopTargetName('docker',name),false);
const escapedCanonical=String.raw`systemd:-worker@room\x20one@zone.service`,escapedAlias=String.raw`_worker@room\x20one@zone.service`;
assert.deepEqual(ui.stopTargetSelection(['systemd:'+escapedAlias],[{value:escapedCanonical,aliases:[escapedAlias]}]),{selected:[escapedCanonical],missing:[]},'Escaped identities remain literal while mapping aliases');
const portableSnapshot={metadata_mode:'portable-archive',backup_mode:'snapshot',create_export_after_backup:'0'};
const repositoryReady={available:true,initialized:true,key_confirmed:true,target_matches:true};
assert.match(ui.validateSettings(portableSnapshot), /bestätigte Aufbewahrung/);
assert.equal(ui.validateSettings(portableSnapshot,repositoryReady),'');
for(const field of Object.keys(repositoryReady))for(const bad of [false,undefined,'true',1]) {
  assert.match(ui.validateSettings(portableSnapshot,{...repositoryReady,[field]:bad}),/bestätigte Aufbewahrung/,'Repository gate requires exact booleans: '+field);
}
assert.match(ui.validateSettings({...portableSnapshot,create_export_after_backup:'1'},repositoryReady),/tar.gz-Export ausdrücklich deaktivieren/);
assert.equal(ui.validateSettings({...portableSnapshot,backup_mode:'full'}),'','Standalone portable full archive needs no repository');
assert.deepEqual(repositoryReady,{available:true,initialized:true,key_confirmed:true,target_matches:true},'Validation never changes repository or user configuration');
assert.equal(ui.metadataLabel('native-strict'),'Linux-Dateisicherung');
assert.equal(ui.metadataLabel('portable-archive'),'Portable Sicherung');
assert.equal(ui.metadataLabel('network-compatible'),'Dateisicherung mit reduzierten Metadaten');
assert.equal(ui.metadataLabel('fake-super'),'Metadaten in Dateiattributen speichern');
assert.equal(ui.metadataLabel('future-format'),'future-format');
assert.equal(ui.backupModeLabel('full'),'Vollbackup');
assert.equal(ui.backupModeLabel('snapshot'),'Platzsparende Sicherungsstände');
assert.equal(ui.advancedMetadata('native-strict'),false);
assert.equal(ui.advancedMetadata('portable-archive'),false);
assert.equal(ui.advancedMetadata('network-compatible'),true);
assert.equal(ui.advancedMetadata('fake-super'),true);
assert.match(ui.validateSettings({schedule_enabled:'1',schedule_time:'02:00',schedule_mode:'weekly',schedule_weekdays:''}), /Wochentag/);
assert.match(ui.validateSettings({schedule_enabled:'1',schedule_time:'02:00',schedule_mode:'monthly',schedule_monthdays:'1',schedule_months:''}), /Monat/);
assert.equal(ui.validateSettings({metadata_mode:'network-compatible',backup_mode:'snapshot',schedule_enabled:'1',schedule_time:'02:00',schedule_mode:'daily'}), '');
const initial={profile:'native'}, changed={}, t1=new Date(1),t2=new Date(2);
ui.updateDirty(initial,changed,'profile','network',t1);
assert.equal(changed.profile.at,t1);
ui.updateDirty(initial,changed,'profile','network',t2);
assert.equal(changed.profile.at,t1);
ui.updateDirty(initial,changed,'profile','portable',t2);
assert.equal(changed.profile.at,t2);
ui.updateDirty(initial,changed,'profile','native',t2);
assert.equal(Object.keys(changed).length,0);
assert.equal(ui.logViewport(0,500,2000),false);
assert.equal(ui.logViewport(1480,500,2000),true);
assert.equal(ui.phaseLabel('retention'),'Aufbewahrung prüfen und alte Backups bereinigen');
assert.equal(ui.phaseLabel('copying'),'copying');
assert.equal(ui.phaseLabel('selecting_sources'),'Ausgewählte Datenquellen erfassen');
assert.equal(ui.phaseLabel('future-phase'),'future-phase');
const localSources=ui.sourceSelection('{"policy":"local","overrides":{"/media/smb/allowed":true,"/media/usb/backup":false}}');
assert.equal(ui.sourceIncluded(localSources,{path:'/media/usb/data',kind:'local',selectable:true}),true);
assert.equal(ui.sourceIncluded(localSources,{path:'/media/smb/nas',kind:'network',selectable:true}),false);
assert.equal(ui.sourceIncluded(localSources,{path:'/media/smb',kind:'automount',selectable:true}),false);
assert.equal(ui.sourceIncluded(localSources,{path:'/media/smb/allowed',kind:'network',selectable:true}),true);
assert.equal(ui.sourceIncluded(localSources,{path:'/media/usb/backup/sub',kind:'local',selectable:true}),false);
assert.equal(ui.sourceIncluded(localSources,{path:'/media/smb/allowed',kind:'network',selectable:false,included:false}),false);
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'legacy',overrides:{}}),{path:'/media/smb/nas',kind:'network',selectable:true}),true);
assert.equal(JSON.stringify(ui.sourceSelection(JSON.stringify(localSources))),JSON.stringify(localSources));
assert.throws(()=>ui.sourceSelection({policy:'local',overrides:{'/media/smb':1}}),/Ausnahme/);
const mountRows=[{path:'/mnt/nas',kind:'network',selectable:true},{path:'/mnt/nas/nested',kind:'local',selectable:true}];
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{}}),mountRows[1],mountRows),false);
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{'/mnt/nas/nested':true}}),mountRows[1],mountRows),true);
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{'/mnt':true}}),mountRows[0],mountRows),false);
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'legacy',overrides:{'/mnt/nas':true}}),{...mountRows[0],forced_excluded:true},mountRows),false);
const autoRows=[{path:'/media/usb',kind:'automount',selectable:false},{path:'/media/usb/data',kind:'local',selectable:true},{path:'/media/usb/network',kind:'network',selectable:true}];
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{}}),autoRows[1],autoRows),true,'Known USB mount below autofs stays selected');
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{}}),autoRows[0],autoRows),false,'Autofs itself is not traversed');
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{}}),autoRows[2],autoRows),false,'Network sibling below autofs still requires explicit selection');
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{'/media/usb':false}}),autoRows[1],autoRows),false,'An explicit parent exclusion remains effective');
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{'/media/usb':false,'/media/usb/data':true}}),autoRows[1],autoRows),true,'Explicit mount selection may override a source-parent exclusion');
const remoteAutoRows=[{path:'/mnt/remote',kind:'network',selectable:true},{path:'/mnt/remote/auto',kind:'automount',selectable:false},{path:'/mnt/remote/auto/local',kind:'local',selectable:true}];
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{}}),remoteAutoRows[2],remoteAutoRows),false,'Autofs exception must not bypass an excluded network ancestor');
assert.equal(ui.sourceIncluded(ui.sourceSelection({policy:'local',overrides:{'/media/usb':true}}),autoRows[0],autoRows),false,'Autofs cannot be explicitly enabled as a whole');
const selectedAutoRows=[{path:'/outer',kind:'network',selectable:true},{path:'/outer/chosen',kind:'local',selectable:true},{path:'/outer/chosen/auto',kind:'automount',selectable:false},{path:'/outer/chosen/auto/local',kind:'local',selectable:true},{path:'/outer/chosen/auto/network',kind:'network',selectable:true}];
const selectedAuto=ui.sourceSelection({policy:'local',overrides:{'/outer':false,'/outer/chosen':true}});
assert.equal(ui.sourceIncluded(selectedAuto,selectedAutoRows[3],selectedAutoRows),true,'Selected local child starts a new inclusion branch despite older parent exclusion');
assert.equal(ui.sourceIncluded(selectedAuto,selectedAutoRows[4],selectedAutoRows),false,'Explicit local branch must not admit nested network mount');
const defaultDisplay=ui.sourceSelection({policy:'local',overrides:{}});
assert.equal(ui.sourceDisplayGroup(defaultDisplay,{path:'/',kind:'local',fstype:'overlay'}),'primary','Container root stays prominent even when it uses overlay');
for(const volume of [{path:'/boot',kind:'local',fstype:'vfat'},{path:'/media/usb/data',kind:'local',fstype:'ext4'},{path:'/media/smb/nas',kind:'network',fstype:'cifs'},{path:'/media/smb/disconnected',kind:'unmounted'},{path:'/opt/loxberry/log/plugins-data',kind:'local'},{path:'/opt/loxberry/log/plugins/user-data',kind:'local'}]) {
  assert.equal(ui.sourceDisplayGroup(defaultDisplay,volume),'primary','Real data sources and missing exceptions stay visible: '+volume.path);
}
for(const volume of [{path:'/proc',kind:'system',fstype:'proc'},{path:'/media/smb',kind:'automount',fstype:'autofs'},{path:'/var/lib/docker/overlay2/example/merged',kind:'local',fstype:'overlay'},{path:'/opt/loxberry/log/plugins',kind:'local'},{path:'/opt/loxberry/log/ramlog',kind:'local'},{path:'/opt/loxberry/log/system_tmpfs',kind:'local'}]) {
  assert.equal(ui.sourceDisplayGroup(defaultDisplay,volume),'technical','Technical mount is visually grouped: '+volume.path);
  for(const selected of [true,false]) assert.equal(ui.sourceDisplayGroup(ui.sourceSelection({policy:'local',overrides:{[volume.path]:selected}}),volume),'primary','Both selected and excluded explicit technical exceptions remain prominent');
}
const groupingRows=[{path:'/',kind:'local',fstype:'overlay',selectable:false},{path:'/proc',kind:'system',fstype:'proc',selectable:false},{path:'/media/smb',kind:'automount',fstype:'autofs',selectable:false},{path:'/media/smb/nas',kind:'network',fstype:'cifs',selectable:true},{path:'/media/usb/data',kind:'local',fstype:'ext4',selectable:true},{path:'/var/lib/docker/merged',kind:'local',fstype:'overlay',selectable:true}];
for(const selection of [defaultDisplay,ui.sourceSelection({policy:'legacy',overrides:{}}),ui.sourceSelection({policy:'local',overrides:{'/var/lib/docker/merged':false}})]) {
  const before=groupingRows.map(row=>ui.sourceIncluded(selection,row,groupingRows)), serialized=JSON.stringify(selection);
  const primary=groupingRows.filter(row=>ui.sourceDisplayGroup(selection,row)==='primary'), technical=groupingRows.filter(row=>ui.sourceDisplayGroup(selection,row)==='technical');
  assert.equal(primary.length+technical.length,groupingRows.length,'Grouping neither drops nor duplicates a mount');
  assert.equal(new Set([...primary,...technical]).size,groupingRows.length,'Every mount belongs to exactly one display group');
  assert.deepEqual(groupingRows.map(row=>ui.sourceIncluded(selection,row,groupingRows)),before,'Display grouping does not change any backup checkbox');
  assert.equal(JSON.stringify(selection),serialized,'Display grouping never changes saved exceptions');
}
const legacyNotice='Bestehende Konfiguration: bisheriger Sicherungsumfang bleibt erhalten. Fuer einen begrenzten Umfang lokale Quellen waehlen und Netzfreigaben einzeln aktivieren.';
assert.deepEqual(ui.sourceNotices([legacyNotice,'Gewählte Quelle ist nicht eingebunden.'],['Prüfung fehlgeschlagen.']),['Gewählte Quelle ist nicht eingebunden.','Prüfung fehlgeschlagen.'],'Remove only the duplicate policy explanation');
assert.deepEqual(ui.sourceNotices([], [legacyNotice]),[legacyNotice],'Errors are never filtered, even when text matches a notice');
const allSourcesNotice='Alle eingebundenen Quellen: Auch Netzfreigaben werden mitgesichert. Fuer einen begrenzten Umfang lokale Laufwerke waehlen und Netzfreigaben einzeln aktivieren.';
assert.deepEqual(ui.sourceNotices([allSourcesNotice], ['Quelle fehlt.']),['Quelle fehlt.'],'Neutral policy notice is already explained next to the selector');
assert.deepEqual(ui.sourceNotices([], [allSourcesNotice]),[allSourcesNotice],'Neutral policy errors must also remain visible');
assert.deepEqual(ui.sourceNotices(),[]);
console.log('HostBackup web behavior tests passed.');
