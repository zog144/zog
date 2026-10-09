import fs from 'node:fs'
import path from 'node:path'
import {checkAssetCoverage,reviewPackage,hash} from './license-evidence.mjs'
export function releasePlugin(){
 let root,coverage
 return {name:'station-release-evidence',enforce:'post',apply:'build',
  configResolved(config){
   root=config.root
   if(config.mode!=='production'||process.env.NODE_ENV!=='production')throw new Error('Use npm run build for a production release.')
   coverage=checkAssetCoverage(root,config.publicDir)
  },
  generateBundle(_options,bundle){
   const evidence=JSON.parse(fs.readFileSync(path.join(root,'license-evidence.json'),'utf8'))
   const lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json'),'utf8'))
   const packages=new Map(),helpers=new Set(),modules=[]
   function include(directory){
    if(!packages.has(directory))packages.set(directory,reviewPackage(root,directory,evidence,lock))
   }
   for(const [name,item] of Object.entries(bundle)){
    if(item.type==='asset'){
     if(name!=='index.html'&&!name.endsWith('.css'))throw new Error('Frontend license review: unreviewed emitted asset '+name+' (including worker/image/font output). Add explicit provenance coverage.')
     if(name.endsWith('.css')&&/(?:url\s*\(|@import)/i.test(String(item.source)))throw new Error('Frontend license review: emitted CSS contains an unreviewed resource URL/import.')
     continue
    }
    for(const id of Object.keys(item.modules)){
     if(id.startsWith('\0vite/')){
      if(!['\0vite/modulepreload-polyfill.js','\0vite/preload-helper.js'].includes(id))throw new Error('Frontend license review: unknown generated helper '+id)
      helpers.add(id.slice(1));include(path.join(root,'node_modules/vite'));continue
     }
     const clean=id.replace(/^\0/,'').split('?')[0]
     if(clean.includes('/node_modules/')){
      if(id.startsWith('\0')&&!/\?commonjs-(?:module|exports|es-import|proxy)$/.test(id))throw new Error('Frontend license review: unknown virtual dependency '+id)
      if(id.startsWith('\0'))helpers.add('vite/commonjs-wrapper')
      let directory=path.dirname(clean),found=false
      while(directory.includes('node_modules')){
       const file=path.join(directory,'package.json')
       if(fs.existsSync(file)&&JSON.parse(fs.readFileSync(file,'utf8')).name){include(directory);found=true;break}
       directory=path.dirname(directory)
      }
      if(!found)throw new Error('Frontend license review: cannot identify '+id)
     }else if(id.startsWith('\0')||!clean.startsWith(root+path.sep)||!(clean===path.join(root,'index.html')||clean.startsWith(path.join(root,'src')+path.sep)&&/\.(tsx?|css)$/.test(clean))){
      throw new Error('Frontend license review: unreviewed module/helper/asset '+id)
     }
     modules.push(path.relative(root,clean).split(path.sep).join('/')+(id.startsWith('\0')?'?'+id.split('?')[1]:''))
    }
   }
   // Vite's published notice contains the complete licenses for its bundled helper tooling.
   include(path.join(root,'node_modules/vite'))
   const deps=[...packages.values()].sort((a,b)=>a.name.localeCompare(b.name))
   let legal='===== Zog / station-access original material =====\n'+fs.readFileSync(path.join(root,'../LICENSE'),'utf8')+'\n'
   for(const dep of deps){
    legal+=`\n===== ${dep.name} ${dep.version} =====\nDeclared license: ${dep.license}\nReviewed terms: ${dep.reviewed_terms}\nPublished archive: ${dep.tarball}\nIntegrity: ${dep.integrity}\n\n`
    for(const notice of dep.notices)legal+='----- Upstream '+notice.path+' (verbatim) -----\n'+notice.text+'\n'
   }
   const licenseFile='assets/LICENSES-'+hash(legal).slice(0,12)+'.txt'
   this.emitFile({type:'asset',fileName:licenseFile,source:legal})
   const html=bundle['index.html'];if(!html||html.type!=='asset')throw new Error('Missing frontend entry point')
   html.source=String(html.source).replace('</head>',`<link rel="license" href="/${licenseFile}" /></head>`)
   const sources={}
   function record(relative){const file=path.join(root,relative);if(fs.statSync(file).isDirectory()){for(const name of fs.readdirSync(file).sort())record(path.posix.join(relative,name))}else sources[relative]=hash(fs.readFileSync(file))}
   for(const name of ['src','scripts','license-evidence.json','toolchain.json','package.json','package-lock.json','vite.config.ts','tsconfig.json','index.html','../LICENSE'])record(name)
   const outputs={};for(const [name,item] of Object.entries(bundle))outputs[name]=hash(item.type==='chunk'?item.code:item.source)
   outputs[licenseFile]=hash(legal)
   this.emitFile({type:'asset',fileName:'frontend-build.json',source:JSON.stringify({schema:2,mode:'production',node_env:'production',sources,outputs,licenses:licenseFile,coverage:{...coverage,generated_helpers:[...helpers].sort(),modules:[...new Set(modules)].sort()},dependencies:deps.map(({notices,...dep})=>({...dep,notices:notices.map(({text,...notice})=>notice)}))},null,2)+'\n'})
  }
 }
}
