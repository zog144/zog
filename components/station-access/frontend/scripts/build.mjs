// Force production even when the calling shell uses NODE_ENV=development.
import {spawnSync} from 'node:child_process'
process.env.NODE_ENV='production'
const types=spawnSync(process.execPath,['node_modules/typescript/bin/tsc','-b'],{stdio:'inherit'})
if(types.status!==0)process.exit(types.status??1)
const {build}=await import('vite')
await build({mode:'production'})
