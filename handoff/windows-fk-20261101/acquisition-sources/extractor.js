
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const payload=data;
const ROOT='C:\\WeGameApps\\rail_apps\\流放之路：降临(2002052)';
const tables=['ItemVisualIdentity','ModType','Stats'];
const out={schema:'pobr-fk-dependency-acquisition/v1',observed_at_utc:new Date().toISOString(),status:'in_progress',install_root:ROOT,decoder:{name:'ooz-wasm',version:'2.0.0',package_sha256:'9d620bfee0d4ec98f304c291a49af4cd5bafaa9b6a1ef6e9248808d2467d05fe',wasm_sha256:'be3ceea0fc7b4a9ea24715781ea55de9645964a8f2347a1b06c0c859a2eb4bcd',execution:'Embedded WASM only; memory-copy/heap-growth imports only; no downloaded JS evaluated'}};
let readBytes=0,resourceCompressed=0,decodedTotal=0,dirDecoded=0,mem,inst,peakRSS=0;const start=performance.now(),CAP=384*1024*1024;
const fail=(ok,m)=>{if(!ok)throw Error(m)},sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const id=s=>({length:Number(s.size),mtime_ns:s.mtimeNs.toString(),file_id:s.ino.toString()});
const same=(a,b)=>a.size===b.size&&a.mtimeNs===b.mtimeNs&&a.ino===b.ino;
function sample(){peakRSS=Math.max(peakRSS,process.memoryUsage().rss);}
function rd(fd,o,n){fail(n>=0&&o>=0&&Number.isSafeInteger(n)&&Number.isSafeInteger(o),'Invalid read');const b=Buffer.alloc(n);let p=0;while(p<n){const x=fs.readSync(fd,b,p,n-p,o+p);fail(x>0,'EOF');p+=x;readBytes+=x;}return b;}
function hdr(reader,fileLen){
 const b=reader(0,60),h={raw32:b.readUInt32LE(0),compressed32:b.readUInt32LE(4),header_size:b.readUInt32LE(8),encoder:b.readUInt32LE(12),flag:b.readUInt32LE(16),raw64:Number(b.readBigUInt64LE(20)),compressed64:Number(b.readBigUInt64LE(28)),count:b.readUInt32LE(36),chunk_size:b.readUInt32LE(40),reserved:[44,48,52,56].map(o=>b.readUInt32LE(o))};
 fail(h.raw32===h.raw64&&h.compressed32===h.compressed64&&h.header_size===48+4*h.count&&h.flag===1&&h.reserved.every(x=>x===0),'Container header mismatch');
 fail(h.chunk_size>0&&h.chunk_size<=8*1024*1024&&h.count===Math.ceil(h.raw64/h.chunk_size)&&h.count<131072,'Chunk geometry invalid');
 const table=reader(60,4*h.count),sizes=new Uint32Array(h.count),offsets=new Float64Array(h.count);let pos=60+table.length;
 for(let i=0;i<h.count;i++){sizes[i]=table.readUInt32LE(i*4);fail(sizes[i]>0&&sizes[i]<16*1024*1024,'Invalid chunk length');offsets[i]=pos;pos+=sizes[i];}
 fail(pos===fileLen&&pos-60-table.length===h.compressed64,'Container length mismatch');return{h,b,table,sizes,offsets,reader};
}
function dec(b,n){
 fail(decodedTotal+n<=CAP,'Decoded cumulative budget exceeded');
 const e=inst.exports,s=e.e(b.length+64),d=e.e(n+64);fail(s&&d,'WASM allocation failed');
 try{let heap=new Uint8Array(mem.buffer);heap.fill(0,s,s+b.length+64);heap.set(b,s);heap.fill(0,d,d+n+64);let z=e.g(s,b.length,d,n);fail(z===n,'Decoded length mismatch');decodedTotal+=n;return Buffer.from(new Uint8Array(mem.buffer,d,n));}finally{e.f(s);e.f(d);}
}
const MASK=(1n<<64n)-1n,M=0xc6a4a7935bd1e995n;
function h64(str,seed){
 let b=Buffer.from(str.toLowerCase(),'utf8'),h=(seed^(BigInt(b.length)*M))&MASK,i=0;
 for(;i+8<=b.length;i+=8){let k=b.readBigUInt64LE(i);k=k*M&MASK;k^=k>>47n;k=k*M&MASK;h=(h^k)*M&MASK;}
 if(i<b.length){let t=0n;for(let j=i;j<b.length;j++)t|=BigInt(b[j])<<BigInt(8*(j-i));h=(h^t)*M&MASK;}
 h^=h>>47n;h=h*M&MASK;return h^(h>>47n);
}
(async()=>{
 const module=await WebAssembly.compile(Buffer.from(payload.wasm,'base64'));payload.wasm=null;
 fail(WebAssembly.Module.imports(module).every(x=>x.module==='a'&&['a','b'].includes(x.name)),'Unexpected imports');
 inst=await WebAssembly.instantiate(module,{a:{a:n=>{n>>>=0;fail(n<=64*1024*1024,'WASM limit');if(n>mem.buffer.byteLength)mem.grow(Math.ceil((n-mem.buffer.byteLength)/65536));return 1;},b:(d,s,n)=>new Uint8Array(mem.buffer).copyWithin(d,s,s+n)}});mem=inst.exports.c;inst.exports.d();

 const items=data.items,expectedIndex=data.expected_index,ip=path.join(ROOT,'Bundles2','_.index.bin'),ib=fs.statSync(ip,{bigint:true});
 fail(['length','mtime_ns','file_id'].every(k=>id(ib)[k]===expectedIndex.before[k]),'Index identity differs from prior pinned lookup; fresh lookup required');
 out.index={relative_path:'Bundles2/_.index.bin',before:id(ib),prior_sha256:expectedIndex.sha256,sha256_recomputed_this_step:false,sha256_basis:'Prior complete hash and exact length/mtime/file-id match before/after this bounded extraction. Index contents not reread.',lookup_source:'Same-run three-dependency prefix lookup and full stable index hash; no full-client traversal'};
 out.extractions=[];
 const send=x=>new Promise((resolve,reject)=>{process.stdout.write(JSON.stringify(x)+'\n',e=>e?reject(e):resolve());});
 const scPins={Words:{bytes:472064,sha256:'88867218a823236c1c9667bd510c892003aa118464dfe48bbe5f4432c917619c'},Ascendancy:{bytes:12771,sha256:'78656ac3382e0eaf307156f16ab22c4c1a4b6f19813e5bbd30fc5ad5096852fc'}};
 const macPins={Words:{bytes:442540,sha256:'30d8da1fd6033a834c74051d9625373e04d8c7a8975e41dc30e46d79fb16aa2a'},Ascendancy:{bytes:15255,sha256:'9cd8bfe9c74115f12cb0ae6cba1bef6f9289ff58276239c888a6d62c2b851635'}};
 for(const it of items){
  if(global.gc)global.gc();
  const r=it.record,filename=path.resolve(ROOT,r.bundle_relative_path);fail(filename.startsWith(path.resolve(ROOT,'Bundles2')+path.sep),'Unsafe bundle path');
  const f=fs.openSync(filename,'r'),before=fs.fstatSync(f,{bigint:true});
  try{
   const c=hdr((o,n)=>rd(f,o,n),Number(before.size));fail(c.h.raw64===r.bundle_raw_bytes,'Bundle raw length differs from index');
   fail(r.offset>=0&&r.length>0&&r.offset+r.length<=c.h.raw64&&r.length<=32*1024*1024,'Resource boundary');
   let first=Math.floor(r.offset/c.h.chunk_size),last=Math.floor((r.offset+r.length-1)/c.h.chunk_size),cost=0;
   for(let i=first;i<=last;i++)cost+=c.sizes[i];fail(resourceCompressed+cost<=64*1024*1024,'Compressed read budget');
   const raw=Buffer.alloc(r.length),chunks=[],ranges=[{offset:0,length:60+c.table.length}];let copied=0;
   for(let i=first;i<=last;i++){
    let compressed=c.reader(c.offsets[i],c.sizes[i]);resourceCompressed+=compressed.length;
    let n=Math.min(c.h.chunk_size,c.h.raw64-i*c.h.chunk_size),decoded=dec(compressed,n),lo=Math.max(0,r.offset-i*c.h.chunk_size),hi=Math.min(n,r.offset+r.length-i*c.h.chunk_size);
    decoded.copy(raw,copied,lo,hi);copied+=hi-lo;
    chunks.push({index:i,compressed_offset:c.offsets[i],compressed_bytes:compressed.length,compressed_sha256:sha(compressed),raw_bytes:n,raw_sha256:sha(decoded),slice_start:lo,slice_end:hi});ranges.push({offset:c.offsets[i],length:c.sizes[i]});
   }
   fail(copied===r.length,'Incomplete resource');
   const after=fs.fstatSync(f,{bigint:true}),pa=fs.statSync(filename,{bigint:true});
   fail(same(before,after)&&same(before,pa),'Bundle changed during read');
   const identity={bytes:raw.length,sha256:sha(raw)};
   let comparison=null;
   if(it.locale==='Simplified Chinese'&&scPins[it.table]){const pin=scPins[it.table];fail(identity.bytes===pin.bytes&&identity.sha256===pin.sha256,'SC pinned raw mismatch');comparison={kind:'required_sc_raw_pin',pin,matches:true};}
   else if(it.locale==='default'&&macPins[it.table]) {const pin=macPins[it.table];comparison={kind:'mac_reference_only_not_source_authentication',pin,matches:identity.bytes===pin.bytes&&identity.sha256===pin.sha256};}
   out.extractions.push({table:it.table,locale:it.locale,path:it.path,record:r,identity,comparison,bundle:{before:id(before),after:id(after),path_after:id(pa),stable:true,header:c.h,read_ranges:ranges,chunks}});
   await send({kind:'resource',table:it.table,locale:it.locale,path:it.path,identity,base64:raw.toString('base64')});sample();
  }finally{fs.closeSync(f);}
 }
 const ia=fs.statSync(ip,{bigint:true});fail(same(ib,ia),'Index metadata changed during extraction');out.index.after=id(ia);out.index.stable=true;
 out.stats={game_bytes_read:readBytes,resource_compressed_bytes_read:resourceCompressed,raw_bytes_decompressed:decodedTotal,peak_sampled_node_rss:peakRSS,max_node_rss:process.resourceUsage().maxRSS*1024,node_elapsed_seconds:(performance.now()-start)/1000};
 out.execution={all_game_handles:'read-only',writes:false,client_or_launcher_started:false,account_or_log_reads:false,installations:false,temporary_files:false,network:'Only previously fixed public WASM decoder package fetched to RAM; no game network access.',node_permissions:'Only Bundles2 read permission; no filesystem write/network/subprocess permission.'};
 await send({kind:'receipt',receipt:out});
})().catch(e=>{console.error(JSON.stringify({status:'blocked',error:e.message,partial:out}));process.exitCode=1;});
