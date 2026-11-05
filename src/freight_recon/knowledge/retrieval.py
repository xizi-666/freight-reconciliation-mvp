"""Lightweight TF-IDF retrieval; no external embedding API required."""
from pathlib import Path
import json, math, re
from collections import Counter

ROOT=Path(__file__).resolve().parents[3]
INDEX=ROOT/"data"/"index"/"chunks.jsonl"
TOKEN=re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")
STOP=set("的 了 和 是 在 与 及 对 把 有 为 按 什么 哪些 怎么 这个 那个 需要 可以 当前 项目 本次 我们 你们 进行 一个 以及 如果 不能 不得 应该 相关 说明 依据 结果 流程 是否".split())

def tokenize(text: str):
    raw=[x.lower() for x in TOKEN.findall(text)]
    # Keep Chinese bigrams to improve phrase matching while retaining single chars.
    out=[]
    for token in raw:
        if len(token)>1 and all('\u4e00' <= ch <= '\u9fff' for ch in token):
            out.extend(token[i:i+2] for i in range(len(token)-1))
        else: out.append(token)
    return [x for x in out if x not in STOP and len(x)>0]

def load_chunks():
    if not INDEX.exists(): return []
    return [json.loads(line) for line in INDEX.read_text(encoding="utf-8").splitlines() if line.strip()]

def search(query: str, k: int=5):
    docs=load_chunks()
    if not docs: return []
    q=Counter(tokenize(query)); terms=[Counter(tokenize(d["heading"]+" "+d["text"])) for d in docs]
    if not q: return []
    df=Counter()
    for c in terms: df.update(c.keys())
    n=len(docs); scores=[]
    for d,c in zip(docs,terms):
        score=0.0
        for term,qcount in q.items():
            if term in c:
                idf=math.log(1+(n-df[term]+0.5)/(df[term]+0.5))
                score += qcount*idf*(c[term]*2.2)/(c[term]+1.2*(0.25+0.75*sum(c.values())/max(1,80)))
        if score>0: scores.append((score,d))
    return [d for _,d in sorted(scores,key=lambda x:x[0],reverse=True)[:k]]
