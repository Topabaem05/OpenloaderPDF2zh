const MAX_BYTES = 20 * 1024 * 1024;
const active = new Set(['queued', 'parsing', 'translating', 'rendering']);
const json = (data, status = 200) => Response.json(data, {status, headers:{'Cache-Control':'private, no-store'}});
const artifactNames = {translated_pdf:'translated_mono.pdf', detected_boxes_pdf:'detected_boxes.pdf', structured_json:'structured.json', result_md:'result.md'};
function database(env) { if (!env.DB) throw new Error('기록 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'); return env.DB; }
async function rowFor(env, id, owner) { return database(env).prepare('SELECT * FROM jobs WHERE id = ? AND owner = ?').bind(id, owner).first(); }
function view(row) { const record = JSON.parse(row.record); return {...record, job_id:row.id, filename:row.filename, created_at:row.created_at, target_language:JSON.parse(row.settings).target_language, original_url:`/files/${row.id}/original.pdf`, bytes:row.bytes}; }
async function saveRecord(env, row, record) { await database(env).prepare('UPDATE jobs SET record = ? WHERE id = ? AND owner = ?').bind(JSON.stringify(record), row.id, row.owner).run(); row.record=JSON.stringify(record); }
function backend(env) { if (!env.OPENPDF2ZH_BACKEND_URL || !env.OPENPDF2ZH_BACKEND_TOKEN) return null; const url = new URL(env.OPENPDF2ZH_BACKEND_URL); if(url.protocol!=='https:' || url.username || url.password || url.search || url.hash) throw new Error('번역 서버 HTTPS 설정을 확인해 주세요.'); return url.origin; }
async function upstream(env,path,options={}) { const origin=backend(env); if(!origin) throw new Error('번역 서버를 먼저 연결해 주세요.'); return fetch(origin+path,{...options,redirect:'error',signal:AbortSignal.timeout(60000),headers:{...options.headers,Authorization:`Bearer ${env.OPENPDF2ZH_BACKEND_TOKEN}`}}); }
async function sync(env,row) {
 if(!row.upstream_id || !active.has(JSON.parse(row.record).status)) return row;
 const response=await upstream(env,`/api/jobs/${encodeURIComponent(row.upstream_id)}`);
 if(!response.ok) throw new Error('번역 상태를 가져오지 못했습니다. 원본과 기록은 보관 중입니다.');
 const record=await response.json();
 if(record.status==='succeeded') {
  const links={};
  for(const [key,name] of Object.entries(artifactNames)) {
   if(!record.artifacts?.[key]) continue;
   // Construct the known artifact path, never fetch URLs supplied by a provider.
   const file=await upstream(env,`/files/${encodeURIComponent(row.upstream_id)}/${name}`);
   if(!file.ok) throw new Error('번역 결과를 보관하지 못했습니다. 기록을 다시 열어 재시도해 주세요.');
   await env.BUCKET.put(`${row.owner}/${row.id}/${name}`,file.body,{httpMetadata:{contentType:name.endsWith('.pdf')?'application/pdf':name.endsWith('.json')?'application/json':'text/markdown; charset=utf-8'}});
   links[key]=`/files/${row.id}/${name}`;
  }
  if(!links.translated_pdf) throw new Error('번역 서버가 결과 PDF를 반환하지 않았습니다.');
  record.artifacts=links;
 } else record.artifacts={};
 await saveRecord(env,row,record); return row;
}
async function start(env,row) {
 const current=JSON.parse(row.record);
 if(current.status!=='saved') return row;
 if(!backend(env)) throw new Error('번역 서버가 아직 연결되지 않았습니다. 문서는 안전하게 저장되어 있습니다.');
 const lock=await database(env).prepare("UPDATE jobs SET record = ? WHERE id = ? AND owner = ? AND record = ?").bind(JSON.stringify({...current,status:'queued',message_ko:'번역 서버에 전달하고 있습니다.'}),row.id,row.owner,row.record).run();
 if(!lock.meta.changes) return await rowFor(env,row.id,row.owner);
 try {
  const file=await env.BUCKET.get(`${row.owner}/${row.id}/original.pdf`);
  if(!file) throw new Error('원본 파일을 찾을 수 없습니다.');
  const form=new FormData(); form.set('file',new File([await file.arrayBuffer()],row.filename,{type:'application/pdf'}));
  for(const [key,value] of Object.entries(JSON.parse(row.settings))) form.set(key,String(value));
  const response=await upstream(env,'/api/jobs',{method:'POST',body:form});
  if(!response.ok) throw new Error(`번역 서버가 작업을 받지 못했습니다 (${response.status}).`);
  const result=await response.json();
  if(typeof result.job_id!=='string') throw new Error('번역 서버 응답을 확인해 주세요.');
  await database(env).prepare('UPDATE jobs SET upstream_id = ?, record = ? WHERE id = ? AND owner = ?').bind(result.job_id,JSON.stringify({...result,artifacts:{},status:active.has(result.status)?result.status:'queued'}),row.id,row.owner).run();
  return await rowFor(env,row.id,row.owner);
 } catch(error) {
  // Never automatically retry an uncertain POST: the engine may already be running.
  await saveRecord(env,row,{...current,status:'failed',message_ko:`${error.message} 제출 결과가 불확실할 수 있으므로 번역 서버 기록을 확인해 주세요.`});
  throw error;
 }
}
export default {
 async fetch(request,env) {
  const url=new URL(request.url), path=url.pathname;
  if(!path.startsWith('/api/')&&!path.startsWith('/files/')) return env.ASSETS.fetch(request);
  const owner=request.headers.get('oai-authenticated-user-id');
  if(!owner) return json({detail:'로그인이 필요합니다.'},401);
  if(!['GET','HEAD'].includes(request.method)) {
   if(request.headers.get('origin') && request.headers.get('origin')!==url.origin) return json({detail:'허용되지 않은 요청입니다.'},403);
   if(request.headers.get('sec-fetch-site')==='cross-site') return json({detail:'허용되지 않은 요청입니다.'},403);
  }
  try {
   if(path==='/api/health'&&request.method==='GET') {
    await database(env).prepare('SELECT 1').first();
    return json({status:'ok',translation_ready:Boolean(backend(env)),storage:'cloud',max_upload_bytes:MAX_BYTES});
   }
   if(path==='/api/jobs'&&request.method==='GET') {
    const result=await database(env).prepare('SELECT * FROM jobs WHERE owner = ? ORDER BY created_at DESC LIMIT 200').bind(owner).all();
    return json(result.results.map(view));
   }
   if(path==='/api/jobs'&&request.method==='POST') {
    // Stream bound prevents oversized multipart bodies from exhausting the Worker isolate.
    const reader=request.body?.getReader(); if(!reader) return json({detail:'PDF를 선택해 주세요.'},400);
    const chunks=[];let total=0;
    while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>MAX_BYTES+128*1024){await reader.cancel();return json({detail:'20MB 이하 PDF를 선택해 주세요.'},413);}chunks.push(value);}
    const form=await new Response(new Blob(chunks),{headers:{'content-type':request.headers.get('content-type')||''}}).formData();
    const file=form.get('file');
    if(!(file instanceof File)||!file.name.toLowerCase().endsWith('.pdf')||file.size===0||file.size>MAX_BYTES) return json({detail:'20MB 이하 PDF 파일 하나를 선택해 주세요.'},400);
    if(!(await file.slice(0,5).text()).startsWith('%PDF-')) return json({detail:'올바른 PDF 파일이 아닙니다.'},400);
    const settings={provider:'ctranslate2',target_language:form.get('target_language')||'Korean',page_mode:form.get('page_mode')||'all',render_layout_engine:form.get('render_layout_engine')||'pretext',adjust_render_letter_spacing_for_overlap:'true'};
    if(!['Korean','English'].includes(settings.target_language)||!['all','first','first20'].includes(settings.page_mode)||!['legacy','pretext'].includes(settings.render_layout_engine)) return json({detail:'번역 설정을 확인해 주세요.'},400);
    const id=crypto.randomUUID(), created=new Date().toISOString();
    const record={status:'saved',stage:'saved',progress:0,message_ko:'원본과 번역 설정을 서버에 저장했습니다.',artifacts:{},warnings:[]};
    const key=`${owner}/${id}/original.pdf`;
    await env.BUCKET.put(key,file.stream(),{httpMetadata:{contentType:'application/pdf'}});
    try {await database(env).prepare('INSERT INTO jobs (id,owner,filename,bytes,created_at,settings,record) VALUES (?,?,?,?,?,?,?)').bind(id,owner,file.name.slice(0,240),file.size,created,JSON.stringify(settings),JSON.stringify(record)).run();}
    catch(error){await env.BUCKET.delete(key);throw error;}
    return json(view(await rowFor(env,id,owner)),201);
   }
   const match=path.match(/^\/api\/jobs\/([a-zA-Z0-9-]+)(\/start)?$/);
   if(match) {
    let row=await rowFor(env,match[1],owner); if(!row) return json({detail:'문서를 찾을 수 없습니다.'},404);
    if(request.method==='POST'&&match[2]) row=await start(env,row);
    else if(request.method==='GET'&&!match[2]) row=await sync(env,row);
    else return json({detail:'허용되지 않은 요청입니다.'},405);
    return json(view(row));
   }
   const fileMatch=path.match(/^\/files\/([a-zA-Z0-9-]+)\/([a-z_.]+)$/);
   if(fileMatch&&request.method==='GET') {
    const [,id,name]=fileMatch;
    if(!['original.pdf',...Object.values(artifactNames)].includes(name)||!await rowFor(env,id,owner)) return json({detail:'파일을 찾을 수 없습니다.'},404);
    const object=await env.BUCKET.get(`${owner}/${id}/${name}`); if(!object) return json({detail:'파일을 찾을 수 없습니다.'},404);
    const headers=new Headers({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Disposition':`${url.searchParams.has('download')?'attachment':'inline'}; filename="${name}"`});object.writeHttpMetadata(headers);
    return new Response(object.body,{headers});
   }
   return json({detail:'경로를 찾을 수 없습니다.'},404);
  }catch(error){console.error('PDF request failed',error);return json({detail:error.message||'저장소를 사용할 수 없습니다. 다시 시도해 주세요.'},503);}
 }
};
