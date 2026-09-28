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
