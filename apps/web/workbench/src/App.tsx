import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { UploadPanel } from './components/UploadPanel';
import { buildBackendUrl, normalizeApiBaseUrl, resolveBackendUrl } from './lib/api-url';
import './workbench.css';
const PdfPreview=lazy(()=>import('./components/PdfCanvasPreview'));
type RecordItem={job_id:string;filename?:string;status:string;progress?:number;created_at?:string;target_language?:string;message_ko?:string;warnings?:string[];original_url?:string;artifacts?:Record<string,string>};
const base=normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
const busyStates=new Set(['queued','parsing','translating','rendering']);
const labels:Record<string,string>={saved:'저장됨',queued:'대기 중',parsing:'문서 분석',translating:'번역 중',rendering:'PDF 조립',succeeded:'번역 완료',failed:'실패',quota_exceeded:'한도 초과',queue_busy:'서버 혼잡'};
async function api(path:string,options?:RequestInit){const response=await fetch(buildBackendUrl(path,base),options);const value=await response.json();if(!response.ok)throw new Error(value.detail||'요청에 실패했습니다. 다시 시도해 주세요.');return value;}
export default function App(){
 const [file,setFile]=useState<File|null>(null),[localUrl,setLocalUrl]=useState('');
 const [jobs,setJobs]=useState<RecordItem[]>([]),[selected,setSelected]=useState<RecordItem|null>(null);
 const [health,setHealth]=useState<{translation_ready:boolean;storage:string}|null>(null);
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
 const [language,setLanguage]=useState('Korean'),[pages,setPages]=useState('all'),[layout,setLayout]=useState('pretext');
 const [tab,setTab]=useState<'original'|'translated'>('original'),[page,setPage]=useState(1),[pageCount,setPageCount]=useState(1);
 const requestSerial=useRef(0);
 const refresh=async()=>{const values=await api('/api/jobs');setJobs(values);};
 useEffect(()=>{
  const context=(document as Document & {modelContext?:{registerTool:(tool:unknown,options:{signal:AbortSignal})=>void}}).modelContext;
  if(!context?.registerTool)return;
  const lifecycle=new AbortController();
  try{context.registerTool({name:'list_saved_documents',description:'현재 계정의 서버 문서 기록을 불러오고 보관함을 새로고칩니다.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:async(input:unknown)=>{if(!input||typeof input!=='object'||Object.keys(input).length)throw new Error('빈 객체를 입력해 주세요.');const records=await api('/api/jobs');setJobs(records);return records.map((item:RecordItem)=>({id:item.job_id,filename:item.filename,status:item.status}));}},{signal:lifecycle.signal});}catch{ /* Browsers without the experimental API use the regular interface. */ }
  return()=>lifecycle.abort();
 },[]);

 useEffect(()=>{Promise.all([api('/api/health').then(setHealth),refresh()]).catch(e=>setError(e.message)).finally(()=>setLoading(false));},[]);
 useEffect(()=>{if(!file){setLocalUrl('');return;}const url=URL.createObjectURL(file);setLocalUrl(url);return()=>URL.revokeObjectURL(url);},[file]);
 useEffect(()=>{if(!selected||!busyStates.has(selected.status))return;let cancelled=false;let timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{const value=await api(`/api/jobs/${selected.job_id}`);if(cancelled)return;setSelected(value);setJobs(items=>items.map(item=>item.job_id===value.job_id?value:item));if(busyStates.has(value.status))timer=setTimeout(poll,1800);}catch(e){if(!cancelled){setError((e as Error).message);timer=setTimeout(poll,10000);}}};void poll();return()=>{cancelled=true;clearTimeout(timer);};},[selected?.job_id,selected?.status]);
 const choose=(value:File|null)=>{requestSerial.current++;setFile(value);setSelected(null);setError('');setNotice('');setTab('original');setPage(1);setPageCount(1);};
 const open=async(item:RecordItem)=>{const serial=++requestSerial.current;setFile(null);setSelected(item);setPage(1);setPageCount(1);setTab(item.status==='succeeded'?'translated':'original');setError('');try{const value=await api(`/api/jobs/${item.job_id}`);if(serial===requestSerial.current){setSelected(value);setJobs(items=>items.map(row=>row.job_id===value.job_id?value:row));}}catch(e){setError((e as Error).message);}};
 const save=async()=>{if(!file)return;setBusy(true);setError('');try{const form=new FormData();form.set('file',file);form.set('provider','ctranslate2');form.set('target_language',language);form.set('page_mode',pages);form.set('render_layout_engine',layout);form.set('adjust_render_letter_spacing_for_overlap','true');const value=await api('/api/jobs',{method:'POST',body:form});setSelected(value);setNotice(health?.storage==='cloud'?'원본과 설정이 서버에 저장되었습니다.':'번역 작업을 시작했습니다.');await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const translate=async()=>{if(!selected)return;setBusy(true);setError('');try{const value=await api(`/api/jobs/${selected.job_id}/start`,{method:'POST'});setSelected(value);await refresh();}catch(e){setError((e as Error).message);await refresh().catch(()=>{});}finally{setBusy(false);}};
 const original=localUrl||resolveBackendUrl(selected?.original_url,base)||'';
 const translated=resolveBackendUrl(selected?.artifacts?.translated_pdf,base)||'';
 const src=tab==='translated'?translated:original;
 const active=selected&&busyStates.has(selected.status);
 return <div className="gradio-app">
  <header className="app-header"><h1>OpenPDF2ZH</h1><p>PDF를 업로드하고, 원본 형식을 유지해 번역하세요.</p></header>
  {error&&<div role="alert" className="message error">{error}</div>}
  {notice&&<div role="status" className="message success">{notice}</div>}
  <main className="gradio-columns">
   <section className="input-column" aria-label="입력 및 설정">
    <div className="component"><div className="component-label">입력 PDF <span>최대 20MB</span></div>
     {file||selected?<div className="selected-file"><span className="pdf-tag">PDF</span><div><strong>{selected?.filename||file?.name}</strong><small>{file?`${(file.size/1024).toFixed(1)} KB`:'서버에 보관된 원본'}</small></div><button className="clear-file" disabled={busy} aria-label="문서 선택 해제" onClick={()=>choose(null)}>×</button></div>:<UploadPanel file={file} onFileChange={choose}/>}
    </div>
    <fieldset disabled={busy||Boolean(selected)}><div className="settings-row"><label className="component">번역 언어<select value={selected?.target_language||language} onChange={e=>setLanguage(e.target.value)}><option value="Korean">한국어</option><option value="English">English</option></select></label><label className="component">페이지 범위<select value={pages} onChange={e=>setPages(e.target.value)}><option value="all">전체 페이지</option><option value="first">첫 페이지</option><option value="first20">처음 20페이지</option></select></label></div>
     <label className="component layout-select">레이아웃<select value={layout} onChange={e=>setLayout(e.target.value)}><option value="pretext">형식 유지 · 겹침 최소화</option><option value="legacy">기본 형식 유지</option></select></label>
    </fieldset>
    <details className="format-info"><summary>형식 유지 안내</summary><p>기존 PDF의 표·그림·수식 위치에 맞춰 번역문을 배치합니다. 문장이 길거나 표가 복잡하면 일부 넘침이 발생할 수 있으며, 완료 후 경고로 확인할 수 있습니다.</p></details>
    <div className="action-row"><button className="secondary" disabled={busy||(!file&&!selected)} onClick={()=>choose(null)}>초기화</button><button className="save-button" disabled={!file||busy||Boolean(selected)||!health} onClick={()=>void save()}>{busy&&!selected?'저장 중…':'서버에 저장'}</button></div>
    <button className="primary-action" disabled={busy||!selected||selected.status!=='saved'||!health?.translation_ready} onClick={()=>void translate()}>{active?'번역 처리 중…':busy&&selected?'시작 중…':'번역 실행'}</button>
    <div className={`server-state ${health?.translation_ready?'ready':''}`} role="status"><strong>{health?.translation_ready?'번역 서버 연결됨':'번역 서버 연결 대기'}</strong><p>{health?.translation_ready?'문서를 서버에 저장한 뒤 번역을 실행하세요.':'원본 업로드·미리보기·기록 저장은 사용 가능합니다. 번역 서버가 연결되면 번역 실행이 활성화됩니다.'}</p></div>
   </section>
   <section className="output-column" aria-label="미리보기 및 결과">
    <div className="component preview-component"><div className="preview-toolbar"><div className="preview-tabs" role="tablist" aria-label="PDF 미리보기"><button role="tab" aria-selected={tab==='original'} onClick={()=>{setTab('original');setPage(1);}}>원본 미리보기</button><button role="tab" aria-selected={tab==='translated'} disabled={!translated} onClick={()=>{setTab('translated');setPage(1);}}>번역 결과</button></div>{src&&<div className="page-controls"><button aria-label="이전 페이지" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>‹</button><span>{page} / {pageCount}</span><button aria-label="다음 페이지" disabled={page>=pageCount} onClick={()=>setPage(p=>p+1)}>›</button></div>}</div>
     <div className="document-viewer">{src?<Suspense fallback={<p>PDF를 불러오는 중…</p>}><PdfPreview src={src} pageNumber={page} zoomPercent={100} onDocumentLoaded={setPageCount}/></Suspense>:<div className="preview-empty"><span aria-hidden="true">▤</span><p>PDF 미리보기가 여기에 표시됩니다</p><small>왼쪽에서 파일을 업로드하세요.</small></div>}</div>
    </div>
    <div className="component status-component"><div className="component-label">작업 상태 <span>{selected?labels[selected.status]||selected.status:'준비'}</span></div><p aria-live="polite">{selected?.message_ko||(file?'원본을 확인한 후 서버에 저장해 주세요.':'PDF 파일을 기다리고 있습니다.')}</p>{active&&<progress value={selected?.progress||0} max="1"/>}{selected?.warnings?.map((warning,i)=><p className="warning" key={i}>{warning}</p>)}</div>
    {selected?.original_url&&<a className="download-link" download href={resolveBackendUrl(selected.original_url,base)+'?download=1'}>↓ 원본 PDF 다운로드</a>}
    {Object.entries(selected?.artifacts||{}).filter(([,href])=>typeof href==='string').map(([key,href])=><a className="download-link" download key={key} href={resolveBackendUrl(href,base)+'?download=1'}>↓ {({translated_pdf:'번역 PDF',detected_boxes_pdf:'영역 확인 PDF',structured_json:'구조 JSON',result_md:'번역 Markdown'} as Record<string,string>)[key]||key} 다운로드</a>)}
   </section>
  </main>
  <section className="component history-component"><div className="history-heading"><div><h2>저장된 문서</h2><p>브라우저를 닫아도 원본과 완료된 번역 기록이 남습니다.</p></div><button className="secondary" aria-label="기록 새로고침" onClick={()=>{setError('');void refresh().catch(e=>setError(e.message));}}>새로고침</button></div><div className="history-list" aria-busy={loading}>{loading?<p className="history-empty">기록을 불러오는 중…</p>:jobs.length===0?<p className="history-empty">저장된 문서가 없습니다.</p>:jobs.map(item=><button disabled={busy} className={`history-item ${selected?.job_id===item.job_id?'selected':''}`} key={item.job_id} onClick={()=>void open(item)}><span className="pdf-tag">PDF</span><span className="history-copy"><strong>{item.filename||item.job_id}</strong><small>{item.created_at?new Date(item.created_at).toLocaleString('ko-KR'):''}</small></span><span className="status-pill">{labels[item.status]||item.status}</span></button>)}</div></section>
  <footer><span>개인 문서 보관함 · OpenPDF2ZH</span><a href="https://github.com/Topabaem05/OpenloaderPDF2zh" target="_blank" rel="noreferrer">소스 코드 ↗</a></footer>
 </div>;
}
