import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import {reviewPackage,checkAssetCoverage,filesUnder,hash} from './license-evidence.mjs'
const root=path.resolve('.'),evidence=JSON.parse(fs.readFileSync('license-evidence.json')),lock=JSON.parse(fs.readFileSync('package-lock.json'))
test('included react package keeps complete published notice, identity and attribution',()=>{
 const result=reviewPackage(root,path.join(root,'node_modules/react'),evidence,lock)
 assert.equal(result.notices[0].text,fs.readFileSync('node_modules/react/LICENSE','utf8'))
 assert.match(result.notices[0].text,/Copyright \(c\) Meta Platforms/)
 assert.equal(result.status,'reviewed');assert.equal(result.integrity,lock.packages['node_modules/react'].integrity)
})
test('missing, ambiguous or changed required evidence is actionable',()=>{
 assert.throws(()=>reviewPackage(root,path.join(root,'node_modules/react'),{},lock),/missing or unresolved evidence.*react@.*license-evidence.json/)
 const changed=structuredClone(evidence);changed.packages['react@19.2.0'].status='unresolved'
 assert.throws(()=>reviewPackage(root,path.join(root,'node_modules/react'),changed,lock),/missing or unresolved/)
 changed.packages['react@19.2.0'].status='reviewed';changed.packages['react@19.2.0'].notices[0].sha256='bad'
 assert.throws(()=>reviewPackage(root,path.join(root,'node_modules/react'),changed,lock),/missing\/changed required notice/)
})
test('unreviewed installed bytes and different registry identity fail',()=>{
 const changed=structuredClone(evidence);changed.packages['react@19.2.0'].published_files_sha256='bad'
 assert.throws(()=>reviewPackage(root,path.join(root,'node_modules/react'),changed,lock),/installed files differ/)
 const other=structuredClone(lock);other.packages['node_modules/react'].resolved='https://other.example/react.tgz'
 assert.throws(()=>reviewPackage(root,path.join(root,'node_modules/react'),evidence,other),/registry\/archive identity/)
})
test('nested nonstandard reviewed evidence is retained verbatim, not guessed from package.json',()=>{
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'license-fixture-'))
 try{
  const dir=path.join(temporary,'node_modules/example');fs.mkdirSync(path.join(dir,'legal'),{recursive:true})
  fs.writeFileSync(path.join(dir,'package.json'),JSON.stringify({name:'example',version:'1.0.0',license:'MIT OR Apache-2.0'}))
  const text='Copyright Fixture Authors\nMIT OR Apache-2.0\nAdditional attribution and an upstream exception retained.\n'
  fs.writeFileSync(path.join(dir,'legal/permissions.txt'),text)
  const files=filesUnder(dir),digest=hash(files.map(f=>f+'\0'+hash(fs.readFileSync(path.join(dir,f)))+'\n').join(''))
  const review={status:'reviewed',reviewed_terms:'Fixture only',declared_license:'MIT OR Apache-2.0',published_file_count:files.length,published_files_sha256:digest,tarball:'https://registry.example/example.tgz',integrity:'fixture',notices:[{path:'legal/permissions.txt',sha256:hash(text)}]}
  const result=reviewPackage(temporary,dir,{packages:{'example@1.0.0':review}},{packages:{'node_modules/example':{version:'1.0.0',resolved:review.tarball,integrity:review.integrity}}})
  assert.equal(result.notices[0].text,text)
  fs.unlinkSync(path.join(dir,'legal/permissions.txt'))
  assert.throws(()=>reviewPackage(temporary,dir,{packages:{'example@1.0.0':review}},{packages:{'node_modules/example':{version:'1.0.0',resolved:review.tarball,integrity:review.integrity}}}),/installed files differ/)
 }finally{fs.rmSync(temporary,{recursive:true,force:true})}
})
test('copied public files, nested public node_modules, CSS URLs, workers and binary assets fail closed',()=>{
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'coverage-fixture-'))
 try{
  fs.mkdirSync(path.join(temporary,'src'));fs.writeFileSync(path.join(temporary,'index.html'),'<div></div>')
  assert.deepEqual(checkAssetCoverage(temporary,false).workers,[])
  fs.mkdirSync(path.join(temporary,'public/node_modules'),{recursive:true});fs.writeFileSync(path.join(temporary,'public/node_modules/unreviewed.svg'),'<svg/>')
  assert.throws(()=>checkAssetCoverage(temporary,path.join(temporary,'public')),/copied public assets/)
  for(const [name,content,pattern] of [['style.css','a {background:url(https://example/font.woff)}',/CSS URL/],['worker.ts','new Worker("worker.js")',/worker or embedded/],['logo.png','fixture',/unreviewed source asset/]]){
   const file=path.join(temporary,'src',name);fs.writeFileSync(file,content);assert.throws(()=>checkAssetCoverage(temporary,false),pattern);fs.unlinkSync(file)
  }
 }finally{fs.rmSync(temporary,{recursive:true,force:true})}
})

test('unreviewed emitted worker/asset and generated helper are rejected',async()=>{
 const {releasePlugin}=await import('./release-plugin.mjs')
 const old=process.env.NODE_ENV;process.env.NODE_ENV='production'
 try{
  const plugin=releasePlugin();plugin.configResolved({root,mode:'production',publicDir:false})
  assert.throws(()=>plugin.generateBundle({}, {'worker.js':{type:'asset',source:'unreviewed worker'}}),/unreviewed emitted asset.*worker.js/)
  assert.throws(()=>plugin.generateBundle({}, {'main.js':{type:'chunk',modules:{'\0vite/new-helper.js':{}}}}),/unknown generated helper/)
 }finally{if(old===undefined)delete process.env.NODE_ENV;else process.env.NODE_ENV=old}
})
