#!/usr/bin/env python3
import ast,json,re,subprocess
from pathlib import Path
from dataclasses import dataclass,asdict
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/".audit"/"generated"; BIN={".png",".jpg",".jpeg",".gif",".webp",".ico",".pdf",".zip",".gz",".zst",".jar",".apk",".so",".dll",".dylib",".class",".pyc",".woff",".woff2",".ttf",".otf",".mp3",".mp4",".wav",".sqlite",".db",".pdn"}
@dataclass(frozen=True)
class F:path:str; line:int; severity:str; rule:str; message:str
@dataclass(frozen=True)
class S:path:str; reason:str
def main():
 head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(); raw=subprocess.run(["git","ls-files","-z"],cwd=ROOT,check=True,stdout=subprocess.PIPE).stdout; fs=[x.decode("utf-8","surrogateescape") for x in raw.split(b"\0") if x]; finds=[]; skips=[]; nf=nl=0; conflict=re.compile(r"^(<{7}|={7}|>{7})(?:\s|$)")
 for rel in fs:
  p=ROOT/rel
  if not p.exists() or p.is_dir(): skips.append(S(rel,"absent/gitlink/directory")); continue
  if p.suffix.lower() in BIN: skips.append(S(rel,"binary")); continue
  b=p.read_bytes()
  if b"\0" in b[:8192]: skips.append(S(rel,"binary content")); continue
  try:t=b.decode("utf-8")
  except UnicodeDecodeError: skips.append(S(rel,"non-UTF8")); continue
  lines=t.splitlines(keepends=True); nf+=1; nl+=max(1,len(lines))
  for i,line in enumerate(lines,1):
   x=line.rstrip("\r\n")
   if conflict.match(x): finds.append(F(rel,i,"BLOCKER","MERGE_MARKER","unresolved merge marker"))
   if x.endswith(" ") or x.endswith("\t"): finds.append(F(rel,i,"INFO","TRAILING_WHITESPACE","trailing whitespace"))
  if p.suffix.lower()==".py":
   try:tree=ast.parse(t,filename=rel)
   except SyntaxError as e: finds.append(F(rel,e.lineno or 0,"BLOCKER","PY_SYNTAX",e.msg)); continue
   for n in ast.walk(tree):
    if isinstance(n,ast.ExceptHandler) and n.type is None: finds.append(F(rel,n.lineno,"WARN","BARE_EXCEPT","bare except"))
    if isinstance(n,ast.Call):
     f=n.func
     if isinstance(f,ast.Name) and f.id in {"eval","exec"}: finds.append(F(rel,n.lineno,"BLOCKER","DYNAMIC_EXEC",f.id))
     if isinstance(f,ast.Attribute) and isinstance(f.value,ast.Name) and f.value.id=="os" and f.attr=="system": finds.append(F(rel,n.lineno,"BLOCKER","OS_SYSTEM","os.system"))
     if isinstance(f,ast.Attribute) and f.attr in {"Popen","run","call","check_call","check_output"} and any(k.arg=="shell" and isinstance(k.value,ast.Constant) and k.value.value is True for k in n.keywords): finds.append(F(rel,n.lineno,"BLOCKER","SUBPROCESS_SHELL_TRUE","shell=True"))
 sev=Counter(x.severity for x in finds); rpt={"schema_version":"1.1.0","audited_commit":head,"tracked_files":len(fs),"audited_text_files":nf,"audited_lines":nl,"skip_count":len(skips),"severity_counts":dict(sev),"skipped":[asdict(x) for x in skips],"findings":[asdict(x) for x in finds]}; OUT.mkdir(parents=True,exist_ok=True); (OUT/"full-code-audit.json").write_text(json.dumps(rpt,indent=2)+"\n"); print(json.dumps({k:rpt[k] for k in ("audited_commit","tracked_files","audited_text_files","audited_lines","skip_count","severity_counts")})); return 1 if sev.get("BLOCKER") else 0
if __name__=="__main__": raise SystemExit(main())