import fs from 'node:fs'
import path from 'node:path'
import {createHash} from 'node:crypto'
export const hash=data=>createHash('sha256').update(data).digest('hex')
const fail=message=>{throw new Error('Frontend license review: '+message)}
export function filesUnder(root,skipDependencies=false){
 const files=[]
 function visit(directory){for(const name of fs.readdirSync(directory).sort()){
  if(skipDependencies&&name==='node_modules')continue
  const file=path.join(directory,name),stat=fs.lstatSync(file)
  if(stat.isSymbolicLink())fail('symlink needs explicit review: '+file)
  if(stat.isDirectory())visit(file);else if(stat.isFile())files.push(path.relative(root,file).split(path.sep).join('/'))
 }}
 visit(root);return files.sort()
}
export function reviewPackage(root,directory,evidence,lock){
 const metadata=JSON.parse(fs.readFileSync(path.join(directory,'package.json'),'utf8'))
 const key=metadata.name+'@'+metadata.version,review=evidence?.packages?.[key]
 if(!review||review.status!=='reviewed'||!review.reviewed_terms||!review.notices?.length)fail('missing or unresolved evidence for '+key+'. Review its published archive and record exact notices in license-evidence.json.')
 if(typeof metadata.license!=='string'||!metadata.license.trim()||review.declared_license!==metadata.license)fail(key+' declaration changed; review the supplied legal text again.')
 const locked=lock?.packages?.[path.relative(root,directory).split(path.sep).join('/')]
 if(!locked||locked.version!==metadata.version||locked.resolved!==review.tarball||locked.integrity!==review.integrity)fail(key+' registry/archive identity differs from the reviewed lockfile pin.')
 const files=filesUnder(directory,true),digests=Object.fromEntries(files.map(file=>[file,hash(fs.readFileSync(path.join(directory,file)))]))
 if(files.length!==review.published_file_count||hash(files.map(file=>file+'\0'+digests[file]+'\n').join(''))!==review.published_files_sha256)fail(key+' installed files differ from the reviewed published package. Run npm ci or review the new artifact.')
 const candidates=files.filter(file=>/license|licence|copying|notice|copyright|authors/i.test(path.basename(file)))
 for(const file of candidates)if(!review.notices.some(notice=>notice.path===file))fail(key+' has unreviewed legal evidence: '+file)
 const notices=review.notices.map(notice=>{
  if(!files.includes(notice.path)||digests[notice.path]!==notice.sha256)fail(key+' missing/changed required notice '+notice.path)
  const text=fs.readFileSync(path.join(directory,notice.path),'utf8')
  if(!text.trim()||text.includes('\ufffd'))fail(key+' requires a reviewed, nonempty UTF-8 notice: '+notice.path)
  return {...notice,bytes:Buffer.byteLength(text),text}
 })
 return {...review,license:metadata.license,notices}
}
export function checkAssetCoverage(root,publicDir){
 if(publicDir&&fs.existsSync(publicDir)&&filesUnder(publicDir).length)fail('copied public assets are not reviewed. Add explicit origin/license evidence and coverage before shipping public/.')
 for(const relative of filesUnder(path.join(root,'src'))){
  if(!/\.(tsx?|css)$/.test(relative))fail('unreviewed source asset '+relative+'; add explicit origin/license coverage.')
  const text=fs.readFileSync(path.join(root,'src',relative),'utf8')
  if(/\.css$/.test(relative)&&/(?:url\s*\(|@import)/i.test(text))fail('CSS URL/import needs explicit font/image/style provenance: '+relative)
  if(!/\.test\.[^.]+$/.test(relative)&&/(?:new\s+(?:SharedWorker|Worker)\s*\(|serviceWorker\s*\.\s*register|Worklet\s*\.\s*addModule|[?&](?:worker|sharedworker|inline)(?:[&'"`]|$)|data:(?:image|font|application\/wasm))/i.test(text))fail('worker or embedded asset needs explicit license coverage: '+relative)
 }
 const html=fs.readFileSync(path.join(root,'index.html'),'utf8')
 if(/<(?:img|image|source|video|audio|object|embed)\b|data:|rel=["'](?:icon|stylesheet)["']/i.test(html))fail('HTML asset needs explicit license coverage before release.')
 return {public_assets:[],fonts:[],images:[],workers:[],css:'First-party src CSS only; URLs/imports rejected pending explicit review.',external_runtime:'noVNC is separately served and is not part of this bundle or this license review.'}
}
