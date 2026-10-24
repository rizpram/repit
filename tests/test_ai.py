import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app import ai
from app.security import redact
from app.vision import coach_narrative, estimate_text, wants_text_estimate

KEYS={'OPENAI_API_KEY':'test-openai','ANTHROPIC_API_KEY':'test-anthropic','GEMINI_API_KEY':'test-gemini'}
CLEAN={k:'' for k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','GEMINI_API_KEY','VISION_ENABLED','VISION_MODEL',
       'AI_VISION_ENABLED','AI_FOOD_TEXT_ENABLED','AI_COACH_ENABLED','AI_ROUTE_VISION','AI_ROUTE_FOOD_TEXT',
       'AI_ROUTE_COACH','AI_MODEL_OPENAI','AI_MODEL_ANTHROPIC','AI_MODEL_GEMINI','AI_MODEL_ANTHROPIC_COACH')}

def responses(*items):
    """Fake aiohttp session returning (status, json) items in order."""
    made=[]
    for status,body in items:
        response=MagicMock(status=status)
        response.json=AsyncMock(return_value=body)
        response.__aenter__=AsyncMock(return_value=response)
        response.__aexit__=AsyncMock(return_value=False)
        made.append(response)
    session=MagicMock()
    session.post.side_effect=made
    session.__aenter__=AsyncMock(return_value=session)
    session.__aexit__=AsyncMock(return_value=False)
    return session

MEAL='{"description":"Nasi padang","calories":750,"protein_g":30,"carbs_g":90,"fat_g":28}'
OPENAI_OK={'choices':[{'message':{'content':MEAL}}]}
CLAUDE_OK={'content':[{'type':'text','text':'Poin 1'}]}
GEMINI_OK={'candidates':[{'content':{'parts':[{'text':'thinking','thought':True},{'text':MEAL}]}}]}

