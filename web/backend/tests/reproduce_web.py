"""Opt-in live regression: exact reported question, default low-effort web route."""
import asyncio
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main
from harness import Harness
from internet import Internet

class TraceInternet(Internet):
    async def search(self, queries, limit, seen):
        print('queries:', queries, 'page_limit:', limit, flush=True)
        docs = await super().search(queries,limit,seen)
        print('read:', [{'url':d['url'],'characters':len(d['text']), 'has_definition': 'y học cổ truyền là' in d['text'].lower()} for d in docs],flush=True)
        return docs
    async def filter(self, question, documents, budget):
        print('filter_input:',len(documents),flush=True)
        docs = await super().filter(question,documents,budget)
        print('kept:', [{'url':d['url'],'score':d['decision_score'],'characters':len(d['text']), 'excerpt':d['text']} for d in docs],flush=True)
        return docs

async def run():
    import httpx
    async with httpx.AsyncClient(timeout=20) as client:
        request=main.ChatRequest(messages=[main.Message(role='user',content='y học cổ truyền là gì ?')],route='web',effort='low')
        result=await Harness(main.GraphKnowledge(),client,main.BASE_URL,os.environ['FPT_API_KEY'],main.MODEL,TraceInternet(client)).run(request)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        if '--assert' in sys.argv:
            assert result['route']=='web',result.get('reason')
            assert result['citations'] and result['usage']['model_calls']<=5

if __name__=='__main__': asyncio.run(run())
