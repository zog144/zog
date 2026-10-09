import { expect, test } from 'vitest'
import { ageSeconds, currentHost, currentInventory, lastSeen } from './hostFreshness'
import type { RegistryHost, HostInventory } from '../api'
const stamp='2026-09-20T00:00:00Z'
const now=Date.parse(stamp)
const host: RegistryHost={id:'one',label:'One',provider:'aws',account_id:'123',region:'us-east-1',instance_id:'i-example',workspace_id:'',first_seen:stamp,heartbeat:'recent',last_received:stamp,aws_checked_at:stamp,aws_missing_since:null,aws_fresh:true,aws_state:'running',zog_tagged:true,tag_status:'zog',public_address:'example.test',address_source:'aws',address_stale:false,enrolled:true,report:{},aws:{state:'running'}}
test('ages heartbeat through the threshold without a new response',()=>{
 expect(currentHost(host,now+180000).heartbeat).toBe('recent')
 expect(currentHost(host,now+181000).heartbeat).toBe('overdue')
 expect(currentHost({...host,last_received:null},now).heartbeat).toBe('never')
 expect(lastSeen(stamp,now+35000)).toBe('Seen 35 seconds ago')
 expect(lastSeen(stamp,now+60000)).toBe('Seen 1 minute ago')
 expect(lastSeen(null,now)).toBe('Never reported')
 expect(ageSeconds(stamp,now-5000)).toBe(0)
})
test('expires AWS state, tags, address confidence and counts during a prolonged refresh failure',()=>{
 const snapshot: HostInventory={server_time:stamp,hosts:[host],inventory_status:'complete',scans:[{scope:'123/us-east-1',last_success:stamp,last_attempt:stamp,error:'',instance_count:1}]}
 const current=currentInventory(snapshot,now+601000)
 expect(current.inventory_status).toBe('unavailable')
 expect(current.hosts[0]).toMatchObject({heartbeat:'overdue',aws_state:'unknown',tag_status:'unknown',address_stale:true,public_address:'example.test'})
 expect(snapshot.hosts[0].aws_state).toBe('running')
})
