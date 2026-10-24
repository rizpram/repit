"""Live AI provider check: `python -m app.ai_check` inside the REPIT container.

Sends one tiny text prompt per (feature, provider) in each configured chain and
prints only feature, provider, model and OK / failure class. No keys, prompts
or model output are printed. Each call may count against free-tier limits.
Exit code 0 only when every enabled feature has at least one working provider.
"""
import asyncio
import sys
from app import ai

async def probe(provider,name):
    from aiohttp import ClientSession, ClientTimeout
    url,headers,body=ai.build(provider,name,'Reply with the single word OK.','Ping',None,False,64)
    try:
        async with ClientSession(timeout=ClientTimeout(total=ai.TIMEOUT)) as session:
            async with session.post(url,headers=headers,json=body,allow_redirects=False) as response:
                if response.status!=200:
                    return f'FAILED HTTP {response.status}'
                ai.read(provider,await response.json())
        return 'OK'
    except ai.ProviderError as error:
        return 'FAILED '+error.args[0]
    except Exception as error:
        return 'FAILED '+type(error).__name__

async def main():
    healthy=True
    for feature in ai.ENABLE_ENV:
        if not ai.enabled(feature):
            print(f'{feature}: disabled')
            continue
        chain=ai.route(feature)
        if not chain:
            print(f'{feature}: ENABLED BUT NO PROVIDER KEY')
            healthy=False
            continue
        results=[]
        for provider in chain:
            name=ai.model(provider,feature)
            result=await probe(provider,name)
            results.append(result=='OK')
            print(f'{feature}: {ai.LABEL[provider]} {name} {result}')
        healthy=healthy and any(results)
    return 0 if healthy else 1

if __name__=='__main__':
    sys.exit(asyncio.run(main()))
