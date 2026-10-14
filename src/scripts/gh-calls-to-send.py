# Rewrites s.GH("api", "-X", M, "-f", "k=v", ..., path) calls into s.GitHub.Send(M, path, github.F("k", v), ...), as the github I/O module (#63) needed across src/internal/issues.
import re,sys
def split_args(s):
    out=[];depth=0;cur='';i=0;instr=None
    while i<len(s):
        c=s[i]
        if instr:
            cur+=c
            if c=='\\' and instr=='"': cur+=s[i+1]; i+=2; continue
            if c==instr: instr=None
        elif c in '"`': instr=c; cur+=c
        elif c in '([{': depth+=1; cur+=c
        elif c in ')]}': depth-=1; cur+=c
        elif c==',' and depth==0: out.append(cur.strip()); cur=''
        else: cur+=c
        i+=1
    if cur.strip(): out.append(cur.strip())
    return out
def find_close(s,i):
    depth=0;instr=None
    while i<len(s):
        c=s[i]
        if instr:
            if c=='\\' and instr=='"': i+=2; continue
            if c==instr: instr=None
        elif c in '"`': instr=c
        elif c=='(' : depth+=1
        elif c==')':
            depth-=1
            if depth==0: return i
        i+=1
def field(flag,e):
    m=re.match(r'^"([^"=]+)=(.*)"$',e)
    if m: return 'github.F("%s", "%s")'%(m.group(1),m.group(2))
    m=re.match(r'^"([^"=]+)="\s*\+\s*(.*)$',e,re.S)
    if m: return 'github.F("%s", %s)'%(m.group(1),m.group(2))
    m=re.match(r'^fmt\.Sprintf\("([^"=]+)=%d",\s*(.*)\)$',e,re.S)
    if m and flag=='"-F"': return 'github.Int("%s", %s)'%(m.group(1),m.group(2))
    m=re.match(r'^fmt\.Sprintf\("([^"=]+)=(.*)",\s*(.*)\)$',e,re.S)
    if m: return 'github.F("%s", fmt.Sprintf("%s", %s))'%(m.group(1),m.group(2),m.group(3))
    raise Exception('field? '+e)
for p in sys.argv[1:]:
    s=open(p).read();out='';i=0;n=0
    while True:
        j=s.find('s.GH(',i)
        if j<0: out+=s[i:];break
        k=find_close(s,j+4)
        args=split_args(s[j+5:k])
        if args[0]!='"api"' or len(args)<3 or args[1]!='"-X"':
            print('SKIP',p,s[j:k+1][:120]); out+=s[i:k+1]; i=k+1; continue
        method=args[2]; rest=args[3:-1]; path=args[-1]
        fs=[field(rest[a],rest[a+1]) for a in range(0,len(rest),2)]
        out+=s[i:j]+'s.GitHub.Send('+', '.join([method,path]+fs)+')'
        i=k+1;n+=1
    open(p,'w').write(out); print(p,n)
