"""Cria (de forma idempotente) a conta oficial `twist` e suas playlists curadas.

    python manage.py seed_listas_oficiais
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.movies import tmdb
from apps.movies.models import Playlist, PlaylistMovie
from apps.movies.services import OFFICIAL_USERNAME, get_or_sync_movie

OFFICIAL_EMAIL = "twist@twist.app"

# (nome, descrição, [ids do TMDB])
OFFICIAL_LISTS = [
    (
        "Clássicos essenciais",
        "Filmes que todo cinéfilo deveria ver pelo menos uma vez.",
        [238, 240, 278, 424, 769, 389, 497, 13, 429, 11216],
    ),
    (
        "Para rir sem culpa",
        "Comédias que funcionam em qualquer dia ruim.",
        [8363, 4638, 18785, 771, 37165, 105, 2108, 120467, 585, 862],
    ),
    (
        "Ficção científica obrigatória",
        "Do cyberpunk às viagens espaciais: o melhor da ficção científica.",
        [78, 603, 62, 157336, 329865, 286217, 335984, 27205, 348, 679],
    ),
    (
        "Sustos para a madrugada",
        "Terror para assistir de luz apagada, por sua conta e risco.",
        [694, 539, 4232, 1091, 419430, 493922, 9552, 948, 138843, 346364],
    ),
    (
        "Tão ruins que são bons",
        "Produções que erram tanto que acabam virando diversão.",
        [17473, 10513, 415, 515001, 2048, 205321],
    ),
]


class Command(BaseCommand):
    help = "Cria a conta oficial 'twist' e as playlists oficiais (idempotente)."

    def handle(self, *args, **options):
        User = get_user_model()
        existing = User.objects.filter(username__iexact=OFFICIAL_USERNAME).first()
        if existing is not None and (
            existing.username != OFFICIAL_USERNAME
            or existing.has_usable_password()
            or not existing.is_staff
        ):
            raise CommandError(
                f"O usuário '{existing.username}' já existe e não é a conta oficial criada por este "
                "comando (conta staff com senha inutilizável). Abortando para não "
                "publicar listas oficiais em uma conta comum; renomeie ou remova essa conta antes."
            )
        owner, created = User.objects.get_or_create(
            username=OFFICIAL_USERNAME,
            defaults={"email": OFFICIAL_EMAIL, "is_staff": True},
        )
        if created:
            owner.set_unusable_password()
            owner.save(update_fields=["password"])

        for name, description, tmdb_ids in OFFICIAL_LISTS:
            playlist, _ = Playlist.objects.get_or_create(
                owner=owner, name=name,
                defaults={"description": description, "is_public": True},
            )
            added = self._fill(playlist, tmdb_ids)
            self.stdout.write(f"{name}: {added} filme(s) adicionado(s).")

        self.stdout.write(self.style.SUCCESS("Listas oficiais atualizadas."))

    def _fill(self, playlist, tmdb_ids):
        existing = set(playlist.playlist_movies.values_list("movie__provider_movie_id", flat=True))
        position = playlist.playlist_movies.count()
        added = 0
        for tmdb_id in tmdb_ids:
            if tmdb_id in existing:
                continue
            try:
                movie = get_or_sync_movie(tmdb_id)
            except tmdb.TMDBError as exc:
                self.stderr.write(self.style.WARNING(f"  Pulando TMDB {tmdb_id}: {exc}"))
                continue
            with transaction.atomic():
                _, was_created = PlaylistMovie.objects.get_or_create(
                    playlist=playlist, movie=movie, defaults={"position": position},
                )
            if was_created:
                position += 1
                added += 1
        return added
