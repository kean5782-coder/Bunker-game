'use strict';
const $=id=>document.getElementById(id);
let token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
try{token=token||sessionStorage.getItem('bunkerLauncherToken')||'';if(token)sessionStorage.setItem('bunkerLauncherToken',token);}catch(_){}
if(token&&location.protocol.startsWith('http')){try{history.replaceState(null,'',location.pathname);}catch(_){}}
let role='host',mode='porthole',runtimeReady=false,initialized=false,currentPhase='idle',lastState=null,adapters=[];
const savedAddresses={};
const labels={porthole:'Porthole',lan:'Локальная сеть',vpn:'Hamachi / Radmin',public:'Белый IP'};
async function api(path,body){const opts={headers:{'X-Bunker-Token':token}};if(body!==undefined){opts.method='POST';opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body);}const r=await fetch('/api/'+path,opts);if(!r.ok){let msg;try{msg=(await r.json()).error;}catch(_){msg=await r.text().catch(()=>r.statusText);}throw new Error(msg||'Помощник недоступен. Запустите Bunker.exe повторно.');}return r.json();}
function settings(){return {role,mode,port:Number($('port').value),external_port:Number($('externalPort').value),address:$('address').value.trim(),allow_download:$('consent').checked};}
function guide(){const p=$('port').value||'8008',ep=$('externalPort').value||p;
 const data={
 porthole:role==='host'?[
 `Нажмите «${runtimeReady?'Запустить сервер':'Подготовить и запустить'}». Игровой порт: TCP ${p}.`,
 'Откройте Porthole в Steam, создайте в нём лобби и добавьте локальный TCP-порт игры.',
 `Пригласите друзей в Porthole. Каждый должен подтвердить порт ${p} на своём компьютере.`,
 'Откройте игру, создайте комнату и отправьте друзьям ссылку из лобби Бункера.',
 'Когда все вошли, задайте параметры, выберите «Погружение» или «Неизвестность» и начните партию.'
 ]:[
 'Запустите Steam и Porthole. Войдите в лобби ведущего по приглашению или коду Porthole.',
 `Подтвердите TCP-порт игры. Обычно это ${p}; если Porthole выбрал другой локальный порт, укажите его здесь.`,
 'Не запускайте свой игровой сервер. Он займёт порт, который должен использовать Porthole.',
 'Нажмите «Подключиться к ведущему», затем откройте игру. Введите имя и код комнаты Бункера или используйте ссылку ведущего.'
 ],
 lan:role==='host'?[
 'Подключите устройства к одной домашней сети Wi-Fi или кабелем к одному роутеру.',
 'Выберите IPv4 вашего Wi-Fi/Ethernet-адаптера. Не выбирайте виртуальный адаптер VPN.',
 `Запустите сервер на TCP-порту ${p}. При запросе Windows разрешите доступ в доверенной частной сети.`,
 'Создайте комнату. Отправьте друзьям ссылку из лобби; на телефоне её можно открыть в браузере.',
 'Если вход не работает, проверьте, не включена ли изоляция устройств в гостевом Wi-Fi.'
 ]:[
 'Подключитесь к той же домашней сети, что и ведущий, не к гостевому Wi-Fi.',
 `Введите IPv4 ведущего и TCP-порт ${p}, либо вставьте его полную ссылку.`,
 'Нажмите «Проверить адрес», затем «Подключиться к ведущему». Ваш сервер не запускается.',
 'В игре введите имя и код комнаты. Один код без адреса сервера не соединит разные компьютеры.'
 ],
 vpn:role==='host'?[
 'Откройте Hamachi, Radmin VPN или аналогичную программу. Создайте сеть и пригласите друзей.',
 'Выберите IPv4 виртуального адаптера этой программы, а не адрес обычного Wi-Fi.',
 `Запустите Бункер на TCP-порту ${p}. Разрешите входящий TCP только для нужной программы и выбранной сети.`,
 'Создайте комнату и отправьте ссылку из лобби Бункера. Сеть VPN и сервер должны оставаться включёнными.'
 ]:[
 'Установите ту же программу VPN, что использует ведущий, и войдите в его виртуальную сеть.',
 'Скопируйте виртуальный IPv4 ведущего из Hamachi/Radmin, не свой адрес.',
 `Введите этот адрес и TCP-порт ${p} либо вставьте ссылку. Проверьте доступность и подключитесь.`,
 'Введите имя и код комнаты Бункера. Отдельный сервер у игрока не нужен.'
 ],
 public:role==='host'?[
 'Уточните у провайдера, есть ли у вас входящий публичный IPv4. Адрес, показанный сайтом проверки IP, сам по себе этого не доказывает.',
 `В роутере настройте перенаправление TCP ${ep} на локальный IPv4 этого компьютера и TCP ${p}. Закрепите локальный адрес за компьютером.`,
 'Введите белый IPv4 в поле адреса. Разрешите нужный входящий TCP-порт в брандмауэре, не отключая защиту целиком.',
 'Запустите сервер, создайте комнату и отправьте ссылку только доверенным друзьям.',
 'Проверьте соединение с другой сети, например мобильного интернета. Открытие ссылки у себя не подтверждает доступ извне.'
 ]:[
 'Получите от ведущего его публичный адрес с портом или полную ссылку.',
 'Введите адрес и нажмите «Проверить адрес». На вашем роутере перенаправление портов не нужно.',
 'Подключитесь и введите имя. Код комнаты нужен уже после соединения с сервером.',
 'Если ответа нет, ведущий должен проверить свой роутер, брандмауэр и наличие белого IPv4.'
 ]};
 $('guideTitle').textContent=(role==='host'?'Ведущий':'Игрок')+' · '+labels[mode];$('steps').replaceChildren(...data[mode].map(t=>{const li=document.createElement('li');li.textContent=t;return li;}));
 $('important').textContent=mode==='porthole'?'Porthole не выдаёт вам публичный сайт. У каждого игрока свой локальный адрес. Код Porthole и код комнаты Бункера — разные коды.':role==='host'?'Не выключайте компьютер ведущего и сервер до конца партии. Закрытие сервера завершает текущую игру.':'Для подключения нужен адрес ведущего. Код комнаты не заменяет сетевое соединение.';
}
function renderForm(){const busy=['preparing','starting','exporting'].includes(currentPhase),locked=busy||currentPhase==='running';
 document.querySelectorAll('[data-role]').forEach(b=>{b.classList.toggle('selected',b.dataset.role===role);b.setAttribute('aria-pressed',b.dataset.role===role);b.disabled=locked;});document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('selected',b.dataset.mode===mode);b.setAttribute('aria-pressed',b.dataset.mode===mode);b.disabled=locked;});
 $('externalWrap').hidden=!(role==='host'&&mode==='public');$('adapterWrap').hidden=!(role==='host'&&['lan','vpn'].includes(mode));$('addressWrap').hidden=role==='host'&&mode==='porthole';$('publicWarning').hidden=mode!=='public';$('downloadNote').hidden=role!=='host'||runtimeReady;
 $('addressLabel').textContent=role==='guest'?(mode==='porthole'?'Локальный адрес Porthole или ссылка':'Адрес сервера ведущего или ссылка'):(mode==='public'?'Белый IPv4 ведущего':'IPv4 выбранного сетевого адаптера');
 $('address').placeholder=mode==='porthole'?'127.0.0.1':mode==='public'?'Публичный IPv4':mode==='vpn'?'IPv4 из Hamachi / Radmin':'192.168.1.25';
 $('addressNote').textContent=mode==='porthole'?'TCP, не UDP. Этот порт нужно подтвердить у каждого игрока в Porthole.':mode==='public'?'Белый IP вводится вручную. Помощник не проверяет его через сторонние сайты.':'IP выбирается из адаптеров компьютера. Проверьте, что выбран именно нужный Wi-Fi или VPN.';
 if(role==='guest')$('addressNote').textContent='Полная ссылка сохраняет указанный в ней порт и код комнаты. Один код комнаты сюда вводить нельзя.';
 $('start').textContent=role==='guest'?'Подключиться к ведущему':runtimeReady?'Запустить сервер':'Подготовить и запустить';$('start').disabled=locked;$('check').hidden=role!=='guest';$('check').disabled=busy;
 ['port','externalPort','address','adapter','consent'].forEach(id=>$(id).disabled=locked);
 guide();}
