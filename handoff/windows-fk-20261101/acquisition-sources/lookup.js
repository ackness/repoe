
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const ROOT='C:\\WeGameApps\\rail_apps\\流放之路：降临(2002052)';
const tables=['ItemVisualIdentity','ModType','Stats'];
const out={schema:'pobr-sc-names-probe/v1',observed_at_utc:new Date().toISOString(),status:'in_progress',install_root:ROOT,decoder:{name:'ooz-wasm',version:'2.0.0',package_sha256:'9d620bfee0d4ec98f304c291a49af4cd5bafaa9b6a1ef6e9248808d2467d05fe',wasm_sha256:'be3ceea0fc7b4a9ea24715781ea55de9645964a8f2347a1b06c0c859a2eb4bcd',execution:'Embedded WASM only; memory-copy/heap-growth imports only; no downloaded JS evaluated'}};
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
 const ip=path.join(ROOT,'Bundles2','_.index.bin'),fd=fs.openSync(ip,'r'),before=fs.fstatSync(fd,{bigint:true});
 let raw;
 try{
  const c=hdr((o,n)=>rd(fd,o,n),Number(before.size));fail(c.h.raw64<CAP,'Index too large');raw=Buffer.alloc(c.h.raw64);
  const hash=crypto.createHash('sha256').update(c.b).update(c.table);
  for(let i=0;i<c.h.count;i++){let b=c.reader(c.offsets[i],c.sizes[i]);hash.update(b);let n=Math.min(c.h.chunk_size,c.h.raw64-i*c.h.chunk_size);dec(b,n).copy(raw,i*c.h.chunk_size);if(i%32===0)sample();}
  const after=fs.fstatSync(fd,{bigint:true}),pa=fs.statSync(ip,{bigint:true});
  out.index={relative_path:'Bundles2/_.index.bin',before:id(before),after:id(after),path_after:id(pa),stable:same(before,after)&&same(before,pa),sha256:hash.digest('hex'),header:c.h,read_passes:1,read_bytes:Number(before.size),all_chunks_validated:true};
  fail(out.index.stable,'Index changed');
 }finally{fs.closeSync(fd);}
 let p=0;function u32(){fail(p+4<=raw.length,'Index overflow');let n=raw.readUInt32LE(p);p+=4;return n;}
 const bc=u32(),bundles=[];fail(bc<1000000,'Bundle count');
 for(let i=0;i<bc;i++){let n=u32();fail(n>0&&n<4096&&p+n+4<=raw.length,'Bundle name');const name=raw.toString('ascii',p,p+n);p+=n;bundles.push({name,raw:u32()});}
 const fc=u32(),ft=p;fail(ft+fc*20+24<=raw.length,'File table');p+=fc*20;
 const dc=u32(),dt=p,de=dt+dc*20;fail(de+60<=raw.length,'Directory table');
 let root=raw.readBigUInt64LE(dt);fail(root!==0x07e47507b4a92e53n,'FNV unsupported');
 let inv=1n;for(let i=0;i<6;i++)inv=inv*(2n-M*inv)&MASK;let v=root^(root>>47n);v=v*inv&MASK;const seed=v^(v>>47n);fail(h64('',seed)===root,'Seed');
 const dr=i=>{let o=dt+i*20;return{record:i,hash:raw.readBigUInt64LE(o),offset:raw.readUInt32LE(o+8),size:raw.readUInt32LE(o+12),recursive_size:raw.readUInt32LE(o+16)};};
 const prefixQueries=['Data/Balance','Data/Balance/','Data/Simplified Chinese','Data/Simplified Chinese/','Data/Balance/Simplified Chinese','Data/Balance/Simplified Chinese/'];
 const ph=new Map(prefixQueries.map(x=>[h64(x,seed).toString(),x])),roots=[];
 for(let i=0;i<dc;i++){let d=dr(i),q=ph.get(d.hash.toString());if(q)roots.push({...d,prefix:q,hash:'0x'+d.hash.toString(16)});}
 out.lookup={bundle_count:bc,file_count:fc,directory_count:dc,seed:'0x'+seed.toString(16),seed_verified:true,prefix_records:roots};
 const nested=hdr((o,n)=>{fail(o+n<=raw.length-de,'Directory container read overflow');return raw.subarray(de+o,de+o+n);},raw.length-de);
 out.directory_container={header:nested.h,selected_chunks:[],raw_bytes_decoded:0};
 const cache=new Map();
 function range(o,n){fail(o+n<=nested.h.raw64,'Directory range outside raw');const b=Buffer.alloc(n);let copied=0;
  for(let ci=Math.floor(o/nested.h.chunk_size);ci<=Math.floor((o+n-1)/nested.h.chunk_size);ci++){
   if(!cache.has(ci)){let c=nested.reader(nested.offsets[ci],nested.sizes[ci]),sz=Math.min(nested.h.chunk_size,nested.h.raw64-ci*nested.h.chunk_size);cache.set(ci,dec(c,sz));dirDecoded+=sz;out.directory_container.selected_chunks.push(ci);}
   let cb=cache.get(ci),base=ci*nested.h.chunk_size,lo=Math.max(0,o-base),hi=Math.min(cb.length,o+n-base);cb.copy(b,copied,lo,hi);copied+=hi-lo;
  }return b;
 }
 const selected=new Map();
 for(const r of roots){
  fail(r.size<=r.recursive_size&&r.offset+r.recursive_size<=nested.h.raw64,'Recursive directory range invalid');
  for(let i=0;i<dc;i++){const d=dr(i);if(d.offset>=r.offset&&d.offset+d.size<=r.offset+r.recursive_size)selected.set(i,d);}
 }
 const candidates=new Map(),observedLocalePrefixes=new Set();
 const baseNames=new Map(tables.map(x=>[x.toLowerCase()+'.datc64',x]));
 const scPath=s=>s.split('/').some(x=>/^(simplified chinese|simplified_chinese|simplified-chinese|zh-cn|zh_cn|zh-hans|zh_hans)$/i.test(x));
 for(const t of tables)for(const prefix of ['Data/Balance/','Data/Balance/Simplified Chinese/']){
  let name=prefix+t+'.datc64';candidates.set(name.toLowerCase(),{query_path:name,table:t,kind:prefix.includes('Simplified')?'exact_simplified_chinese':'exact_default',directory_confirmed:false});
 }
 let dirsParsed=0,pathsExamined=0;
 for(const d of selected.values()){
  fail(d.size<16*1024*1024,'Directory segment unexpectedly large');const b=range(d.offset,d.size);
  let off=0,baseMode=false,temp=[];
  while(off<=b.length-4){
   let idx=b.readUInt32LE(off);off+=4;if(idx===0){baseMode=!baseMode;if(baseMode)temp=[];continue;}idx--;
   let end=b.indexOf(0,off);fail(end>=off,'Directory string unterminated');
   let tail=b.toString('utf8',off,end),s=(idx<temp.length?temp[idx]:'')+tail;off=end+1;
   if(baseMode){temp.push(s);continue;}
   pathsExamined++;
   let norm=s.replace(/\\/g,'/'),lower=norm.toLowerCase();
   fail(lower.startsWith('data/balance/')||lower.startsWith('data/simplified chinese/'),'Selected directory decoded outside allowed prefix: '+norm);
   let parts=norm.split('/');if(parts.length>3)observedLocalePrefixes.add(parts.slice(0,-1).join('/'));
   const t=baseNames.get(parts.at(-1).toLowerCase());if(!t)continue;
   if(lower.startsWith('data/balance/')||scPath(norm)){
    let old=candidates.get(lower);
    candidates.set(lower,{...old,query_path:old?.query_path??norm,observed_exact_path:norm,table:t,kind:scPath(norm)?'explicit_simplified_chinese':(old?.kind??'other_locale_or_subdirectory'),directory_confirmed:true});
   }
  }
  dirsParsed++;
 }
 out.directory_container.raw_bytes_decoded=dirDecoded;
 out.lookup.directory_records_parsed=dirsParsed;out.lookup.paths_examined_within_selected_prefixes=pathsExamined;
 out.lookup.observed_locale_prefixes=[...observedLocalePrefixes].filter(x=>x.split('/').length<=4).slice(0,40);
 const targets=new Map();for(const c of candidates.values()){let hash=h64(c.observed_exact_path??c.query_path,seed).toString();if(!targets.has(hash))targets.set(hash,[]);targets.get(hash).push(c);}
 for(let i=0;i<fc;i++){
  let o=ft+20*i,key=raw.readBigUInt64LE(o).toString(),list=targets.get(key);if(!list)continue;
  let bi=raw.readUInt32LE(o+8),offset=raw.readUInt32LE(o+12),length=raw.readUInt32LE(o+16);fail(bi<bundles.length&&offset+length<=bundles[bi].raw,'Record bounds');
  for(const c of list){fail(!c.record,'Duplicate hash');c.record={record_index:i,path_hash:'0x'+BigInt(key).toString(16),bundle_index:bi,bundle_relative_path:'Bundles2/'+bundles[bi].name+'.bundle.bin',bundle_raw_bytes:bundles[bi].raw,offset,length};}
 }
 out.tables=tables.map(t=>({table:t,default:[...candidates.values()].find(c=>c.table===t&&c.kind==='exact_default')??null,simplified_chinese:[...candidates.values()].filter(c=>c.table===t&&(c.kind.includes('simplified')||scPath(c.query_path))).map(c=>({...c,status:c.record?'present':'absent'})),other_locale_paths:[...candidates.values()].filter(c=>c.table===t&&c.kind==='other_locale_or_subdirectory'&&c.record).map(c=>({path:c.observed_exact_path,record:c.record}))}));
 for(const row of out.tables)if(row.default)row.default.status=row.default.record?'present':'absent';
 sample();
 out.resources=[];let exampleCount=0;
 for(const t of []){
  const choices=[...candidates.values()].filter(c=>c.table===t&&c.record&&scPath(c.observed_exact_path??c.query_path));
  for(const choice of choices){
   let r=choice.record;fail(r.length<=32*1024*1024,'Target resource too large for small probe');
   let filename=path.resolve(ROOT,r.bundle_relative_path);fail(filename.startsWith(path.resolve(ROOT,'Bundles2')+path.sep),'Path traversal');
   let f=fs.openSync(filename,'r'),pre=fs.fstatSync(f,{bigint:true});
   try{
    const c=hdr((o,n)=>rd(f,o,n),Number(pre.size));fail(c.h.raw64===r.bundle_raw_bytes,'Bundle raw mismatch');
    const first=Math.floor(r.offset/c.h.chunk_size),last=Math.floor((r.offset+r.length-1)/c.h.chunk_size);
    let projected=0;for(let i=first;i<=last;i++)projected+=c.sizes[i];fail(resourceCompressed+projected<=16*1024*1024,'Resource compressed budget');
    const rawResource=Buffer.alloc(r.length),chunks=[];let copied=0;
    for(let i=first;i<=last;i++){const b=c.reader(c.offsets[i],c.sizes[i]);resourceCompressed+=b.length;let n=Math.min(c.h.chunk_size,c.h.raw64-i*c.h.chunk_size),buf=dec(b,n),lo=Math.max(0,r.offset-i*c.h.chunk_size),hi=Math.min(n,r.offset+r.length-i*c.h.chunk_size);buf.copy(rawResource,copied,lo,hi);copied+=hi-lo;chunks.push({index:i,compressed_offset:c.offsets[i],compressed_length:b.length,sha256:sha(b),raw_length:n});}
    fail(copied===r.length,'Incomplete target');
    const post=fs.fstatSync(f,{bigint:true});fail(same(pre,post)&&same(pre,fs.statSync(filename,{bigint:true})),'Resource bundle changed');
    // Scan only printable, NUL-terminated UTF-16LE sequences; no DAT columns inferred.
    const examples=[],seen=new Set();let readableCount=0;
    for(let parity=0;parity<2;parity++){
     let runStart=parity,chars=[];
     for(let i=parity;i+1<rawResource.length;i+=2){
      let v=rawResource.readUInt16LE(i),printable=(v>=32&&v<=0x7e)||(v>=0x3000&&v<=0x9fff)||(v>=0xff00&&v<=0xffef);
      if(printable){if(!chars.length)runStart=i;chars.push(v);if(chars.length>512)chars=[];}
      else{
       if(v===0&&chars.length>=2&&chars.length<=120&&chars.some(c=>c>=0x3400&&c<=0x9fff)){
        let text=String.fromCharCode(...chars);if(!seen.has(text)){seen.add(text);readableCount++;if(examples.length<10&&exampleCount<20){examples.push({byte_offset:runStart,text,interpretation:'Unmapped UTF-16LE text candidate; not a decoded DAT field.'});exampleCount++;}}
       }chars=[];
      }
     }
    }
    out.resources.push({table:t,path:choice.observed_exact_path??choice.query_path,length:r.length,sha256:sha(rawResource),bundle_before:id(pre),bundle_after:id(post),stable:true,chunks,readable_cjk_text_candidate_count:readableCount,examples,schema_decode_performed:false});sample();
   }finally{fs.closeSync(f);}
  }
 }
 out.index.final_path_stat=id(fs.statSync(ip,{bigint:true}));fail(JSON.stringify(out.index.final_path_stat)===JSON.stringify(out.index.before),'Index changed by end');
 out.status='completed';
 out.scope={filesystem_writes:false,temporary_files:false,installations:false,client_started:false,accounts_or_logs_read:false,old_spark_evidence_touched:false,game_data_network_fetch:false,network:'Only fixed public decoder package and format-source documentation',patch:null,server_region:null,default_table_language:'unverified',sc_label_meaning:'Explicit indexed locale path only; no inference of realm or whole-client patch',dat_schema_decode:false};
 out.unresolved=['No fixed schema provided: names/description columns not decoded.','Default tables alone do not prove language.','Locale search limited to decoded Data/Balance subtree and exact Data/Simplified Chinese prefix variants; no whole-client path inventory.'];
})().catch(e=>{out.status='blocked';out.error={message:e.message,stack:e.stack?.split('\n').slice(0,4)};}).finally(()=>{
 out.stats={game_bytes_read:readBytes,resource_compressed_bytes_read:resourceCompressed,total_raw_bytes_decoded:decodedTotal,directory_raw_bytes_decoded:dirDecoded,peak_sampled_rss:peakRSS,max_rss:process.resourceUsage().maxRSS*1024,elapsed_seconds:(performance.now()-start)/1000,output_bytes:0};
 for(let i=0;i<3;i++)out.stats.output_bytes=Buffer.byteLength(JSON.stringify(out));
 let j=JSON.stringify(out);if(Buffer.byteLength(j)>32768)j=JSON.stringify({status:'output_limit',bytes:Buffer.byteLength(j),index:out.index,stats:out.stats});console.log(j);
});
