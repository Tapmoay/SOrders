const fs=require('fs');
const files=['js/look.js'];
for(const f of files){
  const src=fs.readFileSync(f,'utf8');
  try{ new Function(src); console.log('OK', f, src.length); }catch(e){ console.log('FAIL', f, e.message); }
}