function switchChoice(newRole,newMode){savedAddresses[role+':'+mode]=$('address').value;role=newRole;mode=newMode;$('address').value=savedAddresses[role+':'+mode]||'';
 if(role==='host'&&['lan','vpn'].includes(mode)&&!$('address').value){const a=adapters.find(a=>mode==='vpn'?/hamachi|radmin|vpn|tailscale|zerotier/i.test(a.name):!/hamachi|radmin|vpn|tailscale|zerotier/i.test(a.name));if(a)$('address').value=a.ip;}
 $('adapter').value=$('address').value;if(currentPhase==='guest')$('runningActions').hidden=true;$('error').hidden=true;$('checkResult').textContent='';renderForm();}
function showError(e){$('error').hidden=false;$('error').textContent=e.message||String(e);}
async function refresh(){try{const s=await api('status');lastState=s;currentPhase=s.phase;runtimeReady=s.runtime_ready;adapters=s.adapters||[];
 if(!initialized){role=s.settings.role||'host';mode=s.settings.mode||'porthole';$('port').value=s.settings.port||8008;$('externalPort').value=s.settings.external_port||8008;$('address').value=s.settings.address||'';
 for(const a of adapters){const o=document.createElement('option');o.value=a.ip;o.textContent=a.name+' — '+a.ip;$('adapter').appendChild(o);}initialized=true;}
 const titles={idle:'Готов к настройке',guest:'Подключение игрока',preparing:'Подготовка компонентов',starting:'Запуск сервера',running:'Сервер работает',exporting:'Создание автономного комплекта',error:'Нужно ваше внимание'};
 $('statusTitle').textContent=titles[s.phase]||s.phase;$('statusText').textContent=s.message;$('statusBox').className='status '+(s.phase==='running'?'running':['preparing','starting','exporting'].includes(s.phase)?'busy':'');$('badge').textContent=s.phase==='running'?'Сервер включён':'Локальный помощник';
 if(s.error)showError(s.error);$('runningActions').hidden=!s.game_url||!['running','guest','exporting'].includes(s.phase)||s.settings.role!==role||s.settings.mode!==mode;$('openGame').href=s.game_url||'#';$('inviteBox').hidden=s.settings.role==='guest';$('invite').value=s.share_url||'';
 $('stop').hidden=!['running','error'].includes(s.phase);$('export').hidden=!runtimeReady||['preparing','starting','exporting'].includes(s.phase);$('getExport').hidden=!s.export_ready;
 $('log').textContent=s.log||'Журнал появится после запуска сервера.';$('dataPath').textContent=s.data_dir;renderForm();
 }catch(e){showError(e);}}
