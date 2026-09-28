import {cp,mkdir,rename,rm} from 'node:fs/promises';
await rm('client-build',{recursive:true,force:true});
await rename('dist','client-build');
await mkdir('dist/server',{recursive:true});
await rename('client-build','dist/client');
await mkdir('dist/.openai',{recursive:true});
await cp('worker/index.js','dist/server/index.js');
await cp('.openai/hosting.json','dist/.openai/hosting.json');
await cp('drizzle','dist/.openai/drizzle',{recursive:true});
