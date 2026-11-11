from .base import *

# Ambiente de testes: nunca depende de um banco real nem de credenciais
# reais do Supabase. Isso permite rodar `manage.py test` sem um `.env`
# com um DATABASE_URL de produção/homologação.

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'test_db.sqlite3',
    }
}

# Valores dummy só para o settings carregar (nenhuma chamada de rede real é
# feita nos testes: o upload de avatar para o Supabase é mockado).
SUPABASE_URL = env('SUPABASE_URL', default='https://dummy-local.supabase.co')
SUPABASE_SERVICE_KEY = env('SUPABASE_SERVICE_KEY', default='dummy-local-service-key')

# Hashing de senha mais rápido para acelerar a suíte de testes.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# E-mails nunca saem de verdade nos testes.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
FRONTEND_URL = 'http://frontend.test'

# Cookie do refresh sem Secure: testes e e2e rodam em http://localhost.
REFRESH_COOKIE_SECURE = False

# Contadores de limite em memória (sem tabela de cache) e limites altos: os testes
# que exercitam o 429 baixam a taxa explicitamente.
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'test-default'},
    'ratelimit': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'test-ratelimit'},
}
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_RATES': {scope: '100000/min' for scope in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']},
}
LOGIN_FAILURE_LIMIT = 1000
PASSWORD_RESET_EMAIL_ASYNC = False
ENABLE_DOCS = True
