"""Multi-provider AI routing: OpenAI, Anthropic Claude and Google Gemini.

Each AI feature has an ordered provider chain chosen for what that provider
does best; the next provider is tried only when one is unconfigured or fails.
Every feature is opt-in. Provider responses, photos and meal text are never
logged: only the feature, provider name and failure class.
"""
import json
import logging
import os

PROVIDERS=('openai','anthropic','gemini')
KEY_ENV={'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY','gemini':'GEMINI_API_KEY'}
LABEL={'openai':'OpenAI','anthropic':'Claude','gemini':'Gemini'}
DEFAULT_MODEL={'openai':'gpt-6-luna','anthropic':'claude-sonnet-5-5','gemini':'gemini-3.8-flash'}
# vision: Gemini Flash is strong and cheap on food photos.
# food_text: OpenAI small model gives fast, reliable structured JSON.
# coach: Claude writes the most careful Indonesian narrative from aggregates.
DEFAULT_ROUTE={'vision':('gemini','openai','anthropic'),
               'food_text':('openai','gemini','anthropic'),
               'coach':('anthropic','gemini','openai')}
ENABLE_ENV={'vision':'AI_VISION_ENABLED','food_text':'AI_FOOD_TEXT_ENABLED','coach':'AI_COACH_ENABLED'}
URLS={'openai':'https://api.openai.com/v1/chat/completions',
      'anthropic':'https://api.anthropic.com/v1/messages',
      'gemini':'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'}
TIMEOUT=45
# Generous: reasoning/thinking tokens count against these limits.
MAX_TOKENS={'vision':2000,'food_text':1500,'coach':3000}

class ProviderError(Exception):
    pass

def enabled(feature):
    value=os.getenv(ENABLE_ENV[feature])
    if value is None and feature=='vision':
        value=os.getenv('VISION_ENABLED')  # Phase 1.2 compatibility
    return (value or 'false').lower()=='true'

def model(provider,feature):
    legacy=os.getenv('VISION_MODEL') if provider=='openai' and feature=='vision' else None
    return (os.getenv(f'AI_MODEL_{provider.upper()}_{feature.upper()}') or legacy
            or os.getenv(f'AI_MODEL_{provider.upper()}') or DEFAULT_MODEL[provider])

def route(feature):
    """Configured providers for a feature, in order. Unknown names are ignored."""
    raw=os.getenv(f'AI_ROUTE_{feature.upper()}')
    order=[p.strip().lower() for p in raw.split(',')] if raw else list(DEFAULT_ROUTE[feature])
    chain=[]
    for provider in order:
        if provider in PROVIDERS and provider not in chain and os.getenv(KEY_ENV[provider]):
            chain.append(provider)
    return chain

def extract_json(text):
    start,end=text.find('{'),text.rfind('}')
    if start<0 or end<start:
        raise ProviderError('no json')
    value=json.loads(text[start:end+1])
    if not isinstance(value,dict):
        raise ProviderError('json not object')
    return value

def build(provider,name,system,text,image,want_json,max_tokens):
    """Return (url, headers, body) for one provider request."""
    key=os.environ[KEY_ENV[provider]]
    if provider=='openai':
        content=[{'type':'text','text':text}]
        if image:
            content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+image}})
        body={'model':name,'max_completion_tokens':max_tokens,
              'messages':[{'role':'system','content':system},{'role':'user','content':content}]}
        if want_json:
            body['response_format']={'type':'json_object'}
        return URLS['openai'],{'Authorization':'Bearer '+key},body
    if provider=='anthropic':
        content=[]
        if image:
            content.append({'type':'image','source':{'type':'base64','media_type':'image/jpeg','data':image}})
        content.append({'type':'text','text':text})
        return URLS['anthropic'],{'x-api-key':key,'anthropic-version':'2023-06-01'},{
            'model':name,'max_tokens':max_tokens,'system':system,'messages':[{'role':'user','content':content}]}
    parts=[]
    if image:
        parts.append({'inlineData':{'mimeType':'image/jpeg','data':image}})
    parts.append({'text':text})
    config={'maxOutputTokens':max_tokens}
    if want_json:
        config['responseMimeType']='application/json'
    return URLS['gemini'].format(model=name),{'x-goog-api-key':key},{
        'systemInstruction':{'parts':[{'text':system}]},
        'contents':[{'role':'user','parts':parts}],'generationConfig':config}

def read(provider,value):
    if provider=='openai':
        return value['choices'][0]['message']['content'] or ''
    if provider=='anthropic':
        return ''.join(block.get('text','') for block in value['content'] if block.get('type')=='text')
    return ''.join(part.get('text','') for part in value['candidates'][0]['content']['parts'] if not part.get('thought'))

async def ask(feature,system,text,image=None,want_json=False):
    """Try the feature's provider chain. Returns (provider, text|dict) or None."""
    from aiohttp import ClientSession, ClientTimeout
    chain=route(feature)
    if not chain:
        return None
    async with ClientSession(timeout=ClientTimeout(total=TIMEOUT)) as session:
        for provider in chain:
            try:
                url,headers,body=build(provider,model(provider,feature),system,text,image,want_json,MAX_TOKENS[feature])
                async with session.post(url,headers=headers,json=body,allow_redirects=False) as response:
                    if response.status!=200:
                        raise ProviderError(f'HTTP {response.status}')
                    output=read(provider,await response.json()).strip()
                if not output:
                    raise ProviderError('empty')
                return provider,(extract_json(output) if want_json else output)
            except Exception as error:
                reason=str(error) if isinstance(error,ProviderError) else type(error).__name__
                logging.warning('AI %s via %s failed (%s); trying next provider',feature,provider,reason)
    return None
