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
 return <div className="pdf-app">
  <header className="topbar"><a className="brand" href="/" aria-label="OpenPDF2ZH 홈"><span className="brand-icon">文</span><span>OpenPDF<span className="brand-light">2ZH</span></span></a><div className="top-meta">문서 번역 작업실 <span className="private-badge">개인 보관함</span></div></header>
  <main className="workspace"><aside className="document-sidebar"><div className="sidebar-heading"><h2>문서 기록</h2><button aria-label="기록 새로고침" onClick={()=>{setError('');void refresh().catch(e=>setError(e.message));}}>↻</button></div><button className="new-document" disabled={busy} onClick={()=>choose(null)}>＋ 새 문서</button><p className="sidebar-description">저장한 문서와 번역 결과를 다시 엽니다.</p><div className="history-list" aria-busy={loading}>{loading?<p className="muted">기록을 불러오는 중…</p>:jobs.length===0?<div className="history-empty"><span>아직 저장된 문서가 없습니다</span><small>PDF를 올려 첫 문서를 보관하세요.</small></div>:jobs.map(item=><button disabled={busy} className={`history-item ${selected?.job_id===item.job_id?'selected':''}`} key={item.job_id} onClick={()=>void open(item)}><span className="file-glyph">PDF</span><span className="history-copy"><strong>{item.filename||item.job_id}</strong><small>{item.created_at?new Date(item.created_at).toLocaleDateString('ko-KR'):''} · {labels[item.status]||item.status}</small></span></button>)}</div><p className="sidebar-footer">원본 · 번역본 · 작업 기록<br/>로그인한 계정의 서버 보관함</p></aside>
  <section className="document-workspace"><div className="workspace-heading"><div><span className="eyebrow">PDF TRANSLATION</span><h1>{selected?.filename||file?.name||'문서의 형식은 그대로, 언어는 새롭게.'}</h1></div><span className="document-status">{selected?labels[selected.status]||selected.status:'새 문서'}</span></div>
   {error&&<div role="alert" className="error-message">{error}</div>}{notice&&<div role="status" className="notice-message">{notice}</div>}
   {!file&&!selected?<UploadPanel file={file} onFileChange={choose}/>:<><div className="preview-toolbar"><div className="preview-tabs" role="tablist" aria-label="PDF 미리보기"><button role="tab" aria-selected={tab==='original'} onClick={()=>{setTab('original');setPage(1);}}>원본</button><button role="tab" aria-selected={tab==='translated'} disabled={!translated} onClick={()=>{setTab('translated');setPage(1);}}>번역본</button></div><div className="page-controls"><button aria-label="이전 페이지" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>‹</button><span>{page} / {pageCount}</span><button aria-label="다음 페이지" disabled={page>=pageCount} onClick={()=>setPage(p=>p+1)}>›</button></div></div><div className="document-viewer">{src?<Suspense fallback={<p>PDF를 불러오는 중…</p>}><PdfPreview src={src} pageNumber={page} zoomPercent={100} onDocumentLoaded={setPageCount}/></Suspense>:<p>이 기록에는 원본 미리보기가 없습니다.</p>}</div></>}
   <div className="flow-strip"><span><b>01</b> 문서 분석</span><span><b>02</b> 텍스트 번역</span><span><b>03</b> 원본 위치에 재배치</span></div>
   {selected&&<div className="job-progress" aria-live="polite"><strong>{selected.message_ko||labels[selected.status]}</strong>{active&&<progress value={selected.progress||0} max="1"/>}{selected.warnings?.map((warning,i)=><p className="warning" key={i}>{warning}</p>)}</div>}
  </section>
  <aside className="translation-sidebar"><div className="settings-heading"><span className="eyebrow">TRANSLATION</span><h2>번역 설정</h2></div><fieldset disabled={busy||Boolean(selected)}><label>번역 언어<select value={language} onChange={e=>setLanguage(e.target.value)}><option value="Korean">한국어</option><option value="English">English</option></select></label><label>페이지 범위<select value={pages} onChange={e=>setPages(e.target.value)}><option value="all">전체 페이지</option><option value="first">첫 페이지 · 테스트</option><option value="first20">처음 20페이지</option></select></label><label>문서 배치<select value={layout} onChange={e=>setLayout(e.target.value)}><option value="pretext">형식 유지 · 겹침 최소화</option><option value="legacy">기본 형식 유지</option></select></label></fieldset><div className="layout-note"><strong>원본 형식 유지</strong><p>기존 PDF의 표·그림·수식 위치를 바탕으로 번역문을 배치합니다. 긴 문장이나 복잡한 표에서 생기는 넘침은 완료 후 경고로 확인하세요.</p></div>
   <div className="server-state"><strong>{health?.translation_ready?'번역 서버 연결됨':'번역 서버 연결 대기'}</strong><p>{health?.translation_ready?'저장한 문서로 번역을 시작할 수 있습니다.':'지금은 원본 업로드와 기록 저장을 사용할 수 있습니다. 번역은 서버 연결 후 이용할 수 있습니다.'}</p></div>
   {!selected?<button className="primary-action" disabled={!file||busy||!health} onClick={()=>void save()}>{busy?'저장 중…':health?.storage==='cloud'?'서버에 문서 저장':'번역 시작'}</button>:selected.status==='saved'?<button className="primary-action" disabled={busy||!health?.translation_ready} onClick={()=>void translate()}>{busy?'작업 시작 중…':'형식 유지하여 번역'}</button>:active?<button className="primary-action" disabled>번역 처리 중…</button>:null}
   {selected?.target_language&&<p className="saved-setting">저장한 번역 언어: {selected.target_language}</p>}
   {selected?.original_url&&<a className="download-link" href={resolveBackendUrl(selected.original_url,base)+'?download=1'}>원본 PDF 다운로드 ↓</a>}
   {Object.entries(selected?.artifacts||{}).filter(([,href])=>typeof href==='string').map(([key,href])=><a className="download-link" key={key} href={resolveBackendUrl(href,base)+'?download=1'}>{({translated_pdf:'번역 PDF',detected_boxes_pdf:'영역 확인 PDF',structured_json:'구조 JSON',result_md:'번역 Markdown'} as Record<string,string>)[key]||key} 다운로드 ↓</a>)}
   <p className="retention-note">저장한 원본과 완료된 번역은 브라우저를 닫아도 남습니다. 번역 결과를 다시 열면 서버의 완료 상태를 확인합니다.</p>
  </aside></main><footer className="bottom-bar"><span>OpenPDF2ZH</span><a href="https://github.com/Topabaem05/OpenloaderPDF2zh" target="_blank" rel="noreferrer">소스 코드 ↗</a></footer>
 </div>;
}
