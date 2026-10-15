"""Opt-in live check: makes one JEV request, no secrets in output."""
import asyncio
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('USE_TF','0')
os.environ.setdefault('HF_HOME',str(ROOT/'.model-cache'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')

async def main():
    import httpx
    from harness import Budget, PROFILES
    from internet import Decisions, Internet
    state={'query':'Thủ đô Việt Nam là gì?', 'text':'Hà Nội là thủ đô của Việt Nam.'}
    questions={'relevant':{'type':'choice','instructions':'Does text answer query?',
        'criteria':{'direct':'Provides the requested information','irrelevant':'Does not answer'}}}
    async with httpx.AsyncClient(timeout=20) as client:
        decisions=Decisions(client)
        response=await decisions.predict(state,questions,Budget(PROFILES['low']))
        print('jev:',response['relevant'])
        internet=Internet(client)
        docs=await internet.search(['Crawl4AI Python AsyncWebCrawler documentation'],1,set())
        print('search/read:', [{'url':d['url'],'characters':len(d['text'])} for d in docs])

if __name__=='__main__': asyncio.run(main())