class RoutingTests(unittest.TestCase):
    def test_default_chains_follow_feature_strengths_and_skip_missing_keys(self):
        with patch.dict(os.environ,dict(CLEAN,**KEYS)):
            self.assertEqual(ai.route('vision'),['gemini','openai','anthropic'])
            self.assertEqual(ai.route('food_text'),['gemini','openai','anthropic'])
            self.assertEqual(ai.route('coach'),['gemini','anthropic','openai'])
        with patch.dict(os.environ,dict(CLEAN,GEMINI_API_KEY='g')):
            self.assertEqual([ai.route(f) for f in ai.ENABLE_ENV],[['gemini']]*3)
        with patch.dict(os.environ,dict(CLEAN,OPENAI_API_KEY='k')):
            self.assertEqual(ai.route('coach'),['openai'])
        with patch.dict(os.environ,CLEAN):
            self.assertEqual(ai.route('vision'),[])

    def test_route_and_model_overrides(self):
        with patch.dict(os.environ,dict(CLEAN,**KEYS,AI_ROUTE_COACH='gemini, bogus,gemini,openai',
                                        AI_MODEL_ANTHROPIC='m-all',AI_MODEL_ANTHROPIC_COACH='m-coach',VISION_MODEL='legacy')):
            self.assertEqual(ai.route('coach'),['gemini','openai'])
            self.assertEqual(ai.model('anthropic','coach'),'m-coach')
            self.assertEqual(ai.model('anthropic','vision'),'m-all')
            self.assertEqual(ai.model('openai','vision'),'legacy')
            self.assertEqual(ai.model('gemini','vision'),'gemini-3.8-flash')
            self.assertEqual(ai.model('gemini','food_text'),'gemini-3.5-flash-lite')
            self.assertEqual(ai.model('gemini','coach'),'gemini-3.8-flash')

    def test_enable_flags_are_opt_in_with_legacy_vision_flag(self):
        with patch.dict(os.environ,CLEAN):
            self.assertFalse(any(ai.enabled(f) for f in ai.ENABLE_ENV))
        env=dict(CLEAN,VISION_ENABLED='true'); del env['AI_VISION_ENABLED']
        with patch.dict(os.environ,env):
            os.environ.pop('AI_VISION_ENABLED',None)
            self.assertTrue(ai.enabled('vision'))

    def test_request_shapes(self):
        with patch.dict(os.environ,dict(CLEAN,**KEYS)):
            url,headers,body=ai.build('openai','m','sys','txt','IMG',True,100)
            self.assertEqual(body['response_format'],{'type':'json_object'})
            self.assertEqual(body['max_completion_tokens'],100)
            self.assertTrue(body['messages'][1]['content'][1]['image_url']['url'].endswith('IMG'))
            url,headers,body=ai.build('anthropic','m','sys','txt','IMG',True,100)
            self.assertEqual(headers['anthropic-version'],'2023-06-01')
            self.assertEqual(body['system'],'sys')
            self.assertEqual(body['messages'][0]['content'][0]['source']['data'],'IMG')
            url,headers,body=ai.build('gemini','gem-x','sys','txt','IMG',True,100)
            self.assertIn('/models/gem-x:generateContent',url)
            self.assertNotIn('test-gemini',url)
            self.assertEqual(headers,{'x-goog-api-key':'test-gemini'})
            self.assertEqual(body['generation_config'],{'max_output_tokens':100,'response_mime_type':'application/json'})
            self.assertEqual(body['contents'][0]['parts'][0]['inline_data'],{'mime_type':'image/jpeg','data':'IMG'})
            self.assertEqual(body['system_instruction'],{'parts':[{'text':'sys'}]})

    def test_extract_json_and_redaction(self):
        self.assertEqual(ai.extract_json('```json\n{"a":1}\n```'),{'a':1})
        with self.assertRaises(ai.ProviderError):
            ai.extract_json('no object')
        with patch.dict(os.environ,dict(CLEAN,ANTHROPIC_API_KEY='anthropic-secret-value')):
            self.assertNotIn('anthropic-secret-value',redact('x anthropic-secret-value'))
        self.assertNotIn('AIza',redact('key AIza'+'b'*35))

    def test_text_estimate_trigger(self):
        self.assertTrue(wants_text_estimate('/food nasi padang rendang'))
        self.assertFalse(wants_text_estimate('/food 550 35 60 18 Nasi ayam'))
        self.assertFalse(wants_text_estimate('/food'))
        self.assertFalse(wants_text_estimate('/weight 70'))

