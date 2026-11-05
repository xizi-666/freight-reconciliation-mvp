import argparse
from freight_recon.knowledge.ingest import main as ingest
from freight_recon.knowledge.graph import ask

def main():
    p=argparse.ArgumentParser(description="Freight reconciliation knowledge base")
    p.add_argument("question",nargs="?")
    p.add_argument("--rebuild",action="store_true")
    a=p.parse_args()
    if a.rebuild:
        ingest(); return
    if not a.question:
        p.error("provide a question or --rebuild")
    result=ask(a.question)
    print(result["answer"])
    if result.get("citations"):
        print("\nCitations:")
        for c in result["citations"]: print(f"- {c['source']} / {c['heading']} ({c['id']})")

if __name__=="__main__": main()