document.querySelectorAll('[data-role]').forEach(b=>b.onclick=()=>switchChoice(b.dataset.role,mode));document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>switchChoice(role,b.dataset.mode));
$('adapter').onchange=()=>{if($('adapter').value)$('address').value=$('adapter').value;};$('port').oninput=guide;$('externalPort').oninput=guide;
$('launchForm').onsubmit=async e=>{e.preventDefault();$('error').hidden=true;$('start').disabled=true;try{await api('start',settings());await refresh();if(role==='guest')$('openGame').focus();}catch(e){showError(e);renderForm();}};
$('check').onclick=async()=>{$('check').disabled=true;$('checkResult').textContent='Проверка адреса…';try{const r=await api('check',settings());$('checkResult').textContent=r.message;}catch(e){showError(e);}finally{$('check').disabled=false;}};
$('stop').onclick=async()=>{if(!confirm('Остановить сервер? Текущая партия не сохраняется и завершится у всех игроков.'))return;try{await api('stop',{});await refresh();}catch(e){showError(e);}};
$('exit').onclick=async()=>{if(!confirm('Завершить Бункер? Запущенный вами сервер остановится. Текущая партия будет потеряна.'))return;try{await api('exit',{});document.body.replaceChildren(Object.assign(document.createElement('p'),{textContent:'Бункер завершён. Эту вкладку можно закрыть.'}));clearInterval(poll);}catch(e){showError(e);}};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('invite').value);$('copy').textContent='Скопировано';setTimeout(()=>$('copy').textContent='Скопировать адрес',1800);}catch(_){$('invite').select();document.execCommand('copy');}};
$('export').onclick=async()=>{try{await api('export',{});refresh();}catch(e){showError(e);}};
async function saveFile(path,name){try{const r=await fetch('/api/'+path,{headers:{'X-Bunker-Token':token}});if(!r.ok)throw Error('Файл ещё не готов');const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),10000);}catch(e){showError(e);}}
$('getExport').onclick=()=>saveFile('export-file','Bunker_Portable_V4_6.zip');$('getLogs').onclick=()=>saveFile('logs','bunker-server.log');
renderForm();refresh();const poll=setInterval(refresh,1600);