class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_vision_falls_back_from_gemini_to_openai(self):
        session=responses((400,{}),(200,OPENAI_OK))
        with patch.dict(os.environ,dict(CLEAN,**KEYS)),patch('aiohttp.ClientSession',return_value=session):
            provider,value=await ai.ask('vision','s','t',image='IMG',want_json=True)
        self.assertEqual(provider,'openai')
        self.assertEqual(value['calories'],750)
        self.assertIn('generateContent',session.post.call_args_list[0].args[0])

    async def test_all_providers_failing_returns_none(self):
        # Gemini 400 (no retry), OpenAI 429 twice (one retry), Claude empty text.
        session=responses((400,{}),(429,{}),(429,{}),(200,{'content':[]}))
        with patch.dict(os.environ,dict(CLEAN,**KEYS)),patch('aiohttp.ClientSession',return_value=session),patch.object(ai,'RETRY_DELAY',0):
            self.assertIsNone(await ai.ask('food_text','s','t',want_json=True))
        self.assertEqual(session.post.call_count,4)

    async def test_gemini_rate_limit_retried_once_then_succeeds(self):
        session=responses((429,{}),(200,GEMINI_OK))
        with patch.dict(os.environ,dict(CLEAN,GEMINI_API_KEY='g')),patch('aiohttp.ClientSession',return_value=session),patch.object(ai,'RETRY_DELAY',0):
            provider,value=await ai.ask('food_text','s','t',want_json=True)
        self.assertEqual((provider,value['calories']),('gemini',750))
        self.assertIn('gemini-3.5-flash-lite',session.post.call_args.args[0])

    async def test_gemini_blocked_or_truncated_is_a_failure(self):
        for body in ({'promptFeedback':{'blockReason':'SAFETY'}},{'candidates':[{'finishReason':'MAX_TOKENS','content':{}}]}):
            session=responses((200,body))
            with patch.dict(os.environ,dict(CLEAN,GEMINI_API_KEY='g')),patch('aiohttp.ClientSession',return_value=session):
                self.assertIsNone(await ai.ask('vision','s','t',want_json=True))

    async def test_gemini_thought_parts_ignored(self):
        session=responses((200,GEMINI_OK))
        with patch.dict(os.environ,dict(CLEAN,GEMINI_API_KEY='g')),patch('aiohttp.ClientSession',return_value=session):
            provider,value=await ai.ask('vision','s','t',want_json=True)
        self.assertEqual((provider,value['description']),('gemini','Nasi padang'))

    async def test_text_estimate_draft_and_disabled(self):
        with patch.dict(os.environ,CLEAN):
            self.assertIsNone(await estimate_text('/food nasi padang'))
        session=responses((200,GEMINI_OK))
        with patch.dict(os.environ,dict(CLEAN,**KEYS,AI_FOOD_TEXT_ENABLED='true')),patch('aiohttp.ClientSession',return_value=session):
            meal=await estimate_text('/food nasi padang rendang')
        self.assertEqual((meal['ai_provider'],meal['origin'],meal['calories']),('Gemini','text',750))
        self.assertIn('generativelanguage.googleapis.com',session.post.call_args.args[0])

    async def test_coach_narrative_gemini_first_claude_fallback_and_labelled(self):
        with patch.dict(os.environ,dict(CLEAN,**KEYS)):
            self.assertEqual(await coach_narrative('REPIT Weekly Review'),'')
        gemini_text={'candidates':[{'content':{'parts':[{'text':'Poin 1'}]}}]}
        session=responses((200,gemini_text))
        with patch.dict(os.environ,dict(CLEAN,GEMINI_API_KEY='g',AI_COACH_ENABLED='true')),patch('aiohttp.ClientSession',return_value=session):
            self.assertIn('Analisis AI (Gemini)',await coach_narrative('REPIT Weekly Review'))
        session=responses((400,{}),(200,CLAUDE_OK))
        with patch.dict(os.environ,dict(CLEAN,**KEYS,AI_COACH_ENABLED='true')),patch('aiohttp.ClientSession',return_value=session):
            text=await coach_narrative('REPIT Weekly Review')
        self.assertIn('Analisis AI (Claude)',text)
        self.assertIn('api.anthropic.com',session.post.call_args.args[0])
        session=responses(*[(400,{})]*3)
        with patch.dict(os.environ,dict(CLEAN,**KEYS,AI_COACH_ENABLED='true')),patch('aiohttp.ClientSession',return_value=session):
            self.assertIn('tidak tersedia',await coach_narrative('REPIT Weekly Review'))

    async def test_live_check_reports_without_output_or_keys(self):
        from app import ai_check
        import io, contextlib
        session=responses((200,GEMINI_OK),(403,{}))
        out=io.StringIO()
        env=dict(CLEAN,GEMINI_API_KEY='secret-gem',AI_VISION_ENABLED='true',AI_COACH_ENABLED='true')
        with patch.dict(os.environ,env),patch('aiohttp.ClientSession',return_value=session),contextlib.redirect_stdout(out):
            code=await ai_check.main()
        text=out.getvalue()
        self.assertEqual(code,1)
        self.assertIn('vision: Gemini gemini-3.8-flash OK',text)
        self.assertIn('coach: Gemini gemini-3.8-flash FAILED HTTP 403',text)
        self.assertIn('food_text: disabled',text)
        self.assertNotIn('secret-gem',text)
        self.assertNotIn('Nasi padang',text)
