// Development-only adapter: exercise the production Worker with local SQLite/files.
// Never imported by the production build or deployed Worker.
import { DatabaseSync } from 'node:sqlite';
import { mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import worker from '../worker/index.js';
export function previewApi(){return{name:'pdf-local-api',apply:'serve',async configureServer(server){
 const root=resolve('.sites-runtime/preview');await mkdir(root,{recursive:true});
 const db=new DatabaseSync(join(root,'history.sqlite'));
 db.exec('CREATE TABLE IF NOT EXISTS preview_migrations (name TEXT PRIMARY KEY)');
 const journal=JSON.parse(await readFile('drizzle/meta/_journal.json','utf8'));
 for(const migration of journal.entries){if(!db.prepare('SELECT 1 FROM preview_migrations WHERE name=?').get(migration.tag)){db.exec(await readFile(`drizzle/${migration.tag}.sql`,'utf8'));db.prepare('INSERT INTO preview_migrations VALUES (?)').run(migration.tag);}}
 const env={DB:{prepare(sql){return{first:async()=>db.prepare(sql).get(),bind(...args){return{first:async()=>db.prepare(sql).get(...args),all:async()=>({results:db.prepare(sql).all(...args)}),run:async()=>({meta:db.prepare(sql).run(...args)})}}};}},BUCKET:{async put(key,body,metadata){const path=join(root,'objects',key);await mkdir(resolve(path,'..'),{recursive:true});await writeFile(path,Buffer.from(await new Response(body).arrayBuffer()));await writeFile(path+'.meta',JSON.stringify(metadata));},async get(key){try{const path=join(root,'objects',key),bytes=await readFile(path),meta=JSON.parse(await readFile(path+'.meta','utf8'));return{body:new Blob([bytes]).stream(),arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),writeHttpMetadata:h=>h.set('Content-Type',meta.httpMetadata.contentType)}}catch(e){if(e.code==='ENOENT')return null;throw e;}},async delete(key){await rm(join(root,'objects',key),{force:true});await rm(join(root,'objects',key)+'.meta',{force:true});}}};
 server.middlewares.use(async(req,res,next)=>{if(!req.url?.startsWith('/api/')&&!req.url?.startsWith('/files/'))return next();try{const headers=new Headers();for(const [key,value]of Object.entries(req.headers)){if(value)headers.set(key,Array.isArray(value)?value.join(','):value);}headers.set('oai-authenticated-user-id','local-preview-user');const body=['GET','HEAD'].includes(req.method)?undefined:req;const request=new Request(`http://${req.headers.host}${req.url}`,{method:req.method,headers,body,duplex:'half'});const response=await worker.fetch(request,env);res.statusCode=response.status;response.headers.forEach((value,key)=>res.setHeader(key,value));res.end(Buffer.from(await response.arrayBuffer()));}catch(e){res.statusCode=500;res.end(JSON.stringify({detail:e.message}));}});
 server.httpServer?.once('close',()=>db.close());
}};}
