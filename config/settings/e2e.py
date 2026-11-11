from .testing import *

# Ambiente do e2e de integração (frontend + backend reais, e-mail em arquivo).
# Banco SQLite descartável e e-mails gravados em disco: nenhuma chave real
# (Brevo/Resend/Supabase) é usada.

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'e2e_db.sqlite3',
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
EMAIL_FILE_PATH = str(BASE_DIR / '.e2e_mail')
FRONTEND_URL = 'http://localhost:5189'

# Hash real/rápido não importa aqui; limites altos para o teste não flutuar.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_RATES': {
        **REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'],
        'password_reset_request': '10000/hour',
        'password_reset_confirm': '10000/hour',
    },
}
