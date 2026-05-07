"""Flask CLI commands.

Story A introduces:
    flask create-user --username --display-name --email
    flask list-users

Story B adds:
    flask init-buckets
    flask purge-orphans
"""

import click

from app.extensions import db
from app.models.user import User


def register_commands(app):
    """Attach all CLI commands to the Flask app."""

    @app.cli.command("create-user")
    @click.option("--username", required=True, help="Unique username (lowercase, alphanumeric)")
    @click.option("--display-name", default=None, help="Free-form display name")
    @click.option("--email", default=None, help="Email address (optional)")
    def create_user(username, display_name, email):
        """Create a new user and print their generated API key."""
        existing = User.query.filter_by(username=username).first()
        if existing is not None:
            click.echo(f"ERROR: username {username!r} already exists")
            raise SystemExit(1)

        user = User(username=username, display_name=display_name, email=email)
        db.session.add(user)
        db.session.commit()

        click.echo(f"Created user: {user.id}")
        click.echo(f"  username:     {user.username}")
        click.echo(f"  display_name: {user.display_name}")
        click.echo(f"  email:        {user.email}")
        click.echo(f"  api_key:      {user.api_key}")

    @app.cli.command("list-users")
    def list_users():
        """List all users (api_keys redacted)."""
        users = User.query.order_by(User.created_at.desc()).all()
        if not users:
            click.echo("(no users)")
            return
        for u in users:
            click.echo(f"{u.id}  {u.username:<20}  {u.email or '-':<30}  {u.created_at.isoformat()}")

    @app.cli.command("init-buckets")
    def init_buckets():
        """Create the public + private MinIO buckets and configure CORS."""
        from app.services.storage_service import storage_service

        cfg = app.config
        storage_service.init_buckets(
            public_bucket=cfg["MEDIA_PUBLIC_BUCKET"],
            private_bucket=cfg["MEDIA_PRIVATE_BUCKET"],
            cors_origins=cfg.get("CORS_ORIGINS", "*"),
        )
        click.echo(
            f"Initialized buckets: "
            f"public={cfg['MEDIA_PUBLIC_BUCKET']}, "
            f"private={cfg['MEDIA_PRIVATE_BUCKET']}"
        )

    @app.cli.command("purge-orphans")
    @click.option(
        "--days",
        default=30,
        help="Hard-delete soft-deleted media older than this many days.",
    )
    def purge_orphans(days):
        """Hard-delete soft-deleted media older than --days."""
        from app.services.media_service import media_service

        purged = media_service.purge_deleted_media(older_than_days=days)
        click.echo(f"Purged {purged} soft-deleted media item(s) older than {days} days.")
