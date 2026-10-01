import json
import httpx
import pytest
from src.motion_llm import DirectorConfig, DirectorAPIError, generate_json


def test_gemini_native_request_json_and_private_key(monkeypatch):
    original=httpx.Client
    captured=[]
    def handle(request):
        captured.append(request)
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'private reasoning'},{'text':'{"cue": {}}'}]}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kwargs: original(transport=httpx.MockTransport(handle),**kwargs))
    config=DirectorConfig('https://generativelanguage.googleapis.com/v1beta','gemini-3.8-flash','test-private-key')
    assert 'test-private-key' not in repr(config)
    assert generate_json(config,'测试导演输入')=={'cue':{}}
    request=captured[0];assert request.url.path.endswith('/models/gemini-3.8-flash:generateContent')
    assert request.headers['x-goog-api-key']=='test-private-key'
    assert 'test-private-key' not in str(request.url)
    data=json.loads(request.content)
    assert data['generationConfig']['responseMimeType']=='application/json'
    assert data['contents'][0]['parts'][0]['text']=='测试导演输入'


@pytest.mark.parametrize('status',[401,429,500,302])
def test_upstream_error_never_exposes_key_or_body(monkeypatch,status):
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs: original(transport=httpx.MockTransport(lambda request:httpx.Response(status,text='test-private-key upstream internal details')),**kwargs))
    with pytest.raises(DirectorAPIError) as error: generate_json(DirectorConfig('https://example.test','gemini-3.8-flash','test-private-key'),'prompt')
    assert 'test-private-key' not in str(error.value) and 'upstream internal details' not in str(error.value)


@pytest.mark.parametrize('finish',['MAX_TOKENS','SAFETY'])
def test_incomplete_generation_fails_before_json_parse(monkeypatch,finish):
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs: original(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'candidates':[{'finishReason':finish,'content':{'parts':[{'text':'{"a":1}'}]}}]})),**kwargs))
    with pytest.raises(DirectorAPIError):generate_json(DirectorConfig('https://example.test','gemini-3.8-flash','test-key'),'prompt')


def test_config_env_overrides_file_without_exposing_credentials(monkeypatch):
    from src.motion_llm import configuration
    monkeypatch.setattr('dotenv.dotenv_values',lambda *args:{'GEMINI_API_KEY':'file-secret','M2V_LLM_MODEL':'gemini-3.5-flash'})
    for key in ('M2V_LLM_API_KEY','M2V_LLM_BASE_URL','M2V_LLM_TIMEOUT','M2V_LLM_MAX_TOKENS','M2V_LLM_JSON_MODE'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('GEMINI_API_KEY','env-secret');monkeypatch.setenv('M2V_LLM_MODEL','gemini-3.8-flash')
    config=configuration();assert config.api_key=='env-secret' and config.model=='gemini-3.8-flash'
    assert 'secret' not in repr(config)
    monkeypatch.setenv('M2V_LLM_BASE_URL','https://api.test/?key=secret')
    with pytest.raises(DirectorAPIError): configuration()


def test_http_429_is_a_typed_quota_error(monkeypatch):
    from src.motion_llm import DirectorQuotaError
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda request:httpx.Response(429,json={'error':{'status':'RESOURCE_EXHAUSTED','message':'private details'}})),**kwargs))
    with pytest.raises(DirectorQuotaError):generate_json(DirectorConfig('https://example.test','gemini-3.8-flash','test-key'),'prompt')
