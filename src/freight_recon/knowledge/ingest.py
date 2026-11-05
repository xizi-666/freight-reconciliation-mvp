"""Split project Markdown into searchable chunks with source metadata."""
from pathlib import Path
import json, re

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / "data" / "knowledge"
OUT = ROOT / "data" / "index" / "chunks.jsonl"

def split_md(text: str, limit: int = 900):
    sections = re.split(r"(?m)(?=^#{1,3} )", text)
    chunks=[]
    for section in sections:
        section=section.strip()
        if not section: continue
        heading=section.splitlines()[0][:180]
        paragraphs=re.split(r"\n\s*\n", section)
        buf=""
        for para in paragraphs:
            if len(buf)+len(para)>limit and buf:
                chunks.append((heading,buf.strip())); buf=""
            buf += ("\n\n" if buf else "")+para
        if buf: chunks.append((heading,buf.strip()))
    return chunks

def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for path in sorted(KB.glob("*.md")):
        for i,(heading,text) in enumerate(split_md(path.read_text(encoding="utf-8"))):
            rows.append({"id":f"{path.stem}:{i+1}","source":path.name,"heading":heading,"text":text})
    OUT.write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in rows),encoding="utf-8")
    print(f"Indexed {len(rows)} chunks from {len(list(KB.glob('*.md')))} documents -> {OUT}")

if __name__=="__main__": main()
