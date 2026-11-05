"""LangGraph RAG workflow with local retrieval and Zhipu GLM-4-Air synthesis."""
import os
from typing import TypedDict, List, Dict, Any
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from .retrieval import search

load_dotenv()

class KBState(TypedDict, total=False):
    question: str
    contexts: List[Dict[str, Any]]
    answer: str
    citations: List[Dict[str, str]]

def retrieve_node(state: KBState):
    return {"contexts": search(state.get("question", ""), k=5)}

def answer_node(state: KBState):
    contexts=state.get("contexts",[])
    citations=[{"source":c["source"],"heading":c["heading"],"id":c["id"]} for c in contexts]
    if not contexts:
        return {"answer":"知识库中暂无可引用材料。请先运行知识库构建命令，或补充相关资料。","citations":[]}
    provider=os.getenv("KB_LLM_PROVIDER","").lower()
    # 支持智谱GLM-4-Air
    if provider in ("zhipu","openai") and os.getenv("KB_LLM_API_KEY"):
        try:
            from openai import OpenAI
            base_url=os.getenv("KB_LLM_BASE_URL","https://open.bigmodel.cn/api/paas/v4")
            model=os.getenv("KB_LLM_MODEL","glm-4-air")
            client=OpenAI(api_key=os.getenv("KB_LLM_API_KEY"),base_url=base_url)
            excerpts="\n\n".join(f"[{c['source']} / {c['heading']}]\n{c['text']}" for c in contexts)
            res=client.chat.completions.create(
                model=model,
                messages=[
                    {"role":"system","content":"你是运费对账知识库助手。只根据提供的内部资料回答问题，不要编造。资料不足时明确说'尚未确认，需人工核实'。每个关键结论用 [source / heading] 标注来源。不得把推测说成事实。模型不认定合同变更、不批准结算、不付款扣费。"},
                    {"role":"user","content":f"问题：{state['question']}\n\n相关资料：\n{excerpts}"}
                ],
                temperature=0.1,
                max_tokens=1500
            )
            return {"answer":res.choices[0].message.content,"citations":citations}
        except Exception as e:
            return {"answer":f"模型服务暂不可用（{str(e)[:100]}）；以下为本地检索到的原文摘要。\n\n"+"\n\n".join(c["text"][:200] for c in contexts[:3]),"citations":citations}
    answer="本地检索到以下相关资料（未调用外部模型）：\n\n"+"\n\n".join(f"[{c['source']} / {c['heading']}]\n{c['text']}" for c in contexts[:3])
    return {"answer":answer,"citations":citations}

def build_graph():
    g=StateGraph(KBState)
    g.add_node("retrieve",retrieve_node)
    g.add_node("answer",answer_node)
    g.add_edge(START,"retrieve")
    g.add_edge("retrieve","answer")
    g.add_edge("answer",END)
    return g.compile()

kb_graph=build_graph()

def ask(question: str):
    return kb_graph.invoke({"question":question})
